"""作业与考勤业务规则（教师 / 学员 / 家长三类门户共用）。

设计要点：
- 教师只能操作自己所带班级的作业与考勤（服务端校验，越权返回 403）；
- 学员只能看到并提交本班作业，一份作业保留一条提交记录，重新提交会清空旧批改；
- 家长只能查看自己关联学员的作业、批改结果与考勤；
- 考勤按「班级 + 日期 + 学员」唯一，重复保存为更新而非新增。
"""
from datetime import date
from typing import Any

import re

from app.core.exceptions import BizException
from app.db.repository import db
from app.services.base import today
from app.services.enrollment import enrolled_class_ids, enrolled_student_ids
from app.services.schedule import ScheduleService

ASSIGNMENT_STATUSES = ("进行中", "已结束")
ATTENDANCE_STATUSES = ("出勤", "迟到", "请假", "缺勤")
SUBMISSION_STATUSES = ("已提交", "已批改", "已退回")


def _parse_due_date(value: str | None, *, floor: str | None = None) -> str:
    """校验截止日期（YYYY-MM-DD），早于今天或早于发布日期时拒绝。"""
    if value in (None, ""):
        return today()
    try:
        due = date.fromisoformat(str(value).strip())
    except ValueError:
        raise BizException(400, "截止日期格式应为 YYYY-MM-DD")
    if due < date.today():
        raise BizException(422, "截止日期不能早于今天")
    if floor:
        try:
            if due < date.fromisoformat(floor[:10]):
                raise BizException(422, "截止日期不能早于发布日期")
        except ValueError:
            pass
    return due.isoformat()


def _check_session(teacher_code: str, class_id: str, session_id: str | None) -> str | None:
    """作业关联课次时，校验课次属于该班级且由本教师授课。"""
    if not session_id:
        return None
    session = db.locate("classSessions", session_id, label="课次")
    if session.get("classId") != class_id:
        raise BizException(400, "关联课次不属于该班级")
    if session.get("teacherId") != teacher_code:
        raise BizException(403, "只能关联自己授课的课次")
    if session.get("status") == "已取消":
        raise BizException(409, "已取消的课次不能关联作业")
    return session_id


def _class_students(class_id: str) -> list[dict[str, Any]]:
    """班级在册学员（含兼报该班的学员，口径与选课记录一致）。"""
    ids = enrolled_student_ids(class_id)
    return [s for s in db.alive("students") if s["id"] in ids]


def _student(student_code: str) -> dict[str, Any]:
    return db.locate("students", student_code or "", label="学员")


def _teacher_class(teacher_code: str, class_id: str) -> dict[str, Any]:
    cls = db.locate("classes", class_id or "", label="班级")
    if cls.get("teacherId") != teacher_code:
        raise BizException(403, f"班级「{cls.get('name')}」不是您所带的班级")
    return cls


def _assignment_of_teacher(teacher_code: str, assignment_id: str) -> dict[str, Any]:
    assignment = db.locate("assignments", assignment_id or "", label="作业")
    if assignment.get("teacherId") != teacher_code:
        raise BizException(403, "只能操作自己布置的作业")
    return assignment


def _sort_assignments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """进行中优先，其次按截止日期由近到远。"""
    return sorted(
        rows,
        key=lambda a: (0 if a.get("status") == "进行中" else 1, a.get("dueDate") or "9999-12-31", a.get("id")),
    )


class AssignmentService:
    # ---------- 教师 ----------

    def list_for_teacher(self, teacher_code: str, class_id: str | None = None) -> list[dict[str, Any]]:
        rows = [
            a for a in db.alive("assignments")
            if a.get("teacherId") == teacher_code and (not class_id or a.get("classId") == class_id)
        ]
        return [self._decorate_teacher(a) for a in _sort_assignments(rows)]

    def create(self, teacher_code: str, data: dict[str, Any]) -> dict[str, Any]:
        cls = _teacher_class(teacher_code, data.get("classId") or "")
        title = (data.get("title") or "").strip()
        if not title:
            raise BizException(400, "请填写作业标题")
        ts = today()
        record = {
            "id": db.next_code("assignments", "HW"),
            "classId": cls["id"],
            "teacherId": teacher_code,
            "sessionId": _check_session(teacher_code, cls["id"], data.get("sessionId")),
            "title": title,
            "content": (data.get("content") or "").strip(),
            "dueDate": _parse_due_date(data.get("dueDate")),
            "allowLate": bool(data.get("allowLate")),
            "status": "进行中",
            "createdAt": ts,
            "updatedAt": ts,
        }
        db.insert("assignments", record)
        return self._decorate_teacher(record)

    def update(self, teacher_code: str, assignment_id: str, data: dict[str, Any]) -> dict[str, Any]:
        current = _assignment_of_teacher(teacher_code, assignment_id)
        fields = {k: v for k, v in data.items() if v is not None}
        if "status" in fields and fields["status"] not in ASSIGNMENT_STATUSES:
            raise BizException(400, "作业状态只能是「进行中」或「已结束」")
        if "title" in fields and not str(fields["title"]).strip():
            raise BizException(400, "作业标题不能为空")
        if "dueDate" in fields:
            fields["dueDate"] = _parse_due_date(fields["dueDate"], floor=current.get("createdAt"))
        if "sessionId" in data:
            # 显式传空表示解除课次关联
            fields["sessionId"] = _check_session(
                teacher_code, current["classId"], data.get("sessionId")
            )
        fields["updatedAt"] = today()
        rec = db.update_fields("assignments", assignment_id, fields, label="作业")
        return self._decorate_teacher(rec)

    def delete(self, teacher_code: str, assignment_id: str) -> None:
        _assignment_of_teacher(teacher_code, assignment_id)
        submitted = [s for s in db.alive("submissions") if s.get("assignmentId") == assignment_id]
        if submitted:
            raise BizException(409, "该作业已有学员提交，不能删除；如需停止提交请将状态改为「已结束」")
        db.soft_delete("assignments", assignment_id, label="作业")

    def submissions(self, teacher_code: str, assignment_id: str) -> dict[str, Any]:
        assignment = _assignment_of_teacher(teacher_code, assignment_id)
        students = _class_students(assignment["classId"])
        subs = [s for s in db.alive("submissions") if s.get("assignmentId") == assignment_id]
        by_student = {s["studentId"]: s for s in subs}
        rows = []
        for stu in sorted(students, key=lambda s: s.get("id") or ""):
            sub = by_student.get(stu["id"])
            rows.append({
                "studentId": stu["id"],
                "studentName": stu.get("name"),
                "submissionId": sub["id"] if sub else None,
                "status": sub["status"] if sub else "未提交",
                "content": sub.get("content") if sub else None,
                "submittedAt": sub.get("submittedAt") if sub else None,
                "score": sub.get("score") if sub else None,
                "comment": sub.get("comment") if sub else None,
                "gradedAt": sub.get("gradedAt") if sub else None,
                "returnReason": sub.get("returnReason") if sub else None,
            })
        return {
            "assignment": self._decorate_teacher(assignment),
            "rows": rows,
            "submittedCount": len(subs),
            "gradedCount": sum(1 for s in subs if s.get("status") == "已批改"),
            "totalStudents": len(students),
        }

    def grade(self, teacher_code: str, submission_id: str, score: int, comment: str | None) -> dict[str, Any]:
        sub = db.locate("submissions", submission_id or "", label="作业提交")
        _assignment_of_teacher(teacher_code, sub.get("assignmentId") or "")
        if sub.get("status") == "已退回":
            raise BizException(409, "该提交已退回，等待学员重新提交后再批改")
        if not isinstance(score, int) or not 0 <= score <= 100:
            raise BizException(400, "分数须为 0-100 的整数")
        rec = db.update_fields(
            "submissions", submission_id,
            {
                "score": score,
                "comment": (comment or "").strip() or None,
                "status": "已批改",
                "gradedAt": today(),
                "gradedBy": teacher_code,
                "updatedAt": today(),
            },
            label="作业提交",
        )
        return rec

    # ---------- 学员 ----------

    def list_for_student(self, student_code: str) -> list[dict[str, Any]]:
        class_ids = set(enrolled_class_ids(student_code))
        rows = [a for a in db.alive("assignments") if a.get("classId") in class_ids]
        result = []
        for a in _sort_assignments(rows):
            sub = db.find_one("submissions", assignmentId=a["id"], studentId=student_code)
            result.append({
                "id": a["id"],
                "title": a.get("title"),
                "content": a.get("content"),
                "dueDate": a.get("dueDate"),
                "status": a.get("status"),
                "allowLate": bool(a.get("allowLate")),
                "className": (db.find("classes", a.get("classId") or "") or {}).get("name", ""),
                "teacherName": (db.find("teachers", a.get("teacherId") or "") or {}).get("name", ""),
                "submissionId": sub["id"] if sub else None,
                "submitStatus": sub["status"] if sub else "未提交",
                "submittedAt": sub.get("submittedAt") if sub else None,
                "score": sub.get("score") if sub else None,
                "comment": sub.get("comment") if sub else None,
                "gradedAt": sub.get("gradedAt") if sub else None,
                "returnReason": sub.get("returnReason") if sub else None,
                "submittedContent": sub.get("content") if sub else None,
            })
        return result

    def submit(self, student_code: str, assignment_id: str, content: str) -> dict[str, Any]:
        assignment = db.locate("assignments", assignment_id or "", label="作业")
        if assignment.get("classId") not in set(enrolled_class_ids(student_code)):
            raise BizException(403, "该作业不属于你所在的班级")
        if assignment.get("status") != "进行中":
            raise BizException(409, "该作业已结束，无法提交")
        due_date = assignment.get("dueDate")
        if due_date and today() > due_date and not assignment.get("allowLate"):
            raise BizException(409, "作业已截止，不允许迟交")
        text = (content or "").strip()
        if not text:
            raise BizException(400, "请填写作业内容")

        ts = today()
        existing = db.find_one("submissions", assignmentId=assignment_id, studentId=student_code)
        if existing:
            if existing.get("status") == "已批改":
                raise BizException(409, "作业已批改，如需修改请让教师退回后重新提交")
            # 重新提交（含被退回后重交）：清空旧批改与退回理由，等待教师重新批阅
            rec = db.update_fields(
                "submissions", existing["id"],
                {
                    "content": text,
                    "submittedAt": ts,
                    "status": "已提交",
                    "score": None,
                    "comment": None,
                    "gradedAt": None,
                    "gradedBy": None,
                    "returnReason": None,
                    "updatedAt": ts,
                },
                label="作业提交",
            )
        else:
            rec = {
                "id": db.next_code("submissions", "TJ"),
                "assignmentId": assignment_id,
                "studentId": student_code,
                "content": text,
                "submittedAt": ts,
                "status": "已提交",
                "score": None,
                "comment": None,
                "gradedAt": None,
                "gradedBy": None,
                "returnReason": None,
                "createdAt": ts,
                "updatedAt": ts,
            }
            db.insert("submissions", rec)
        return rec

    def return_submission(self, teacher_code: str, submission_id: str, reason: str) -> dict[str, Any]:
        """教师退回已批改的提交：成绩作废、记录退回理由，学员可重新提交。"""
        sub = db.locate("submissions", submission_id or "", label="作业提交")
        _assignment_of_teacher(teacher_code, sub.get("assignmentId") or "")
        if sub.get("status") != "已批改":
            raise BizException(409, "只有「已批改」的提交可以退回")
        text = (reason or "").strip()
        if len(text) < 2:
            raise BizException(400, "请填写退回理由（至少 2 个字）")
        rec = db.update_fields(
            "submissions", submission_id,
            {
                "status": "已退回",
                "score": None,
                "comment": None,
                "gradedAt": None,
                "gradedBy": None,
                "returnReason": text,
                "updatedAt": today(),
            },
            label="作业提交",
        )
        return rec

    # ---------- 家长 ----------

    def list_for_parent(self, parent_code: str, student_id: str | None = None) -> list[dict[str, Any]]:
        children = db.list_children_of(parent_code)
        if student_id:
            children = [c for c in children if c.get("id") == student_id]
            if not children:
                raise BizException(403, "该学员不在您的关联范围内")
        result = []
        for stu in children:
            class_ids = set(enrolled_class_ids(stu["id"]))
            rows = [a for a in db.alive("assignments") if a.get("classId") in class_ids]
            for a in _sort_assignments(rows):
                sub = db.find_one("submissions", assignmentId=a["id"], studentId=stu["id"])
                result.append({
                    "studentId": stu["id"],
                    "studentName": stu.get("name"),
                    "assignmentId": a["id"],
                    "title": a.get("title"),
                    "dueDate": a.get("dueDate"),
                    "assignmentStatus": a.get("status"),
                    "allowLate": bool(a.get("allowLate")),
                    "submitStatus": sub["status"] if sub else "未提交",
                    "submittedAt": sub.get("submittedAt") if sub else None,
                    "score": sub.get("score") if sub else None,
                    "comment": sub.get("comment") if sub else None,
                    "gradedAt": sub.get("gradedAt") if sub else None,
                    "returnReason": sub.get("returnReason") if sub else None,
                })
        return result

    # ---------- 公共 ----------

    def _decorate_teacher(self, a: dict[str, Any]) -> dict[str, Any]:
        cls = db.find("classes", a.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        subs = [s for s in db.alive("submissions") if s.get("assignmentId") == a.get("id")]
        submitted = [s for s in subs if s.get("status") != "已退回"]
        students = _class_students(a.get("classId") or "")
        return {
            **a,
            "className": cls["name"] if cls else "",
            "courseName": course["name"] if course else "",
            "totalStudents": len(students),
            "submittedCount": len(submitted),
            "gradedCount": sum(1 for s in subs if s.get("status") == "已批改"),
        }


class AttendanceService:
    # ---------- 教师 ----------

    def roster(self, teacher_code: str, class_id: str, date: str) -> dict[str, Any]:
        cls = _teacher_class(teacher_code, class_id)
        if not date:
            raise BizException(400, "请选择考勤日期")
        students = sorted(_class_students(class_id), key=lambda s: s.get("id") or "")
        saved = {
            a["studentId"]: a
            for a in db.alive("attendance")
            if a.get("classId") == class_id and a.get("date") == date
        }
        rows = [{
            "studentId": s["id"],
            "studentName": s.get("name"),
            "grade": s.get("grade"),
            "status": saved[s["id"]]["status"] if s["id"] in saved else "出勤",
            "note": saved[s["id"]].get("note") if s["id"] in saved else "",
        } for s in students]
        return {
            "classId": class_id,
            "className": cls.get("name"),
            "date": date,
            "saved": bool(saved),
            "rows": rows,
            "summary": self._summary([{"status": r["status"]} for r in rows]),
        }

    def save(self, teacher_code: str, class_id: str, date: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        cls = _teacher_class(teacher_code, class_id)
        if not date:
            raise BizException(400, "请选择考勤日期")
        student_ids = {s["id"] for s in _class_students(class_id)}
        ts = today()
        for item in items:
            sid = item.get("studentId")
            if sid not in student_ids:
                raise BizException(400, f"学员「{sid}」不在班级「{cls.get('name')}」中")
            status = item.get("status") or "出勤"
            if status not in ATTENDANCE_STATUSES:
                raise BizException(400, "考勤状态只能是 出勤 / 迟到 / 请假 / 缺勤")
            note = (item.get("note") or "").strip() or None
            existing = db.find_one("attendance", classId=class_id, studentId=sid, date=date)
            if existing:
                db.update_fields(
                    "attendance", existing["id"],
                    {"status": status, "note": note, "teacherId": teacher_code, "updatedAt": ts},
                    label="考勤记录",
                )
            else:
                db.insert("attendance", {
                    "id": db.next_code("attendance", "KQ"),
                    "classId": class_id,
                    "studentId": sid,
                    "date": date,
                    "status": status,
                    "note": note,
                    "teacherId": teacher_code,
                    "createdAt": ts,
                    "updatedAt": ts,
                })
        # 考勤保存后，对应课次标记为已完成（课表与考勤联动）
        ScheduleService().mark_completed(class_id, date)
        return self.roster(teacher_code, class_id, date)

    def class_summary(self, teacher_code: str, class_id: str, month: str | None = None) -> dict[str, Any]:
        """班级考勤统计：按学员汇总出勤 / 迟到 / 请假 / 缺勤与出勤率。"""
        cls = _teacher_class(teacher_code, class_id)
        if month and not re.fullmatch(r"\d{4}-\d{2}", month):
            raise BizException(400, "月份格式应为 YYYY-MM")
        students = sorted(_class_students(class_id), key=lambda s: s.get("id") or "")
        records = [
            a for a in db.alive("attendance")
            if a.get("classId") == class_id and (not month or (a.get("date") or "").startswith(month))
        ]
        totals = {status: 0 for status in ATTENDANCE_STATUSES}
        buckets: dict[str, dict[str, int]] = {
            s["id"]: {status: 0 for status in ATTENDANCE_STATUSES} for s in students
        }
        for row in records:
            sid = row.get("studentId")
            if sid in buckets and row.get("status") in buckets[sid]:
                buckets[sid][row["status"]] += 1
                totals[row["status"]] += 1
        rows = []
        for stu in students:
            counts = buckets[stu["id"]]
            total = sum(counts.values())
            attended = counts["出勤"] + counts["迟到"]
            rows.append({
                "studentId": stu["id"],
                "studentName": stu.get("name"),
                "grade": stu.get("grade"),
                **counts,
                "total": total,
                "rate": round(attended / total * 100) if total else 0,
            })
        total_all = sum(totals.values())
        attended_all = totals["出勤"] + totals["迟到"]
        return {
            "classId": class_id,
            "className": cls.get("name"),
            "month": month or "",
            "students": rows,
            "totals": {
                **totals,
                "total": total_all,
                "rate": round(attended_all / total_all * 100) if total_all else 0,
            },
        }

    # ---------- 学员 ----------

    def list_for_student(self, student_code: str) -> list[dict[str, Any]]:
        stu = _student(student_code)
        rows = [a for a in db.alive("attendance") if a.get("studentId") == student_code]
        return self._decorate(rows)

    # ---------- 家长 ----------

    def list_for_parent(self, parent_code: str, student_id: str | None = None) -> list[dict[str, Any]]:
        children = db.list_children_of(parent_code)
        if student_id:
            children = [c for c in children if c.get("id") == student_id]
            if not children:
                raise BizException(403, "该学员不在您的关联范围内")
        ids = {c["id"] for c in children}
        names = {c["id"]: c.get("name") for c in children}
        rows = [a for a in db.alive("attendance") if a.get("studentId") in ids]
        result = self._decorate(rows)
        for r in result:
            r["studentName"] = names.get(r["studentId"], r.get("studentName"))
        return result

    # ---------- 公共 ----------

    def _decorate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for a in sorted(rows, key=lambda r: (r.get("date") or "", r.get("id") or ""), reverse=True):
            cls = db.find("classes", a.get("classId") or "")
            stu = db.find("students", a.get("studentId") or "")
            result.append({
                **a,
                "className": cls["name"] if cls else "",
                "studentName": stu["name"] if stu else "",
            })
        return result

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
        summary = {status: 0 for status in ATTENDANCE_STATUSES}
        for r in rows:
            if r.get("status") in summary:
                summary[r["status"]] += 1
        return summary


class TeachingStatsService:
    """门户统计卡片所需的作业 / 考勤摘要。"""

    def teacher(self, teacher_code: str) -> dict[str, Any]:
        assignments = [a for a in db.alive("assignments") if a.get("teacherId") == teacher_code]
        ids = {a["id"] for a in assignments}
        subs = [s for s in db.alive("submissions") if s.get("assignmentId") in ids]
        return {
            "assignmentCount": len(assignments),
            "pendingGrading": sum(1 for s in subs if s.get("status") == "已提交"),
            "submittedCount": len(subs),
        }

    def student(self, student_code: str) -> dict[str, Any]:
        stu = db.find("students", student_code or "")
        if not stu:
            return {"pendingAssignments": 0, "attendance": {s: 0 for s in ATTENDANCE_STATUSES}}
        class_ids = set(enrolled_class_ids(student_code))
        assignments = [
            a for a in db.alive("assignments")
            if a.get("classId") in class_ids and a.get("status") == "进行中"
        ]
        submitted = {
            s.get("assignmentId") for s in db.alive("submissions")
            if s.get("studentId") == student_code and s.get("status") != "已退回"
        }
        records = [a for a in db.alive("attendance") if a.get("studentId") == student_code]
        return {
            "pendingAssignments": sum(1 for a in assignments if a["id"] not in submitted),
            "attendance": AttendanceService._summary(records),
        }
