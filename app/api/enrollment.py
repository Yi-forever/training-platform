"""选课路由：可选班级目录、学员 / 家长自助选课、员工审核与代报名。

门禁：
- 目录：任意已登录身份可读；学员固定看本人、家长仅能看关联学员；
- 学员 / 家长：只能申请、退本人的选课（家长限关联学员）；
- 员工（超管 / 教务 / 前台）：查看全部选课、审核、代报名、退课。
"""
from fastapi import APIRouter, Depends, Query

from app.api.pagination import Pagination
from app.core.config import ROLE_ACADEMIC, ROLE_ADMIN, ROLE_FRONTDESK
from app.core.deps import get_current_user, require_parent, require_roles, require_staff, require_student
from app.core.exceptions import BizException
from app.core.response import ok
from app.db.repository import db
from app.schemas import (
    EnrollmentApply,
    EnrollmentReview,
    ParentEnrollmentApply,
    StaffEnrollmentCreate,
)
from app.services.enrollment import EnrollmentService

router = APIRouter(tags=["选课"])
service = EnrollmentService()
staff_only = require_roles(ROLE_ADMIN, ROLE_ACADEMIC, ROLE_FRONTDESK)


# ---------- 可选班级目录 ----------

@router.get("/enrollments/catalog")
def catalog(
    keyword: str | None = Query(default=None),
    category: str | None = Query(default=None),
    studentId: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """可选班级目录；带 studentId 时返回该学员的选课状态与时间冲突提示。"""
    sid = studentId
    if user.get("identity") == "student":
        sid = user.get("refId")
    elif user.get("identity") == "parent" and sid:
        children = {c["id"] for c in db.list_children_of(user.get("refId") or "")}
        if sid not in children:
            raise BizException(403, "只能查看本人关联学员的选课状态")
    elif user.get("identity") not in ("staff", "parent", "student"):
        sid = None
    return ok(service.catalog(student_id=sid, keyword=keyword, category=category))


# ---------- 员工：选课管理 ----------

@router.get("/enrollments/stats")
def enrollment_stats(_user: dict = Depends(require_staff)):
    return ok(service.stats())


@router.get("/enrollments")
def list_enrollments(
    p: Pagination = Depends(),
    status: str | None = Query(default=None),
    classId: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    _user: dict = Depends(require_staff),
):
    return ok(service.list(
        status=status, class_id=classId, keyword=keyword,
        page=p.page, page_size=p.page_size,
    ))


@router.post("/enrollments")
def enroll_by_staff(body: StaffEnrollmentCreate, user: dict = Depends(staff_only)):
    return ok(
        service.enroll_by_staff(body.student_id, body.class_id, user["username"], note=body.note),
        "已为该学员办理入班",
    )


@router.post("/enrollments/{code}/review")
def review_enrollment(code: str, body: EnrollmentReview, user: dict = Depends(staff_only)):
    result = service.review(code, body.action, user["username"], note=body.note)
    return ok(result, "已通过选课申请" if body.action == "approve" else "已驳回选课申请")


@router.delete("/enrollments/{code}")
def staff_withdraw(code: str, user: dict = Depends(staff_only)):
    result = service.cancel(code, staff_code=user["username"], reason="员工办理退课")
    return ok(result, "已办理退课")


# ---------- 学员 ----------

@router.get("/portal/student/enrollments")
def student_enrollments(user: dict = Depends(require_student)):
    return ok(service.list_for_student(user["refId"]))


@router.post("/portal/student/enrollments")
def student_apply(body: EnrollmentApply, user: dict = Depends(require_student)):
    result = service.apply(user["refId"], body.class_id, note=body.note, source="学员")
    return ok(result, result.get("message") or "选课申请已提交")


@router.delete("/portal/student/enrollments/{code}")
def student_withdraw(code: str, user: dict = Depends(require_student)):
    result = service.cancel(code, student_code=user["refId"], reason="学员自助退课")
    return ok(result, "已退课")


# ---------- 家长 ----------

@router.get("/portal/parent/enrollments")
def parent_enrollments(
    studentId: str | None = Query(default=None),
    user: dict = Depends(require_parent),
):
    return ok(service.list_for_parent(user["refId"], studentId))


@router.post("/portal/parent/enrollments")
def parent_apply(body: ParentEnrollmentApply, user: dict = Depends(require_parent)):
    children = {c["id"] for c in db.list_children_of(user["refId"])}
    if body.student_id not in children:
        raise BizException(403, "只能为本人关联学员选课")
    result = service.apply(body.student_id, body.class_id, note=body.note, source="家长")
    return ok(result, result.get("message") or "选课申请已提交")


@router.delete("/portal/parent/enrollments/{code}")
def parent_withdraw(code: str, user: dict = Depends(require_parent)):
    result = service.cancel(code, parent_code=user["refId"], reason="家长代为退课")
    return ok(result, "已退课")
