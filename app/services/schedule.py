"""排课规则与课次业务规则（E1）。

- 一个班级可配置多条规则（周一/三/五各一条），按规则 + 日期区间幂等生成课次；
- 规则改动只影响「今天及以后」的自动课次，已上课 / 已取消 / 人工调课的课次不动；
- 课次支持取消与调课：调课保留原课次并标记「已调课」，新课次记录原时间，可追溯；
- 三端课表按登录身份解析数据范围（教师只带自己的班、家长只看关联孩子）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.core.exceptions import BizException
from app.db.repository import db
from app.services.base import today
from app.services.scheduling import (
    WEEKDAY_LABELS,
    expand_dates,
    normalize_time,
    parse_date,
    parse_schedule_text,
    session_status,
    weekday_label,
)

RULE_PREFIX = "PB"
SESSION_PREFIX = "SK"
SESSION_STATUSES = ("待上课", "已上课", "已取消", "已调课")
# 兼容旧的「已完成」叫法（远端课表页面使用）
SESSION_STATUS_ALIASES = {"已完成": "已上课"}
ATTENDANCE_STATUSES = ("出勤", "迟到", "请假", "缺勤")
_MAX_RANGE_DAYS = 400
_DEFAULT_HORIZON_DAYS = 56


def _today() -> date:
    return date.today()


def _class(class_id: str) -> dict[str, Any]:
    return db.locate("classes", class_id or "", label="班级")


def _rule(rule_id: str) -> dict[str, Any]:
    return db.locate("classSchedules", rule_id or "", label="排课规则")


def _session(session_id: str) -> dict[str, Any]:
    return db.locate("classSessions", session_id or "", label="课次")


def _check_times(start: str, end: str) -> tuple[str, str]:
    try:
        start_time = normalize_time(start)
        end_time = normalize_time(end)
    except ValueError as exc:
        raise BizException(400, str(exc))
    if end_time <= start_time:
        raise BizException(400, "结束时间必须晚于开始时间")
    return start_time, end_time


def _parse_optional_date(value: str | None, *, label: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return parse_date(str(value), label=label)
    except ValueError as exc:
        raise BizException(400, str(exc))


def _class_window(cls: dict[str, Any], today_date: date) -> tuple[date, date]:
    """班级的课次日期范围：开班日 ~ 结课日（缺省时向前后各留 8 周）。"""
    start = _parse_optional_date(cls.get("startDate"), label="开班日期") or today_date
    end = _parse_optional_date(cls.get("endDate"), label="结课日期")
    if end is None:
        end = start + timedelta(days=_DEFAULT_HORIZON_DAYS)
    return start, end


def _range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """查询区间：缺省为本周一 ~ 4 周后；最长 120 天。"""
    if not date_from and not date_to:
        start = _today() - timedelta(days=_today().isoweekday() - 1)
        return start, start + timedelta(days=27)
    start = _parse_optional_date(date_from, label="开始日期") or _today()
    end = _parse_optional_date(date_to, label="结束日期") or (start + timedelta(days=27))
    if end < start:
        raise BizException(400, "结束日期不能早于开始日期")
    if (end - start).days > _MAX_RANGE_DAYS:
        raise BizException(400, f"课表查询区间不能超过 {_MAX_RANGE_DAYS} 天")
    return start, end


def decorate_rule(rule: dict[str, Any]) -> dict[str, Any]:
    cls = db.find("classes", rule.get("classId") or "")
    return {
        **rule,
        "weekdayLabel": weekday_label(int(rule.get("weekday") or 0)),
        "timeRange": f"{rule.get('startTime')}-{rule.get('endTime')}",
        "className": cls["name"] if cls else "",
    }


def decorate_session(
    session: dict[str, Any],
    *,
    homework_map: dict[str, int] | None = None,
    attendance_map: dict[tuple[str, str], dict[str, int]] | None = None,
) -> dict[str, Any]:
    cls = db.find("classes", session.get("classId") or "")
    course = db.find("courses", (cls or {}).get("courseId") or "")
    teacher = db.find("teachers", session.get("teacherId") or "")
    session_date = session.get("sessionDate")
    day = parse_date(session_date) if session_date else None
    status = session.get("status") or "待上课"
    counts = (attendance_map or _attendance_map()).get(
        (session.get("classId") or "", session_date or "")
    ) or {s: 0 for s in ATTENDANCE_STATUSES}
    display = "待考勤" if status == "待上课" and day and day < _today() else status
    return {
        **session,
        "date": session_date,          # 兼容旧课表页面的字段名
        "className": cls["name"] if cls else "",
        "courseName": course["name"] if course else "",
        "teacherName": teacher["name"] if teacher else "",
        "weekday": day.isoweekday() if day else None,
        "weekdayLabel": weekday_label(day.isoweekday() if day else 0),
        "timeRange": f"{session.get('startTime')}-{session.get('endTime')}",
        "displayStatus": display,
        "attendanceSaved": bool(any(counts.values())),
        "attendance": counts,
        "homeworkCount": (homework_map or {}).get(session.get("id") or "", 0),
    }


def _attendance_map() -> dict[tuple[str, str], dict[str, int]]:
    result: dict[tuple[str, str], dict[str, int]] = {}
    for row in db.alive("attendance"):
        key = (row.get("classId") or "", row.get("date") or "")
        bucket = result.setdefault(key, {s: 0 for s in ATTENDANCE_STATUSES})
        if row.get("status") in bucket:
            bucket[row["status"]] += 1
    return result


def _homework_map() -> dict[str, int]:
    counts: dict[str, int] = {}
    for assignment in db.alive("assignments"):
        sid = assignment.get("sessionId")
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


class ScheduleService:
    # ---------- 规则 ----------

    def list_rules(self, class_id: str) -> list[dict[str, Any]]:
        _class(class_id)
        rows = [
            r for r in db.alive("classSchedules")
            if r.get("classId") == class_id
        ]
        rows.sort(key=lambda r: (int(r.get("weekday") or 0), r.get("startTime") or ""))
        return [decorate_rule(r) for r in rows]

    def create_rule(self, class_id: str, data: dict[str, Any]) -> dict[str, Any]:
        cls = _class(class_id)
        weekday = int(data.get("weekday") or 0)
        if not 1 <= weekday <= 7:
            raise BizException(400, "上课星期必须是周一至周日")
        start_time, end_time = _check_times(
            data.get("startTime") or "", data.get("endTime") or ""
        )
        effective_from = _parse_optional_date(data.get("effectiveFrom"), label="生效日期")
        effective_to = _parse_optional_date(data.get("effectiveTo"), label="失效日期")
        if effective_from is None:
            effective_from = _parse_optional_date(cls.get("startDate"), label="开班日期") or _today()
        if effective_to is None:
            effective_to = _parse_optional_date(cls.get("endDate"), label="结课日期")
        if effective_to and effective_to < effective_from:
            raise BizException(400, "失效日期不能早于生效日期")
        classroom = (data.get("classroom") or "").strip() or (cls.get("classroom") or "")

        duplicate = next(
            (
                r for r in db.alive("classSchedules")
                if r.get("classId") == class_id
                and int(r.get("weekday") or 0) == weekday
                and r.get("startTime") == start_time
                and r.get("endTime") == end_time
                and (r.get("effectiveFrom") or "") == effective_from.isoformat()
                and (r.get("effectiveTo") or "") == (effective_to.isoformat() if effective_to else "")
            ),
            None,
        )
        if duplicate:
            raise BizException(409, "相同的排课规则已存在")

        ts = today()
        record = {
            "id": db.next_code("classSchedules", RULE_PREFIX),
            "classId": class_id,
            "weekday": weekday,
            "startTime": start_time,
            "endTime": end_time,
            "effectiveFrom": effective_from.isoformat(),
            "effectiveTo": effective_to.isoformat() if effective_to else None,
            "classroom": classroom,
            "createdAt": ts,
            "updatedAt": ts,
        }
        db.insert("classSchedules", record)
        self.regenerate_future(class_id)
        return decorate_rule(record)

    def update_rule(self, rule_id: str, data: dict[str, Any]) -> dict[str, Any]:
        rule = _rule(rule_id)
        fields = {k: v for k, v in data.items() if v is not None}
        if "weekday" in fields:
            weekday = int(fields["weekday"])
            if not 1 <= weekday <= 7:
                raise BizException(400, "上课星期必须是周一至周日")
            fields["weekday"] = weekday
        if "startTime" in fields or "endTime" in fields:
            start, end = _check_times(
                fields.get("startTime", rule.get("startTime")),
                fields.get("endTime", rule.get("endTime")),
            )
            fields["startTime"], fields["endTime"] = start, end
        for key in ("effectiveFrom", "effectiveTo"):
            if key in fields:
                value = _parse_optional_date(fields[key], label="生效 / 失效日期")
                fields[key] = value.isoformat() if value else None
        start = _parse_optional_date(fields.get("effectiveFrom", rule.get("effectiveFrom")), label="生效日期")
        end = _parse_optional_date(fields.get("effectiveTo", rule.get("effectiveTo")), label="失效日期")
        if start and end and end < start:
            raise BizException(400, "失效日期不能早于生效日期")
        # 班级在该规则下可能已有课次，不允许改挂到别的班级
        fields.pop("classId", None)
        fields["updatedAt"] = today()
        rec = db.update_fields("classSchedules", rule_id, fields, label="排课规则")
        self.regenerate_future(rule["classId"])
        return decorate_rule(rec)

    def delete_rule(self, rule_id: str) -> None:
        rule = _rule(rule_id)
        db.soft_delete("classSchedules", rule_id, label="排课规则")
        self.regenerate_future(rule["classId"])

    # ---------- 课次生成 ----------

    def regenerate_future(self, class_id: str) -> dict[str, Any]:
        """按当前规则重建「今天及以后」的自动课次（幂等，保留人工课次）。"""
        cls = _class(class_id)
        _, window_end = _class_window(cls, _today())
        if window_end < _today():
            # 学期已结束：规则变更不再产生新课时，也不影响历史课次
            return {
                "classId": class_id, "from": _today().isoformat(),
                "to": window_end.isoformat(), "created": 0, "removed": 0,
                "total": len([s for s in db.alive("classSessions") if s.get("classId") == class_id]),
            }
        return self.generate(class_id, start=_today(), end=None, remove_unmatched=True)

    def generate(
        self,
        class_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        remove_unmatched: bool = False,
    ) -> dict[str, Any]:
        cls = _class(class_id)
        window_start, window_end = _class_window(cls, _today())
        start = start or window_start
        end = end or window_end
        if end < start:
            raise BizException(400, "生成区间的结束日期不能早于开始日期")

        rules = [r for r in db.alive("classSchedules") if r.get("classId") == class_id]
        desired: dict[tuple[str, str], dict[str, Any]] = {}
        for rule in rules:
            rule_from = _parse_optional_date(rule.get("effectiveFrom"), label="生效日期") or start
            rule_to = _parse_optional_date(rule.get("effectiveTo"), label="失效日期") or end
            lo, hi = max(start, rule_from), min(end, rule_to)
            for day in expand_dates(int(rule.get("weekday") or 0), lo, hi):
                key = (day.isoformat(), rule.get("startTime") or "")
                desired.setdefault(key, {**rule, "sessionDate": day})

        existing = [s for s in db.alive("classSessions") if s.get("classId") == class_id]
        alive_keys = {(s.get("sessionDate"), s.get("startTime")) for s in existing}

        removed = 0
        if remove_unmatched:
            protected_ids = {
                a.get("sessionId") for a in db.alive("assignments") if a.get("sessionId")
            }
            for session in existing:
                if session.get("source") != "auto" or session.get("status") != "待上课":
                    continue
                if (session.get("sessionDate"), session.get("startTime")) in desired:
                    continue
                if session["id"] in protected_ids:
                    continue
                if (session.get("sessionDate") or "") < _today().isoformat():
                    continue
                db.hard_delete("classSessions", session["id"], label="课次")
                alive_keys.discard((session.get("sessionDate"), session.get("startTime")))
                removed += 1

        created = 0
        for key, rule in sorted(desired.items()):
            if key in alive_keys:
                continue
            day = rule["sessionDate"]
            ts = today()
            record = {
                "id": db.next_code("classSessions", SESSION_PREFIX),
                "classId": class_id,
                "teacherId": cls.get("teacherId") or "",
                "sessionDate": day.isoformat(),
                "startTime": rule.get("startTime"),
                "endTime": rule.get("endTime"),
                "classroom": rule.get("classroom") or cls.get("classroom") or "",
                "topic": None,
                "status": session_status(day, _today()),
                "source": "auto",
                "rescheduledFrom": None,
                "rescheduledTo": None,
                "originalDate": None,
                "originalStartTime": None,
                "originalEndTime": None,
                "createdAt": ts,
                "updatedAt": ts,
            }
            db.insert("classSessions", record)
            alive_keys.add(key)
            created += 1

        return {
            "classId": class_id,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "created": created,
            "removed": removed,
            "total": len([
                s for s in db.alive("classSessions") if s.get("classId") == class_id
            ]),
        }

    def reassign_teacher(self, class_id: str, teacher_code: str) -> int:
        """班级更换教师后，未上课的课次同步改由新教师授课。"""
        changed = 0
        for session in db.alive("classSessions"):
            if session.get("classId") != class_id:
                continue
            if session.get("status") != "待上课":
                continue
            if (session.get("sessionDate") or "") < _today().isoformat():
                continue
            if session.get("teacherId") == teacher_code:
                continue
            db.update_fields(
                "classSessions", session["id"],
                {"teacherId": teacher_code, "updatedAt": today()},
                label="课次",
            )
            changed += 1
        return changed

    # ---------- 课次查询 / 变更 ----------

    def sessions(
        self, class_id: str, *, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict[str, Any]]:
        _class(class_id)
        start, end = _range(date_from, date_to)
        rows = [
            s for s in db.alive("classSessions")
            if s.get("classId") == class_id
            and start.isoformat() <= (s.get("sessionDate") or "") <= end.isoformat()
        ]
        rows.sort(key=lambda s: (s.get("sessionDate") or "", s.get("startTime") or ""))
        homework = _homework_map()
        attendance = _attendance_map()
        return [
            decorate_session(s, homework_map=homework, attendance_map=attendance)
            for s in rows
        ]

    def teacher_sessions(
        self, teacher_code: str, class_id: str | None = None,
        *, date_from: str | None = None, date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        if class_id:
            cls = _class(class_id)
            if cls.get("teacherId") != teacher_code:
                raise BizException(403, "只能查看自己所带班级的课次")
            return self.sessions(class_id, date_from=date_from, date_to=date_to)
        return self.list_all(
            date_from=date_from, date_to=date_to, teacher_id=teacher_code,
        )

    def list_all(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        class_id: str | None = None,
        teacher_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """员工周课表：跨班级查询课次（可按班级 / 教师过滤）。"""
        start, end = _range(date_from, date_to)
        rows = [
            s for s in db.alive("classSessions")
            if start.isoformat() <= (s.get("sessionDate") or "") <= end.isoformat()
            and (not class_id or s.get("classId") == class_id)
            and (not teacher_id or s.get("teacherId") == teacher_id)
        ]
        rows.sort(key=lambda s: (s.get("sessionDate") or "", s.get("startTime") or ""))
        homework = _homework_map()
        attendance = _attendance_map()
        return [
            decorate_session(s, homework_map=homework, attendance_map=attendance)
            for s in rows
        ]

    def update_session(
        self, session_id: str, data: dict[str, Any], *, teacher_code: str | None = None
    ) -> dict[str, Any]:
        """维护课次的授课主题 / 状态 / 教室（调课仍走 reschedule 保留追溯）。"""
        session = _session(session_id)
        if teacher_code and session.get("teacherId") != teacher_code:
            raise BizException(403, "只能调整自己班级的课次")
        fields: dict[str, Any] = {}
        if "topic" in data:
            fields["topic"] = (data.get("topic") or "").strip() or None
        if "classroom" in data:
            fields["classroom"] = (data.get("classroom") or "").strip() or None
        if "status" in data:
            status = SESSION_STATUS_ALIASES.get(data.get("status"), data.get("status"))
            if status not in SESSION_STATUSES:
                raise BizException(400, "课次状态只能是 待上课 / 已上课 / 已取消 / 已调课")
            if session.get("status") == "已调课" and status != "已调课":
                raise BizException(409, "已调课的课次请操作调课后的新课次")
            fields["status"] = status
        if not fields:
            raise BizException(400, "没有需要更新的内容")
        fields["updatedAt"] = today()
        rec = db.update_fields("classSessions", session_id, fields, label="课次")
        return decorate_session(rec)


    def mark_completed(self, class_id: str, session_date: str) -> None:
        """考勤保存后，把对应课次标记为已上课（同班同日多个课次时只处理第一条待上课）。"""
        for session in db.alive("classSessions"):
            if (session.get("classId") == class_id
                    and session.get("sessionDate") == session_date
                    and session.get("status") == "待上课"):
                db.update_fields(
                    "classSessions", session["id"],
                    {"status": "已上课", "updatedAt": today()},
                    label="课次",
                )
                break


    def next_session(self, class_ids: list[str]) -> dict[str, Any] | None:
        ids = {code for code in class_ids if code}
        if not ids:
            return None
        today_str = _today().isoformat()
        candidates = [
            s for s in db.alive("classSessions")
            if s.get("classId") in ids
            and (s.get("sessionDate") or "") >= today_str
            and s.get("status") == "待上课"
        ]
        if not candidates:
            return None
        session = min(candidates, key=lambda s: (s.get("sessionDate") or "", s.get("startTime") or ""))
        return decorate_session(session, homework_map=_homework_map(), attendance_map=_attendance_map())

    def cancel(self, session_id: str) -> dict[str, Any]:
        session = _session(session_id)
        if session.get("status") == "已取消":
            raise BizException(409, "该课次已取消")
        if session.get("status") == "已上课":
            raise BizException(409, "已上课的课次不能取消")
        if session.get("status") == "已调课":
            raise BizException(409, "该课次已调课，请操作调课后的课次")
        rec = db.update_fields(
            "classSessions", session_id,
            {"status": "已取消", "updatedAt": today()},
            label="课次",
        )
        return decorate_session(rec)

    def reschedule(self, session_id: str, data: dict[str, Any]) -> dict[str, Any]:
        session = _session(session_id)
        if session.get("status") != "待上课":
            raise BizException(409, "只有「待上课」的课次可以调课")
        new_date = _parse_optional_date(data.get("sessionDate"), label="上课日期")
        if new_date is None:
            raise BizException(400, "请选择调课后的日期")
        if new_date < _today():
            raise BizException(400, "调课日期不能早于今天")
        start_time, end_time = _check_times(
            data.get("startTime") or session.get("startTime"),
            data.get("endTime") or session.get("endTime"),
        )
        classroom = (data.get("classroom") or session.get("classroom") or "").strip()
        if new_date.isoformat() == session.get("sessionDate") and start_time == session.get("startTime"):
            raise BizException(409, "调课后的时间与原课次相同")

        conflict = next(
            (
                s for s in db.alive("classSessions")
                if s.get("classId") == session.get("classId")
                and s.get("id") != session_id
                and s.get("sessionDate") == new_date.isoformat()
                and s.get("startTime") == start_time
            ),
            None,
        )
        if conflict:
            raise BizException(409, "该时间已有其他课次，请另选时间")

        ts = today()
        new_record = {
            "id": db.next_code("classSessions", SESSION_PREFIX),
            "classId": session.get("classId"),
            "teacherId": session.get("teacherId"),
            "sessionDate": new_date.isoformat(),
            "startTime": start_time,
            "endTime": end_time,
            "classroom": classroom,
            "topic": session.get("topic"),
            "status": "待上课",
            "source": "manual",
            "rescheduledFrom": session_id,
            "rescheduledTo": None,
            "originalDate": session.get("sessionDate"),
            "originalStartTime": session.get("startTime"),
            "originalEndTime": session.get("endTime"),
            "createdAt": ts,
            "updatedAt": ts,
        }
        created = db.insert("classSessions", new_record)
        db.update_fields(
            "classSessions", session_id,
            {"status": "已调课", "rescheduledTo": created["id"], "updatedAt": ts},
            label="课次",
        )
        return {
            "original": decorate_session(_session(session_id)),
            "session": decorate_session(created),
        }

    # ---------- 存量迁移 ----------

    def rebuild_rules_from_text(self, cls: dict[str, Any]) -> int:
        """按班级「上课时间」文本重建全部规则（文本无法解析时保持原规则）。"""
        specs = parse_schedule_text(cls.get("schedule"))
        if not specs:
            return 0
        for rule in db.alive("classSchedules"):
            if rule.get("classId") == cls["id"]:
                db.soft_delete("classSchedules", rule["id"], label="排课规则")
        effective_from = cls.get("startDate") or today()
        effective_to = cls.get("endDate")
        for spec in specs:
            db.insert("classSchedules", {
                "id": db.next_code("classSchedules", RULE_PREFIX),
                "classId": cls["id"],
                "weekday": spec["weekday"],
                "startTime": spec["startTime"],
                "endTime": spec["endTime"],
                "effectiveFrom": effective_from,
                "effectiveTo": effective_to,
                "classroom": cls.get("classroom") or "",
                "createdAt": today(),
                "updatedAt": today(),
            })
        return len(specs)

    def bootstrap_class(self, cls: dict[str, Any], *, full: bool = True) -> dict[str, int]:
        """为单个班级解析旧文本排课并生成课次（已有规则时仅补生成，幂等）。"""
        class_id = cls["id"]
        created = 0
        if not any(r.get("classId") == class_id for r in db.alive("classSchedules")):
            specs = parse_schedule_text(cls.get("schedule"))
            if not specs:
                return {"classes": 0, "sessions": 0}
            effective_from = cls.get("startDate") or today()
            effective_to = cls.get("endDate")
            for spec in specs:
                db.insert("classSchedules", {
                    "id": db.next_code("classSchedules", RULE_PREFIX),
                    "classId": class_id,
                    "weekday": spec["weekday"],
                    "startTime": spec["startTime"],
                    "endTime": spec["endTime"],
                    "effectiveFrom": effective_from,
                    "effectiveTo": effective_to,
                    "classroom": cls.get("classroom") or "",
                    "createdAt": today(),
                    "updatedAt": today(),
                })
            created = 1
        window_start, window_end = _class_window(cls, _today())
        if not full and window_end < _today():
            return {"classes": created, "sessions": 0}
        stats = self.generate(
            class_id,
            start=window_start if full else _today(),
            end=window_end,
            remove_unmatched=False,
        )
        return {"classes": created, "sessions": int(stats["created"])}

    def sync_for_class(self, class_id: str) -> dict[str, Any]:
        """班级排课信息变更后同步未来课次（已有规则时重建，无规则时从文本补建）。"""
        cls = _class(class_id)
        if any(r.get("classId") == class_id for r in db.alive("classSchedules")):
            return self.regenerate_future(class_id)
        return self.bootstrap_class(cls, full=False)

    def ensure_all(self) -> int:
        """启动 / 重置后补齐课次：无规则的班级从文本补建，有规则的班级续排未来课次。"""
        created = 0
        for cls in db.alive("classes"):
            if cls.get("status") == "已结课":
                continue
            if any(r.get("classId") == cls["id"] for r in db.alive("classSchedules")):
                created += int(self.regenerate_future(cls["id"])["created"])
            else:
                created += int(self.bootstrap_class(cls, full=False)["sessions"])
        return created

    def backfill_legacy(self) -> dict[str, int]:
        """为没有排课规则的班级解析旧文本排课并生成课次（幂等）。"""
        classes = 0
        sessions = 0
        for cls in db.alive("classes"):
            if any(r.get("classId") == cls["id"] for r in db.alive("classSchedules")):
                continue
            stats = self.bootstrap_class(cls, full=True)
            classes += stats["classes"]
            sessions += stats["sessions"]
        return {"classes": classes, "sessions": sessions}


class TimetableService:
    """三端课表：按身份解析数据范围，默认返回本周起 4 周。"""

    def _payload(self, sessions: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
        rows = [
            s for s in sessions
            if start.isoformat() <= (s.get("sessionDate") or "") <= end.isoformat()
        ]
        rows.sort(key=lambda s: (s.get("sessionDate") or "", s.get("startTime") or ""))
        homework = _homework_map()
        attendance = _attendance_map()
        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "sessions": [
                decorate_session(s, homework_map=homework, attendance_map=attendance)
                for s in rows
            ],
        }

    def for_teacher(self, teacher_code: str, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        start, end = _range(date_from, date_to)
        class_ids = {c["id"] for c in db.classes_of_teacher(teacher_code)}
        sessions = [
            s for s in db.alive("classSessions")
            if s.get("classId") in class_ids
        ]
        return self._payload(sessions, start, end)

    def for_student(self, student_code: str, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        from app.services.enrollment import enrolled_class_ids

        start, end = _range(date_from, date_to)
        student = db.locate("students", student_code or "", label="学员")
        class_ids = set(enrolled_class_ids(student_code))
        sessions = [
            s for s in db.alive("classSessions")
            if s.get("classId") in class_ids
        ]
        payload = self._payload(sessions, start, end)
        payload["student"] = {
            "studentId": student["id"], "name": student.get("name"),
            "classId": student.get("classId"),
            "className": (db.find("classes", student.get("classId") or "") or {}).get("name", ""),
            "classNames": [
                c["name"] for c in (db.find("classes", cid) for cid in class_ids) if c
            ],
        }
        return payload

    def for_parent(
        self, parent_code: str, student_id: str,
        date_from: str | None = None, date_to: str | None = None,
    ) -> dict[str, Any]:
        child_ids = {s["id"] for s in db.list_children_of(parent_code)}
        if student_id not in child_ids:
            raise BizException(403, "只能查看与本人关联学员的课表")
        return self.for_student(student_id, date_from, date_to)


__all__ = [
    "ScheduleService",
    "TimetableService",
    "decorate_session",
    "decorate_rule",
    "SESSION_STATUSES",
    "WEEKDAY_LABELS",
]
