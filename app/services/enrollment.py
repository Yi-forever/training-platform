"""选课业务规则：可选班级目录、选课申请、名额与时间冲突校验、审核、退课与候补顺延。

设计要点：
- **可选班级目录**只展示「课程在售 + 班级未结课」的班期，并给出剩余名额、学费与
  与本人已选班级的时间冲突提示；
- **申请**：名额未满 -> 待审核；名额已满 -> 候补（记录顺位）；重复申请与时间冲突
  直接拒绝（409），「学员 + 班级」唯一，被驳回 / 退课后重新申请复用同一条记录；
- **审核**：员工通过后写入「已通过」，同步学员主班并生成该班应收账单；
- **退课**：释放名额，未缴费账单自动作废，候补按顺位自动转正（跳过时间冲突者）；
- 学员可兼报多个班级：``students.classId`` 只表示主班，完整归属以本表「已通过」
  记录为准（``enrolled_class_ids``）。
"""
from __future__ import annotations

from typing import Any

from app.core.config import now_iso
from app.core.exceptions import BizException
from app.db.repository import db
from app.services.base import CrudService, today
from app.services.scheduling import parse_schedule_text

PENDING = "待审核"
APPROVED = "已通过"
REJECTED = "已驳回"
WITHDRAWN = "已退课"
WAITLIST = "候补"
STATUSES = (PENDING, APPROVED, REJECTED, WITHDRAWN, WAITLIST)
ACTIVE_STATUSES = (PENDING, APPROVED, WAITLIST)
SOURCES = ("学员", "家长", "员工")


# ---------- 归属查询（供班级人数 / 作业 / 课表 / 账单复用） ----------

def enrolled_class_ids(student_code: str) -> list[str]:
    """学员当前在读的班级（按通过顺序，首个为主班）。

    以「已通过」选课记录为准；若历史数据尚无选课记录，则回退到 ``students.classId``，
    保证老库升级后行为不变。
    """
    rows = [
        e for e in db.alive("enrollments")
        if e.get("studentId") == student_code and e.get("status") == APPROVED
    ]
    rows.sort(key=lambda e: (e.get("createdAt") or "", e.get("id") or ""))
    ids: list[str] = []
    for row in rows:
        class_id = row.get("classId")
        if class_id and class_id not in ids and db.find("classes", class_id):
            ids.append(class_id)
    if ids:
        return ids
    stu = db.find("students", student_code or "")
    return [stu["classId"]] if stu and stu.get("classId") else []


def enrolled_student_ids(class_id: str) -> set[str]:
    """班级在册学员：已通过选课记录 + ``students.classId``（兼容历史数据）。"""
    ids = {
        e["studentId"] for e in db.alive("enrollments")
        if e.get("classId") == class_id and e.get("status") == APPROVED
    }
    ids |= {s["id"] for s in db.alive("students") if s.get("classId") == class_id}
    return ids


def enrolled_count(class_id: str) -> int:
    return len(enrolled_student_ids(class_id))


# ---------- 时间冲突 ----------

def _slots_of(class_id: str) -> list[dict[str, Any]]:
    """班级上课时段：优先取结构化排课规则，缺省回退解析「上课时间」文本。"""
    rules = [r for r in db.alive("classSchedules") if r.get("classId") == class_id]
    slots = [
        {
            "weekday": int(r.get("weekday") or 0),
            "startTime": r.get("startTime"),
            "endTime": r.get("endTime"),
        }
        for r in rules
        if r.get("startTime") and r.get("endTime")
    ]
    if slots:
        return slots
    cls = db.find("classes", class_id or "")
    return parse_schedule_text(cls.get("schedule") if cls else None)


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("weekday") != b.get("weekday"):
        return False
    return a["startTime"] < b["endTime"] and b["startTime"] < a["endTime"]


def conflict_class(student_code: str, class_id: str) -> dict[str, Any] | None:
    """与学员已选班级的上课时间冲突时返回冲突班级，否则 None。"""
    target_slots = _slots_of(class_id)
    if not target_slots:
        return None
    for other_id in enrolled_class_ids(student_code):
        if other_id == class_id:
            continue
        other = db.find("classes", other_id)
        if not other:
            continue
        if any(_overlap(t, o) for t in target_slots for o in _slots_of(other_id)):
            return other
    return None


class EnrollmentService(CrudService):
    coll = "enrollments"
    prefix = "XK"
    label = "选课记录"
    default_order = "createdAt"
    search_fields = ("id", "studentId", "classId", "source", "note", "reviewNote")

    # ---------- 列表 ----------

    def list(self, *, status: str | None = None, class_id: str | None = None, **kwargs) -> dict:
        return super().list(
            extra_filters={"status": status, "classId": class_id}, **kwargs
        )

    def _sort(self, rows: list[dict], field: str) -> list[dict]:
        if not field:
            return rows
        return sorted(rows, key=lambda r: str(r.get(field) or ""), reverse=True)

    def _match(self, row: dict, kw: str) -> bool:
        if super()._match(row, kw):
            return True
        stu = db.find("students", row.get("studentId") or "")
        cls = db.find("classes", row.get("classId") or "")
        return any(
            kw in str(x or "").lower()
            for x in (stu.get("name") if stu else "", cls.get("name") if cls else "")
        )

    def decorate(self, row: dict) -> dict[str, Any]:
        cls = db.find("classes", row.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        teacher = db.find("teachers", cls.get("teacherId") or "") if cls else None
        stu = db.find("students", row.get("studentId") or "")
        capacity = int(cls.get("capacity") or 0) if cls else 0
        enrolled = enrolled_count(cls["id"]) if cls else 0
        return {
            **row,
            "studentName": stu.get("name") if stu else "",
            "grade": stu.get("grade") if stu else "",
            "className": cls.get("name") if cls else "",
            "classStatus": cls.get("status") if cls else "",
            "courseName": course.get("name") if course else "",
            "category": course.get("category") if course else "",
            "teacherName": teacher.get("name") if teacher else "",
            "schedule": cls.get("schedule") if cls else "",
            "classroom": cls.get("classroom") if cls else "",
            "price": float(course.get("price") or 0) if course else 0.0,
            "hours": int(course.get("hours") or 0) if course else 0,
            "capacity": capacity,
            "enrolled": enrolled,
            "remaining": max(capacity - enrolled, 0),
        }

    # ---------- 可选班级目录 ----------

    def catalog(
        self,
        *,
        student_id: str | None = None,
        keyword: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        kw = (keyword or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for cls in db.alive("classes"):
            if cls.get("status") == "已结课":
                continue
            course = db.find("courses", cls.get("courseId") or "")
            if not course or course.get("status") != "在售":
                continue
            if category and course.get("category") != category:
                continue
            text = f"{cls.get('name')} {cls.get('id')} {course.get('name')} {course.get('category')}"
            if kw and kw not in text.lower():
                continue

            teacher = db.find("teachers", cls.get("teacherId") or "")
            capacity = int(cls.get("capacity") or 0)
            enrolled = enrolled_count(cls["id"])
            mine = None
            if student_id:
                mine = next((
                    e for e in db.alive("enrollments")
                    if e.get("studentId") == student_id
                    and e.get("classId") == cls["id"]
                    and e.get("status") in ACTIVE_STATUSES
                ), None)
            conflict = conflict_class(student_id, cls["id"]) if student_id else None
            remaining = max(capacity - enrolled, 0)
            rows.append({
                "classId": cls["id"],
                "className": cls.get("name"),
                "classStatus": cls.get("status"),
                "courseId": course.get("id"),
                "courseName": course.get("name"),
                "category": course.get("category"),
                "level": course.get("level"),
                "hours": int(course.get("hours") or 0),
                "price": float(course.get("price") or 0),
                "teacherName": teacher.get("name") if teacher else "",
                "classroom": cls.get("classroom"),
                "schedule": cls.get("schedule"),
                "startDate": cls.get("startDate"),
                "endDate": cls.get("endDate"),
                "capacity": capacity,
                "enrolled": enrolled,
                "remaining": remaining,
                "isFull": capacity > 0 and remaining <= 0,
                "myStatus": mine.get("status") if mine else "",
                "myEnrollmentId": mine.get("id") if mine else None,
                "waitlistNo": mine.get("waitlistNo") if mine else None,
                "conflictClassName": conflict.get("name") if conflict else "",
                "canApply": not mine and not conflict,
            })
        rows.sort(key=lambda r: (str(r.get("startDate") or "9999-12-31"), r["classId"]))
        return rows

    # ---------- 申请 ----------

    def _prepare(self, student_code: str, class_id: str):
        stu = db.locate("students", student_code or "", label="学员")
        if stu.get("status") == "已结课":
            raise BizException(409, "该学员已结课，无法继续选课")
        cls = db.locate("classes", class_id or "", label="班级")
        course = db.find("courses", cls.get("courseId") or "")
        if cls.get("status") == "已结课":
            raise BizException(409, f"班级「{cls.get('name')}」已结课，无法选课")
        if not course or course.get("status") != "在售":
            raise BizException(409, "该课程已停售，无法选课")

        existing = db.find_one("enrollments", studentId=student_code, classId=class_id)
        if existing and existing.get("status") in ACTIVE_STATUSES:
            raise BizException(409, f"已申请或已选「{cls.get('name')}」，无需重复提交")

        conflict = conflict_class(student_code, class_id)
        if conflict:
            raise BizException(
                409,
                f"与已选班级「{conflict.get('name')}」上课时间冲突"
                f"（{conflict.get('schedule') or '排课待定'}）",
            )

        capacity = int(cls.get("capacity") or 0)
        enrolled = enrolled_count(class_id)
        return stu, cls, existing, capacity, enrolled, capacity > 0 and enrolled >= capacity

    def _next_waitlist_no(self, class_id: str) -> int:
        used = [
            int(e.get("waitlistNo") or 0) for e in db.alive("enrollments")
            if e.get("classId") == class_id and e.get("status") == WAITLIST
        ]
        return (max(used) if used else 0) + 1

    def apply(
        self, student_code: str, class_id: str, *, note: str | None = None, source: str = "学员"
    ) -> dict[str, Any]:
        _stu, cls, existing, _capacity, _enrolled, full = self._prepare(student_code, class_id)
        ts = now_iso()
        fields = {
            "status": WAITLIST if full else PENDING,
            "source": source if source in SOURCES else "学员",
            "note": (note or "").strip() or None,
            "reviewNote": None,
            "reviewedBy": None,
            "reviewedAt": None,
            "waitlistNo": self._next_waitlist_no(class_id) if full else None,
            "updatedAt": ts,
        }
        if existing:
            rec = db.update_fields("enrollments", existing["id"], fields, label="选课记录")
        else:
            rec = {
                "id": db.next_code("enrollments", "XK"),
                "studentId": student_code,
                "classId": class_id,
                **fields,
                "createdAt": ts,
            }
            db.insert("enrollments", rec)
        result = self.decorate(rec)
        result["message"] = (
            f"「{cls.get('name')}」名额已满，已进入候补第 {result.get('waitlistNo')} 位"
            if full else f"选课申请已提交，等待机构审核「{cls.get('name')}」"
        )
        return result

    def enroll_by_staff(
        self, student_code: str, class_id: str, staff_code: str, *, note: str | None = None
    ) -> dict[str, Any]:
        """员工代报名：校验名额与时间冲突后直接通过并入班。"""
        _stu, cls, existing, capacity, enrolled, full = self._prepare(student_code, class_id)
        if full:
            raise BizException(
                409, f"班级「{cls.get('name')}」名额已满（{enrolled}/{capacity}），无法直接报名"
            )
        ts = now_iso()
        fields = {
            "status": APPROVED,
            "source": "员工",
            "note": (note or "").strip() or None,
            "reviewNote": "员工代报名",
            "reviewedBy": staff_code,
            "reviewedAt": ts,
            "waitlistNo": None,
            "updatedAt": ts,
        }
        if existing:
            rec = db.update_fields("enrollments", existing["id"], fields, label="选课记录")
        else:
            rec = {
                "id": db.next_code("enrollments", "XK"),
                "studentId": student_code,
                "classId": class_id,
                **fields,
                "createdAt": ts,
            }
            db.insert("enrollments", rec)
        self._sync_primary(student_code)
        self._create_bill(student_code, class_id)
        return self.decorate(rec)

    # ---------- 审核 ----------

    def review(
        self, code: str, action: str, staff_code: str, *, note: str | None = None
    ) -> dict[str, Any]:
        if action not in ("approve", "reject"):
            raise BizException(400, "审核动作只能是 approve 或 reject")
        rec = db.locate("enrollments", code or "", label="选课记录")
        if rec.get("status") not in (PENDING, WAITLIST):
            raise BizException(
                409, f"当前状态为「{rec.get('status')}」，只有待审核 / 候补记录可以审核"
            )
        ts = now_iso()
        if action == "reject":
            text = (note or "").strip() or "不符合开班条件，建议改报其他班级"
            updated = db.update_fields(
                "enrollments", code,
                {
                    "status": REJECTED,
                    "reviewNote": text,
                    "reviewedBy": staff_code,
                    "reviewedAt": ts,
                    "waitlistNo": None,
                    "updatedAt": ts,
                },
                label="选课记录",
            )
            return self.decorate(updated)

        stu = db.find("students", rec.get("studentId") or "")
        if stu and stu.get("status") == "已结课":
            raise BizException(409, "该学员已结课，无法通过选课申请")

        self._ensure_seat(rec)
        conflict = conflict_class(rec.get("studentId") or "", rec.get("classId") or "")
        if conflict:
            raise BizException(
                409,
                f"该学员已选班级「{conflict.get('name')}」时间冲突，无法通过审核",
            )
        return self.decorate(self._approve(rec, staff_code, note))

    def _ensure_seat(self, rec: dict[str, Any]) -> None:
        cls = db.locate("classes", rec.get("classId") or "", label="班级")
        capacity = int(cls.get("capacity") or 0)
        enrolled = enrolled_count(cls["id"])
        if capacity > 0 and enrolled >= capacity:
            raise BizException(
                409,
                f"班级「{cls.get('name')}」名额已满（{enrolled}/{capacity}），"
                "请先处理退课或调整班容",
            )

    def _approve(self, rec: dict[str, Any], staff_code: str, note: str | None) -> dict[str, Any]:
        ts = now_iso()
        updated = db.update_fields(
            "enrollments", rec["id"],
            {
                "status": APPROVED,
                "reviewNote": (note or "").strip() or "审核通过",
                "reviewedBy": staff_code,
                "reviewedAt": ts,
                "waitlistNo": None,
                "updatedAt": ts,
            },
            label="选课记录",
        )
        self._sync_primary(rec.get("studentId") or "")
        self._create_bill(rec.get("studentId") or "", rec.get("classId") or "")
        return updated

    def _sync_primary(self, student_code: str) -> None:
        """把学员主班同步为最早通过的班级；全部退课时置空（待分班）。"""
        stu = db.find("students", student_code or "")
        if not stu:
            return
        ids = enrolled_class_ids(student_code)
        target = ids[0] if ids else ""
        if (stu.get("classId") or "") == target:
            return
        db.update_fields(
            "students", student_code,
            {"classId": target, "updatedAt": now_iso()},
            label="学员",
        )

    def _create_bill(self, student_code: str, class_id: str) -> None:
        stu = db.find("students", student_code or "")
        if not stu:
            return
        from app.services.finance import BillService

        try:
            BillService().create_for_class(
                stu, class_id, note="选课学费（按课程价生成）", due_from=today()
            )
        except BizException:
            pass

    def _void_unpaid_bills(self, student_code: str, class_id: str) -> None:
        """退课时作废该班未收款的账单；已有收款流水保持原状，由财务处理退费。"""
        paid: dict[str, float] = {}
        for p in db.alive("payments"):
            bill_id = p.get("billId")
            if bill_id and p.get("status") == "已支付":
                paid[bill_id] = paid.get(bill_id, 0.0) + float(p.get("amount") or 0)
        for bill in db.alive("bills"):
            if bill.get("studentId") != student_code or bill.get("classId") != class_id:
                continue
            if bill.get("status") == "已作废" or paid.get(bill["id"], 0.0) > 0:
                continue
            db.update_fields(
                "bills", bill["id"],
                {"status": "已作废", "updatedAt": now_iso()},
                label="账单",
            )

    # ---------- 退课 ----------

    def cancel(
        self,
        code: str,
        *,
        student_code: str | None = None,
        parent_code: str | None = None,
        staff_code: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        rec = db.locate("enrollments", code or "", label="选课记录")
        if student_code and rec.get("studentId") != student_code:
            raise BizException(403, "只能退本人的选课记录")
        if parent_code:
            children = {c["id"] for c in db.list_children_of(parent_code)}
            if rec.get("studentId") not in children:
                raise BizException(403, "只能为本人关联学员退课")
        if rec.get("status") not in (PENDING, WAITLIST, APPROVED):
            raise BizException(
                409, f"当前状态为「{rec.get('status')}」，无法退课"
            )

        was_approved = rec.get("status") == APPROVED
        ts = now_iso()
        updated = db.update_fields(
            "enrollments", code,
            {
                "status": WITHDRAWN,
                "waitlistNo": None,
                "reviewNote": (reason or "").strip() or "已退课",
                "reviewedBy": staff_code or rec.get("reviewedBy"),
                "reviewedAt": ts,
                "updatedAt": ts,
            },
            label="选课记录",
        )
        promoted = None
        if was_approved:
            self._void_unpaid_bills(rec.get("studentId") or "", rec.get("classId") or "")
            self._sync_primary(rec.get("studentId") or "")
            promoted = self._promote_waitlist(rec.get("classId") or "", staff_code or "system")
        return {"enrollment": self.decorate(updated), "promoted": promoted}

    def _promote_waitlist(self, class_id: str, staff_code: str) -> dict[str, Any] | None:
        """名额释放后按顺位自动转正：跳过与已选班级冲突的候补。"""
        cls = db.find("classes", class_id)
        if not cls:
            return None
        capacity = int(cls.get("capacity") or 0)
        candidates = [
            e for e in db.alive("enrollments")
            if e.get("classId") == class_id and e.get("status") == WAITLIST
        ]
        candidates.sort(key=lambda e: (int(e.get("waitlistNo") or 999), e.get("createdAt") or ""))
        for cand in candidates:
            if capacity > 0 and enrolled_count(class_id) >= capacity:
                return None
            stu = db.find("students", cand.get("studentId") or "")
            if stu and stu.get("status") == "已结课":
                continue
            if conflict_class(cand.get("studentId") or "", class_id):
                continue
            return self.decorate(self._approve(cand, staff_code, "候补顺延自动通过"))
        return None

    # ---------- 门户查询 ----------

    def list_for_student(self, student_code: str) -> list[dict[str, Any]]:
        rows = [e for e in db.alive("enrollments") if e.get("studentId") == student_code]
        rows.sort(key=lambda e: (e.get("createdAt") or "", e.get("id") or ""), reverse=True)
        return [self.decorate(e) for e in rows]

    def list_for_parent(
        self, parent_code: str, student_id: str | None = None
    ) -> list[dict[str, Any]]:
        children = db.list_children_of(parent_code)
        if student_id:
            children = [c for c in children if c.get("id") == student_id]
            if not children:
                raise BizException(403, "该学员不在您的关联范围内")
        ids = {c["id"] for c in children}
        rows = [e for e in db.alive("enrollments") if e.get("studentId") in ids]
        rows.sort(key=lambda e: (e.get("createdAt") or "", e.get("id") or ""), reverse=True)
        return [self.decorate(e) for e in rows]

    def stats(self) -> dict[str, Any]:
        rows = db.alive("enrollments")
        month = today()[:7]
        return {
            "total": len(rows),
            "pending": sum(1 for e in rows if e.get("status") == PENDING),
            "approved": sum(1 for e in rows if e.get("status") == APPROVED),
            "waitlist": sum(1 for e in rows if e.get("status") == WAITLIST),
            "rejected": sum(1 for e in rows if e.get("status") == REJECTED),
            "withdrawn": sum(1 for e in rows if e.get("status") == WITHDRAWN),
            "monthApplied": sum(1 for e in rows if (e.get("createdAt") or "").startswith(month)),
            "classCount": len({e.get("classId") for e in rows if e.get("status") == APPROVED}),
        }

    # ---------- 存量数据补录 ----------

    def backfill(self) -> int:
        """为「已分班但无选课记录」的老学员补一条已通过记录（幂等）。"""
        created = 0
        for stu in db.alive("students"):
            class_id = stu.get("classId") or ""
            if not class_id or not db.find("classes", class_id):
                continue
            exists = any(
                e for e in db.alive("enrollments")
                if e.get("studentId") == stu["id"] and e.get("classId") == class_id
            )
            if exists:
                continue
            ts = now_iso()
            db.insert("enrollments", {
                "id": db.next_code("enrollments", "XK"),
                "studentId": stu["id"],
                "classId": class_id,
                "status": APPROVED,
                "source": "员工",
                "note": None,
                "reviewNote": "历史报名补录",
                "reviewedBy": "system",
                "reviewedAt": ts,
                "waitlistNo": None,
                "createdAt": stu.get("enrollDate") or ts,
                "updatedAt": ts,
            })
            created += 1
        return created
