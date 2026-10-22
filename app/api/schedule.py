"""课表（课次）路由：员工周课表、教师 / 学员 / 家长门户课表，以及考勤统计。

- 员工：查看任意班级/教师课表、按班级补齐课次、调整课次主题与状态；
- 教师：查看自己班级课表、调整课次主题与状态（仅本人班级）；
- 学员 / 家长：只读查看本班 / 关联学员的课表；
- 教师可查看班级考勤汇总（出勤率、迟到/请假/缺勤分布）。
"""
from fastapi import APIRouter, Depends, Query

from app.core.deps import require_parent, require_staff, require_student, require_teacher
from app.core.response import ok
from app.schemas import SessionGenerate, SessionUpdate
from app.services.schedule import ScheduleService
from app.services.teaching import AttendanceService

router = APIRouter(tags=["课表"])
schedule_service = ScheduleService()
attendance_service = AttendanceService()


# ---------- 员工 ----------

@router.get("/sessions")
def list_sessions(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    classId: str | None = Query(default=None),
    teacherId: str | None = Query(default=None),
    _user: dict = Depends(require_staff),
):
    return ok(schedule_service.list_sessions(start=start, end=end, class_id=classId, teacher_id=teacherId))


@router.post("/sessions/generate")
def generate_sessions(body: SessionGenerate, _user: dict = Depends(require_staff)):
    created = schedule_service.generate_for_class(body.class_id, from_date=body.from_date)
    return ok({"created": created}, f"已生成 {created} 个课次")


@router.put("/sessions/{code}")
def update_session(code: str, body: SessionUpdate, _user: dict = Depends(require_staff)):
    return ok(schedule_service.update_session(code, body.model_dump(by_alias=True, exclude_unset=True)))


# ---------- 教师 ----------

@router.get("/portal/teacher/sessions")
def teacher_sessions(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user: dict = Depends(require_teacher),
):
    return ok(schedule_service.teacher_sessions(user["refId"], start, end))


@router.put("/portal/teacher/sessions/{code}")
def teacher_update_session(code: str, body: SessionUpdate, user: dict = Depends(require_teacher)):
    data = body.model_dump(by_alias=True, exclude_unset=True)
    # 教师只允许调整主题与状态，日期/时间由教务统一排课
    data = {k: v for k, v in data.items() if k in ("topic", "status")}
    return ok(schedule_service.update_session(code, data, teacher_code=user["refId"]))


@router.get("/portal/teacher/attendance/summary")
def teacher_attendance_summary(
    classId: str = Query(...),
    month: str | None = Query(default=None),
    user: dict = Depends(require_teacher),
):
    return ok(attendance_service.class_summary(user["refId"], classId, month))


# ---------- 学员 ----------

@router.get("/portal/student/sessions")
def student_sessions(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user: dict = Depends(require_student),
):
    return ok(schedule_service.student_sessions(user["refId"], start, end))


# ---------- 家长 ----------

@router.get("/portal/parent/sessions")
def parent_sessions(
    studentId: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user: dict = Depends(require_parent),
):
    return ok(schedule_service.parent_sessions(user["refId"], studentId, start, end))
