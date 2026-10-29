"""开课申请路由：教师提交 / 撤回，教务与超管审核。

- 教师：`/portal/teacher/course-proposals`（仅本人数据）；
- 教务 / 超管：`/course-proposals`（全部申请）、审核、统计；
- 其他身份（学员 / 家长 / 前台 / 财务）一律 403。
"""
from fastapi import APIRouter, Depends, Query

from app.api.pagination import Pagination
from app.core.config import ROLE_ACADEMIC, ROLE_ADMIN
from app.core.deps import require_roles, require_teacher
from app.core.response import ok
from app.schemas import CourseProposalCreate, CourseProposalReview
from app.services.proposal import CourseProposalService

router = APIRouter(tags=["开课申请"])
service = CourseProposalService()
reviewer_only = require_roles(ROLE_ADMIN, ROLE_ACADEMIC)


# ---------- 教务 / 超管 ----------

@router.get("/course-proposals/stats")
def proposal_stats(_user: dict = Depends(reviewer_only)):
    return ok(service.stats())


@router.get("/course-proposals")
def list_proposals(
    p: Pagination = Depends(),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    _user: dict = Depends(reviewer_only),
):
    return ok(service.list(
        status=status, keyword=keyword, page=p.page, page_size=p.page_size,
    ))


@router.post("/course-proposals/{code}/review")
def review_proposal(code: str, body: CourseProposalReview, user: dict = Depends(reviewer_only)):
    result = service.review(code, body.action, user["username"], note=body.note)
    message = (
        f"已通过申请并创建课程「{result.get('courseName') or result.get('name')}」"
        if body.action == "approve" else "已驳回开课申请"
    )
    return ok(result, message)


# ---------- 教师 ----------

@router.get("/portal/teacher/course-proposals")
def teacher_proposals(user: dict = Depends(require_teacher)):
    return ok(service.list_for_teacher(user["refId"]))


@router.post("/portal/teacher/course-proposals")
def create_proposal(body: CourseProposalCreate, user: dict = Depends(require_teacher)):
    return ok(
        service.create_for_teacher(user["refId"], body.model_dump(by_alias=True)),
        "开课申请已提交，等待教务审核",
    )


@router.delete("/portal/teacher/course-proposals/{code}")
def cancel_proposal(code: str, user: dict = Depends(require_teacher)):
    return ok(service.cancel(user["refId"], code), "开课申请已撤回")
