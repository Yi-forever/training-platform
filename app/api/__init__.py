"""API 路由汇总：统一挂载到 /api/v1 前缀下。"""
from fastapi import APIRouter

from app.api import (
    auth,
    classes,
    courses,
    dashboard,
    enrollment,
    news,
    payments,
    portal,
    proposals,
    resources,
    schedule,
    settings,
    students,
    teachers,
    teaching,
    timetable,
    users,
)

api_router = APIRouter(prefix="/api/v1")

for module_router in (
    auth.router,
    users.router,
    teachers.router,
    courses.router,
    classes.router,
    schedule.router,
    students.router,
    enrollment.router,
    payments.router,
    news.router,
    resources.router,
    dashboard.router,
    portal.router,
    proposals.router,
    timetable.router,
    teaching.router,
    settings.router,
):
    api_router.include_router(module_router)

