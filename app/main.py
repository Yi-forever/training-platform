"""应用入口：uvicorn app.main:app --reload

职责：
- 注册 /api/v1 全部业务路由（对齐《02-总体设计》§6.2）；
- 统一响应壳与异常处理（BizException -> HTTP + 中文提示）；
- CORS 放开（原型联调）；
- 挂载 web/ 静态前端（登录后浏览器直接访问 /login.html 预览）。
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import WEB_DIR
from app.core.exceptions import BizException
from app.db.repository import db as repository
from app.db.seed import seed_db
from app.db.session import Base, init_db
from app.services.finance import BillService
from app.services.schedule import ScheduleService
import app.db.models  # noqa: F401  确保模型注册到 metadata


def _ensure_db() -> None:
    """建表并在空库时播种种子数据（uvicorn 启动与测试首次访问均会触发）。

    老库（v0.4）没有 `bills` 表数据：启动时按课程价补建应收账单，并把历史学费
    流水挂到账单上，保证升级后家长端「应缴 / 已缴 / 欠费」立即可用。
    老库同样没有课次数据：启动时按班级排课规则补齐课表。
    """
    init_db()
    if repository.find("users", "admin") is None:
        seed_db()
    else:
        BillService().backfill()
    ScheduleService().ensure_all()


app = FastAPI(
    title="启航编程管理系统 API",
    version="0.1.0",
    description=(
        "培训机构一站式管理后端 · 关系数据库版（SQLAlchemy + SQLite/MySQL）。\n\n"
        "统一响应壳：成功 `{code: 0, message, data}`，失败 `{code, message}`。\n\n"
        "认证方式：`Authorization: Bearer <token>`（POST /api/v1/auth/login 获取）。"
    ),
)


@app.on_event("startup")
def _startup() -> None:
    _ensure_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BizException)
async def biz_exception_handler(request: Request, exc: BizException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败 -> 422 + 中文提示（取第一条错误）。"""
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        msg = str(first.get("msg", "参数错误"))
        if "missing" in msg:
            msg = "缺少必填字段"
        elif "greater than" in msg or "less than" in msg:
            msg = "数值超出允许范围"
        elif "min_length" in msg or "String should have at least" in msg:
            msg = "长度不满足要求"
        elif "not match" in msg or "pattern" in msg:
            msg = "格式不正确"
        message = f"参数校验失败（{loc}）：{msg}" if loc else f"参数校验失败：{msg}"
    else:
        message = "参数校验失败"
    return JSONResponse(status_code=422, content={"code": 422, "message": message})


@app.get("/api/v1/health")
def health():
    return {"code": 0, "message": "ok", "data": {"status": "up"}}


@app.get("/")
def index():
    return RedirectResponse(url="/login.html")


# 业务路由（先注册，优先于静态挂载）
app.include_router(api_router)

# 前端静态托管（原型一体化预览；data/app.json 为运行时数据，不入库）
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
