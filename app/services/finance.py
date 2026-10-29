"""缴费业务：状态机（待确认 -> 已支付 / 已作废，已退款为终态）、应收账单与统计。

金额口径（家长端与后台必须一致）：
- 应缴 = Σ 有效账单（不含已作废）；
- 已缴 = Σ 「已支付」流水；
- 欠费 = max(应缴 − 已缴, 0)；
- 账单的实收金额不落库，由 `payments.billId` 关联的流水实时汇总，避免两套金额漂移。
"""
from datetime import date, datetime, timedelta
from typing import Any

from app.core.exceptions import BizException
from app.core.config import now_iso
from app.db.repository import db
from app.services.base import CrudService, today

STATUS_PENDING = "待确认"
STATUS_PAID = "已支付"
STATUS_REFUNDED = "已退款"
STATUS_VOIDED = "已作废"

BILL_PENDING = "待缴"
BILL_VOIDED = "已作废"


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _paid_by_bill() -> dict[str, float]:
    """各账单已收金额（仅「已支付」流水计入）。"""
    paid: dict[str, float] = {}
    for p in db.alive("payments"):
        bill_id = p.get("billId")
        if bill_id and p.get("status") == STATUS_PAID:
            paid[bill_id] = round(paid.get(bill_id, 0.0) + float(p.get("amount") or 0), 2)
    return paid


class BillService(CrudService):
    """应收账单：报名时按课程价生成，供家长 / 学员端缴费详情使用。"""

    coll = "bills"
    prefix = "ZD"
    label = "账单"
    search_fields = ("id", "note")

    def list(self, *, student_id: str | None = None, **kwargs) -> dict:
        return super().list(
            extra_filters={"studentId": student_id} if student_id else None, **kwargs
        )

    def create(self, data: dict[str, Any]) -> dict:
        stu = db.locate("students", data.get("studentId") or "", label="学员")
        cls = db.locate("classes", data.get("classId") or stu.get("classId") or "", label="班级")
        course = db.locate("courses", cls.get("courseId") or "", label="课程")
        amount = course.get("price") if data.get("amount") is None else data.get("amount")
        if float(amount or 0) <= 0:
            raise BizException(400, "账单金额必须大于 0")
        due = data.get("dueDate") or today()
        payload = {
            **data,
            "classId": cls["id"],
            "courseId": course["id"],
            "amount": round(float(amount), 2),
            "period": data.get("period") or due[:7],
            "dueDate": due,
            "status": data.get("status") or BILL_PENDING,
        }
        return super().create(payload)

    def create_for_class(
        self, student: dict, class_id: str, *, note: str | None = None, due_from: str | None = None
    ) -> dict | None:
        """按「班级 → 课程价」为某班级生成一条应收账单（同学员同班级幂等）。

        选课系统支持一名学员兼报多个班级，因此幂等口径是「学员 + 班级」，
        而不是「学员是否已有账单」。``due_from`` 用于新选课：账期与到期日按选课日期
        计算，而不是学员最初报名日期。
        """
        cls = db.find("classes", class_id or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        if not cls or not course or _money(course.get("price")) <= 0:
            return None
        if any(
            b.get("studentId") == student["id"]
            and b.get("classId") == class_id
            and b.get("status") != BILL_VOIDED
            for b in db.alive("bills")
        ):
            return None
        base = due_from or student.get("enrollDate") or today()
        try:
            due = (date.fromisoformat(base) + timedelta(days=14)).isoformat()
        except ValueError:
            due = today()
        return self.create({
            "studentId": student["id"],
            "classId": cls["id"],
            "amount": course.get("price"),
            "period": base[:7],
            "dueDate": due,
            "note": note or "报名学费（按课程价生成）",
        })

    def create_for_student(self, student: dict) -> dict | None:
        """报名 / 存量补建：按学员当前主班的课程价生成应收账单（幂等）。"""
        return self.create_for_class(student, student.get("classId") or "")

    def decorate(self, row: dict) -> dict:
        amount = _money(row.get("amount"))
        paid = _paid_by_bill().get(row.get("id"), 0.0)
        voided = row.get("status") == BILL_VOIDED
        if voided:
            display = BILL_VOIDED
        elif amount > 0 and paid >= amount:
            display = "已缴"
        elif paid > 0:
            display = "部分缴"
        elif (row.get("dueDate") or "") < today():
            display = "已逾期"
        else:
            display = BILL_PENDING
        course = db.find("courses", row.get("courseId") or "")
        cls = db.find("classes", row.get("classId") or "")
        student = db.find("students", row.get("studentId") or "")
        return {
            **row,
            "amount": amount,
            "paidAmount": paid,
            "outstanding": 0.0 if voided else round(max(amount - paid, 0), 2),
            "displayStatus": display,
            "overdue": display == "已逾期",
            "courseName": course["name"] if course else "",
            "className": cls["name"] if cls else "",
            "studentName": student["name"] if student else "",
        }

    def student_payload(self, student: dict) -> dict[str, Any]:
        """某学员的缴费详情：汇总 + 账单 + 流水（家长端 / 学员端共用）。"""
        bills = [self.decorate(b) for b in db.alive("bills") if b.get("studentId") == student["id"]]
        bills.sort(key=lambda b: (b.get("dueDate") or "", b["id"]))
        payments = [p for p in db.alive("payments") if p.get("studentId") == student["id"]]
        payments.sort(key=lambda p: (p.get("date") or "", p["id"]), reverse=True)

        effective = [b for b in bills if b.get("status") != BILL_VOIDED]
        due_total = round(sum(b["amount"] for b in effective), 2)
        paid_total = round(
            sum(float(p.get("amount") or 0) for p in payments if p.get("status") == STATUS_PAID), 2
        )
        pending_total = round(
            sum(float(p.get("amount") or 0) for p in payments if p.get("status") == STATUS_PENDING), 2
        )
        cls = db.find("classes", student.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        return {
            "student": {
                "studentId": student["id"],
                "name": student.get("name"),
                "grade": student.get("grade"),
                "status": student.get("status"),
                "className": cls["name"] if cls else "",
                "courseName": course["name"] if course else "",
            },
            "summary": {
                "dueTotal": due_total,
                "paidTotal": paid_total,
                "pendingTotal": pending_total,
                "outstanding": round(max(due_total - paid_total, 0), 2),
                "billCount": len(effective),
                "paidCount": sum(1 for p in payments if p.get("status") == STATUS_PAID),
            },
            "hasBills": bool(effective),
            "bills": bills,
            "payments": [self._payment_view(p) for p in payments],
        }

    def parent_payload(self, parent_code: str, student_id: str) -> dict[str, Any]:
        """家长端缴费详情：只能查看与本人关联的学员（越权 403）。"""
        children = {s["id"] for s in db.list_children_of(parent_code)}
        if student_id not in children:
            raise BizException(403, "只能查看本人关联学员的缴费信息")
        return self.student_payload(db.locate("students", student_id, label="学员"))

    @staticmethod
    def _payment_view(p: dict) -> dict:
        return {
            "id": p.get("id"),
            "date": p.get("date"),
            "amount": _money(p.get("amount")),
            "method": p.get("method"),
            "status": p.get("status"),
            "note": p.get("note"),
            "billId": p.get("billId"),
        }

    def backfill(self) -> int:
        """启动时补齐：为无账单的老学员生成账单，并把历史学费流水挂到账单上。"""
        created = 0
        for stu in db.alive("students"):
            if self.create_for_student(stu):
                created += 1
        self._link_orphan_payments()
        return created

    def _link_orphan_payments(self) -> None:
        bills = {
            b["studentId"]: b for b in db.alive("bills") if b.get("status") != BILL_VOIDED
        }
        for p in db.alive("payments"):
            if p.get("billId") or p.get("status") in (STATUS_REFUNDED, STATUS_VOIDED):
                continue
            bill = bills.get(p.get("studentId") or "")
            if bill and any(k in str(p.get("note") or "") for k in ("学费", "定金", "分期")):
                db.update_fields("payments", p["id"], {"billId": bill["id"]})


class PaymentService(CrudService):
    coll = "payments"
    prefix = "JF"
    label = "缴费记录"
    search_fields = ("id", "note", "method")

    def _match(self, row: dict, kw: str) -> bool:
        """扩展：支持按学员姓名搜索（前端搜索框行为）。"""
        if super()._match(row, kw):
            return True
        student = db.find("students", row.get("studentId") or "")
        return bool(student and kw in str(student.get("name") or "").lower())

    def list(
        self,
        *,
        class_id: str | None = None,
        student_id: str | None = None,
        method: str | None = None,
        **kwargs,
    ) -> dict:
        return super().list(
            extra_filters={"classId": class_id, "studentId": student_id, "method": method},
            **kwargs,
        )

    def decorate(self, row: dict) -> dict:
        student = db.find("students", row.get("studentId") or "")
        cls = db.find("classes", row.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        return {
            **row,
            "studentName": student["name"] if student else "",
            "className": cls["name"] if cls else "",
            "courseName": course["name"] if course else "",
        }

    def create(self, data: dict[str, Any]) -> dict:
        student_id = data.get("studentId") or ""
        db.locate("students", student_id, label="学员")
        db.locate("classes", data.get("classId") or "", label="班级")
        data = {**data}
        if not data.get("date"):
            data["date"] = today()
        # 缴费自动挂到该学员最早一笔未缴清的账单；全缴清或非学费流水则留作历史流水
        data["billId"] = self._resolve_bill_id(data.get("billId"), student_id)
        return super().create(data)

    def _resolve_bill_id(self, bill_id: str | None, student_id: str) -> str | None:
        if bill_id:
            bill = db.locate("bills", bill_id, label="账单")
            if bill.get("studentId") != student_id:
                raise BizException(409, "所选账单与学员不匹配")
            if bill.get("status") == BILL_VOIDED:
                raise BizException(409, "该账单已作废，不能关联缴费")
            return bill_id
        paid = _paid_by_bill()
        candidates = [
            b for b in db.alive("bills")
            if b.get("studentId") == student_id
            and b.get("status") != BILL_VOIDED
            and paid.get(b["id"], 0.0) < float(b.get("amount") or 0)
        ]
        candidates.sort(key=lambda b: (b.get("dueDate") or "", b["id"]))
        return candidates[0]["id"] if candidates else None

    def confirm(self, code: str) -> dict:
        """确认收款：仅「待确认」可流转为「已支付」。"""
        rec = db.locate("payments", code, label="缴费记录")
        if rec.get("status") != STATUS_PENDING:
            raise BizException(409, f"当前状态为「{rec.get('status')}」，只有待确认的缴费才能确认收款")
        return db.update_fields(
            "payments", code, {"status": STATUS_PAID, "updatedAt": now_iso()}, label="缴费记录"
        )

    def void(self, code: str) -> dict:
        """作废：待确认 / 已支付可作废；已退款、已作废为终态。"""
        rec = db.locate("payments", code, label="缴费记录")
        if rec.get("status") in (STATUS_REFUNDED, STATUS_VOIDED):
            raise BizException(409, f"该笔缴费已{rec.get('status')}，不能再作废")
        return db.update_fields(
            "payments", code, {"status": STATUS_VOIDED, "updatedAt": now_iso()}, label="缴费记录"
        )

    def stats(self) -> dict:
        """三卡片统计：本月收入 / 待确认 / 累计收入（仅「已支付」计入收入口径）。"""
        rows = db.alive("payments")
        paid = [p for p in rows if p.get("status") == STATUS_PAID]
        pending = [p for p in rows if p.get("status") == STATUS_PENDING]
        month_prefix = datetime.now().strftime("%Y-%m")
        month_paid = [p for p in paid if str(p.get("date") or "").startswith(month_prefix)]

        def _sum(items: list[dict]) -> float:
            return round(sum(float(p.get("amount") or 0) for p in items), 2)

        return {
            "monthIncome": _sum(month_paid),
            "monthCount": len(month_paid),
            "totalIncome": _sum(paid),
            "totalCount": len(paid),
            "pendingAmount": _sum(pending),
            "pendingCount": len(pending),
        }
