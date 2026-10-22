"""API 路由汇总：统一挂载到 /api/v1 前缀下。"""
from fastapi import APIRouter

from app.api import (
    auth,
    classes,
    courses,
    dashboard,
    news,
    payments,
    portal,
    resources,
    schedule,
    settings,
    students,
    teachers,
    teaching,
    users,
)

api_router = APIRouter(prefix="/api/v1")

for module_router in (
    auth.router,
    users.router,
    teachers.router,
    courses.router,
    classes.router,
    students.router,
    payments.router,
    news.router,
    resources.router,
    dashboard.router,
    portal.router,
    schedule.router,
    teaching.router,
    settings.router,
):
    api_router.include_router(module_router)

