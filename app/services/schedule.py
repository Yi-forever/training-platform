"""课表（课次）业务规则：从班级周排课规则生成课次，并按身份返回课表。

班级的 ``schedule`` 仍是面向用户的自由文本（如「周六 09:00-10:30」、
「周一/三/五 09:00-12:00」），本模块负责解析为「星期 + 起止时间」，
再按开班/结课日期展开成具体课次（class_sessions），供员工课表与三端门户使用。
"""
import re
from datetime import date, timedelta
from typing import Any

from app.core.exceptions import BizException
from app.db.repository import db
from app.services.base import today

WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
SESSION_STATUSES = ("待上课", "已完成", "已取消")
MAX_SESSIONS_PER_GENERATE = 80
DEFAULT_RANGE_DAYS = 120

_SCHEDULE_RE = re.compile(
    r"(周[一二三四五六日天](?:\s*[/、,，]\s*周?[一二三四五六日天])*)\s*"
    r"(\d{1,2}:\d{2})\s*[-~—至]\s*(\d{1,2}:\d{2})"
)


def _norm_time(value: str) -> str:
    hour, minute = value.split(":")
    return f"{int(hour):02d}:{int(minute):02d}"


def parse_schedule(text: str | None) -> dict[str, Any] | None:
    """解析「周六 09:00-10:30」「周一/三/五 09:00-12:00」等排课文本。

    返回 ``{weekdays: [0-6], startTime, endTime}``；无法识别时返回 None。
    """
    if not text:
        return None
    match = _SCHEDULE_RE.search(text)
    if not match:
        return None
    weekdays = sorted({WEEKDAYS[ch] for ch in match.group(1) if ch in WEEKDAYS})
    if not weekdays:
        return None
    return {
        "weekdays": weekdays,
        "startTime": _norm_time(match.group(2)),
        "endTime": _norm_time(match.group(3)),
    }


def _as_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _attendance_map() -> dict[tuple[str, str], dict[str, int]]:
    result: dict[tuple[str, str], dict[str, int]] = {}
    for row in db.alive("attendance"):
        key = (row.get("classId") or "", row.get("date") or "")
        bucket = result.setdefault(key, {"出勤": 0, "迟到": 0, "请假": 0, "缺勤": 0})
        if row.get("status") in bucket:
            bucket[row["status"]] += 1
    return result


class ScheduleService:
    # ---------- 生成 ----------

    def generate_for_class(self, class_id: str, *, from_date: str | None = None) -> int:
        cls = db.locate("classes", class_id or "", label="班级")
        parsed = parse_schedule(cls.get("schedule"))
        if not parsed:
            raise BizException(400, f"班级「{cls.get('name')}」的上课时间无法识别，请按「周六 09:00-10:30」格式填写")

        start = _as_date(from_date) or _as_date(cls.get("startDate")) or date.fromisoformat(today())
        class_start = _as_date(cls.get("startDate"))
        if class_start and start < class_start:
            start = class_start
        end = _as_date(cls.get("endDate")) or (start + timedelta(days=DEFAULT_RANGE_DAYS))
        end = min(end, start + timedelta(days=365))
        if end < start:
            return 0

        existing = {
            (s.get("date"), s.get("startTime"))
            for s in db.alive("sessions")
            if s.get("classId") == class_id
        }
        ts = today()
        created = 0
        cursor = start
        while cursor <= end and created < MAX_SESSIONS_PER_GENERATE:
            if cursor.weekday() in parsed["weekdays"]:
                key = (cursor.isoformat(), parsed["startTime"])
                if key not in existing:
                    db.insert("sessions", {
                        "id": db.next_code("sessions", "SK"),
                        "classId": class_id,
                        "teacherId": cls.get("teacherId"),
                        "date": cursor.isoformat(),
                        "startTime": parsed["startTime"],
                        "endTime": parsed["endTime"],
                        "classroom": cls.get("classroom"),
                        "topic": "",
                        "status": "待上课",
                        "createdAt": ts,
                        "updatedAt": ts,
                    })
                    existing.add(key)
                    created += 1
            cursor += timedelta(days=1)
        return created

    def sync_for_class(self, class_id: str) -> dict[str, int]:
        """排课规则变更后同步未来课次：保留已有考勤的历史课次，重建未上课的未来课次。"""
        cls = db.locate("classes", class_id or "", label="班级")
        if not parse_schedule(cls.get("schedule")):
            return {"removed": 0, "created": 0}
        today_str = today()
        attended_dates = {a.get("date") for a in db.alive("attendance") if a.get("classId") == class_id}
        removed = 0
        for session in db.alive("sessions"):
            if session.get("classId") != class_id:
                continue
            if session.get("date", "") < today_str:
                continue
            if session.get("status") != "待上课" or session.get("date") in attended_dates:
                continue
            db.soft_delete("sessions", session["id"], label="课次")
            removed += 1
        return {"removed": removed, "created": self.generate_for_class(class_id, from_date=today_str)}

    def ensure_all(self) -> int:
        """启动补齐：没有课次的班级按整学期生成；仅有历史课次的班级从今天续排。"""
        created = 0
        for cls in db.alive("classes"):
            if cls.get("status") == "已结课":
                continue
            sessions = [s for s in db.alive("sessions") if s.get("classId") == cls.get("id")]
            if not sessions:
                start = cls.get("startDate") or today()
            elif not any(s.get("date", "") >= today() for s in sessions):
                start = today()
            else:
                continue
            try:
                created += self.generate_for_class(cls["id"], from_date=start)
            except BizException:
                continue
        return created

    # ---------- 查询 ----------

    def list_sessions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        class_id: str | None = None,
        teacher_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._collect(start=start, end=end, class_id=class_id, teacher_id=teacher_id)

    def teacher_sessions(self, teacher_code: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        return self._collect(start=start, end=end, teacher_id=teacher_code)

    def student_sessions(self, student_code: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        stu = db.locate("students", student_code or "", label="学员")
        return self._collect(start=start, end=end, class_id=stu.get("classId"))

    def parent_sessions(
        self, parent_code: str, student_id: str | None = None,
        start: str | None = None, end: str | None = None,
    ) -> list[dict[str, Any]]:
        children = db.list_children_of(parent_code)
        if student_id:
            children = [c for c in children if c.get("id") == student_id]
            if not children:
                raise BizException(403, "该学员不在您的关联范围内")
        names = {c["id"]: c.get("name") for c in children}
        rows: list[dict[str, Any]] = []
        for child in children:
            for session in self._collect(start=start, end=end, class_id=child.get("classId")):
                rows.append({**session, "studentId": child["id"], "studentName": names.get(child["id"])})
        rows.sort(key=lambda r: (r.get("date") or "", r.get("startTime") or ""))
        return rows

    def next_session(self, class_ids: list[str]) -> dict[str, Any] | None:
        today_str = today()
        candidates = [
            s for s in db.alive("sessions")
            if s.get("classId") in set(class_ids)
            and s.get("date", "") >= today_str
            and s.get("status") == "待上课"
        ]
        if not candidates:
            return None
        session = min(candidates, key=lambda s: (s.get("date") or "", s.get("startTime") or ""))
        return self._decorate(session, _attendance_map())

    def _collect(
        self,
        *,
        start: str | None,
        end: str | None,
        class_id: str | None = None,
        teacher_id: str | None = None,
    ) -> list[dict[str, Any]]:
        attendance = _attendance_map()
        rows = []
        for session in db.alive("sessions"):
            if class_id and session.get("classId") != class_id:
                continue
            if teacher_id and session.get("teacherId") != teacher_id:
                continue
            if start and session.get("date", "") < start:
                continue
            if end and session.get("date", "") > end:
                continue
            rows.append(self._decorate(session, attendance))
        rows.sort(key=lambda r: (r.get("date") or "", r.get("startTime") or ""))
        return rows

    def _decorate(self, session: dict[str, Any], attendance: dict[tuple[str, str], dict[str, int]]) -> dict[str, Any]:
        cls = db.find("classes", session.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        teacher = db.find("teachers", session.get("teacherId") or "")
        counts = attendance.get((session.get("classId") or "", session.get("date") or ""))
        status = session.get("status") or "待上课"
        display = status
        if status == "待上课" and session.get("date", "") < today():
            display = "待考勤"
        return {
            **session,
            "className": cls["name"] if cls else "",
            "courseName": course["name"] if course else "",
            "teacherName": teacher["name"] if teacher else "",
            "displayStatus": display,
            "attendanceSaved": bool(counts),
            "attendance": counts or {"出勤": 0, "迟到": 0, "请假": 0, "缺勤": 0},
        }

    # ---------- 编辑 ----------

    def update_session(self, code: str, data: dict[str, Any], *, teacher_code: str | None = None) -> dict[str, Any]:
        session = db.locate("sessions", code or "", label="课次")
        if teacher_code and session.get("teacherId") != teacher_code:
            raise BizException(403, "只能调整自己班级的课次")
        fields = {k: v for k, v in data.items() if v is not None}
        if not fields:
            raise BizException(400, "没有需要更新的内容")
        if "status" in fields and fields["status"] not in SESSION_STATUSES:
            raise BizException(400, "课次状态只能是 待上课 / 已完成 / 已取消")
        for key in ("startTime", "endTime"):
            if key in fields:
                if not re.fullmatch(r"\d{1,2}:\d{2}", str(fields[key])):
                    raise BizException(400, "时间格式应为 HH:MM")
                fields[key] = _norm_time(str(fields[key]))
        if "date" in fields and not _as_date(str(fields["date"])):
            raise BizException(400, "日期格式应为 YYYY-MM-DD")
        if "topic" in fields:
            fields["topic"] = str(fields["topic"]).strip()[:128]
        fields["updatedAt"] = today()
        rec = db.update_fields("sessions", code, fields, label="课次")
        return self._decorate(rec, _attendance_map())

    def mark_completed(self, class_id: str, session_date: str) -> None:
        """考勤保存后，把对应课次标记为已完成（同一班级同一天可能有多个课次时只处理待上课的第一条）。"""
        for session in db.alive("sessions"):
            if (session.get("classId") == class_id
                    and session.get("date") == session_date
                    and session.get("status") == "待上课"):
                db.update_fields("sessions", session["id"], {"status": "已完成", "updatedAt": today()}, label="课次")
                break
