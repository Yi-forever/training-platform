"""教师开课申请：教师提出新课 -> 教务 / 超管审核 -> 通过后自动创建课程。

设计要点：
- 教师只能提交、查看、撤回**本人**的申请；审核权限仅超管 / 教务；
- 申请通过时复用 ``CourseService.create``，课程负责人默认是申请教师，
  课程编号自动取号（KCxxx），并在申请上记录 ``courseId`` 便于追溯；
- 同一教师不允许存在两条同名的「待审核」申请，避免重复提单；
- 审核为一次性动作：已通过 / 已驳回 / 已撤回的申请不可再次审核。
"""
from __future__ import annotations

from typing import Any

from app.core.config import now_iso
from app.core.exceptions import BizException
from app.db.repository import db
from app.services.base import CrudService, today
from app.services.education import CourseService

PENDING = "待审核"
APPROVED = "已通过"
REJECTED = "已驳回"
WITHDRAWN = "已撤回"
STATUSES = (PENDING, APPROVED, REJECTED, WITHDRAWN)


class CourseProposalService(CrudService):
    coll = "courseProposals"
    prefix = "KK"
    label = "开课申请"
    default_order = "createdAt"
    search_fields = ("id", "teacherId", "name", "category", "status", "reviewNote")

    # ---------- 查询 ----------

    def list(self, *, status: str | None = None, teacher_id: str | None = None, **kwargs) -> dict:
        return super().list(
            extra_filters={"status": status, "teacherId": teacher_id}, **kwargs
        )

    def _sort(self, rows: list[dict], field: str) -> list[dict]:
        if not field:
            return rows
        return sorted(rows, key=lambda r: str(r.get(field) or ""), reverse=True)

    def _match(self, row: dict, kw: str) -> bool:
        if super()._match(row, kw):
            return True
        teacher = db.find("teachers", row.get("teacherId") or "")
        return bool(teacher and kw in str(teacher.get("name") or "").lower())

    def decorate(self, row: dict) -> dict[str, Any]:
        teacher = db.find("teachers", row.get("teacherId") or "")
        course = db.find("courses", row.get("courseId") or "") if row.get("courseId") else None
        return {
            **row,
            "price": float(row.get("price") or 0),
            "teacherName": teacher.get("name") if teacher else "",
            "teacherSubject": teacher.get("subject") if teacher else "",
            "courseName": course.get("name") if course else "",
        }

    def list_for_teacher(self, teacher_code: str) -> list[dict[str, Any]]:
        rows = [p for p in db.alive("courseProposals") if p.get("teacherId") == teacher_code]
        rows.sort(key=lambda p: (p.get("createdAt") or "", p.get("id") or ""), reverse=True)
        return [self.decorate(p) for p in rows]

    # ---------- 教师提交 / 撤回 ----------

    def create_for_teacher(self, teacher_code: str, data: dict[str, Any]) -> dict[str, Any]:
        teacher = db.locate("teachers", teacher_code or "", label="教师")
        if teacher.get("status") != "在职":
            raise BizException(403, "当前教师已离职，无法提交开课申请")

        name = (data.get("name") or "").strip()
        if not name:
            raise BizException(400, "请填写课程名称")
        hours = int(data.get("hours") or 0)
        if hours <= 0:
            raise BizException(400, "课时数必须大于 0")
        price = float(data.get("price") or 0)
        if price < 0:
            raise BizException(400, "学费不能为负数")
        if not (data.get("category") or "").strip():
            raise BizException(400, "请选择课程分类")

        duplicate = next((
            p for p in db.alive("courseProposals")
            if p.get("teacherId") == teacher_code
            and p.get("status") == PENDING
            and str(p.get("name") or "").strip() == name
        ), None)
        if duplicate:
            raise BizException(409, f"已有一条同名待审核申请（{duplicate['id']}），请等待审核")

        ts = now_iso()
        record = {
            "id": db.next_code("courseProposals", "KK"),
            "teacherId": teacher_code,
            "name": name,
            "category": data.get("category"),
            "level": data.get("level") or "入门",
            "hours": hours,
            "price": round(price, 2),
            "target": (data.get("target") or "").strip() or None,
            "desc": (data.get("desc") or "").strip() or None,
            "preferredSchedule": (data.get("preferredSchedule") or "").strip() or None,
            "status": PENDING,
            "reviewNote": None,
            "reviewedBy": None,
            "reviewedAt": None,
            "courseId": None,
            "createdAt": ts,
            "updatedAt": ts,
        }
        db.insert("courseProposals", record)
        return self.decorate(record)

    def cancel(self, teacher_code: str, code: str) -> dict[str, Any]:
        rec = db.locate("courseProposals", code or "", label="开课申请")
        if rec.get("teacherId") != teacher_code:
            raise BizException(403, "只能撤回本人的开课申请")
        if rec.get("status") != PENDING:
            raise BizException(409, f"当前状态为「{rec.get('status')}」，只有待审核申请可以撤回")
        ts = now_iso()
        updated = db.update_fields(
            "courseProposals", code,
            {"status": WITHDRAWN, "updatedAt": ts},
            label="开课申请",
        )
        return self.decorate(updated)

    # ---------- 教务 / 超管审核 ----------

    def review(
        self, code: str, action: str, staff_code: str, *, note: str | None = None
    ) -> dict[str, Any]:
        if action not in ("approve", "reject"):
            raise BizException(400, "审核动作只能是 approve 或 reject")
        rec = db.locate("courseProposals", code or "", label="开课申请")
        if rec.get("status") != PENDING:
            raise BizException(
                409, f"当前状态为「{rec.get('status')}」，只有待审核申请可以审核"
            )

        ts = now_iso()
        if action == "reject":
            text = (note or "").strip() or "暂不符合开课条件，建议调整后再提交"
            updated = db.update_fields(
                "courseProposals", code,
                {
                    "status": REJECTED,
                    "reviewNote": text,
                    "reviewedBy": staff_code,
                    "reviewedAt": ts,
                    "updatedAt": ts,
                },
                label="开课申请",
            )
            return self.decorate(updated)

        # 通过：创建课程（负责人 = 申请教师），并回写申请
        course = CourseService().create({
            "name": rec.get("name"),
            "category": rec.get("category"),
            "level": rec.get("level") or "入门",
            "hours": int(rec.get("hours") or 0),
            "price": float(rec.get("price") or 0),
            "target": rec.get("target"),
            "desc": rec.get("desc"),
            "teacherId": rec.get("teacherId"),
            "status": "在售",
        })
        updated = db.update_fields(
            "courseProposals", code,
            {
                "status": APPROVED,
                "reviewNote": (note or "").strip() or "审核通过，已创建课程",
                "reviewedBy": staff_code,
                "reviewedAt": ts,
                "courseId": course["id"],
                "updatedAt": ts,
            },
            label="开课申请",
        )
        result = self.decorate(updated)
        result["createdCourse"] = course
        return result

    # ---------- 统计 ----------

    def stats(self) -> dict[str, Any]:
        rows = db.alive("courseProposals")
        month = today()[:7]
        return {
            "total": len(rows),
            "pending": sum(1 for p in rows if p.get("status") == PENDING),
            "approved": sum(1 for p in rows if p.get("status") == APPROVED),
            "rejected": sum(1 for p in rows if p.get("status") == REJECTED),
            "withdrawn": sum(1 for p in rows if p.get("status") == WITHDRAWN),
            "monthSubmitted": sum(1 for p in rows if (p.get("createdAt") or "").startswith(month)),
        }
