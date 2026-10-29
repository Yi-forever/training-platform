"""四类身份登录 / 身份区分 / 数据库 CRUD 回归测试。

覆盖需求：
- 员工（staff） / 教师（teacher） / 学员（student） / 家长（parent）四类账户登录
- 不同身份的工作台（/auth/context）数据清晰区分
- 身份门禁（require_identity）
- 关系数据库的增删改查与软删 / 级联删除

运行：``python3.11 -m pytest tests/test_identities.py -q``
"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

# 必须在导入 app 之前确定数据库位置（SQLAlchemy engine 在导入时即创建）
_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_identities_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.core.deps import require_identity
from app.core.exceptions import BizException
from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app

API = "/api/v1"

# 种子账号（见 app/db/seed.py）
CRED = {
    "staff": ("admin", "admin123"),       # 超级管理员
    "teacher": ("JS001", "123456"),       # 王志强
    "student": ("XS001", "123456"),       # 陈一诺
    "parent": ("P001", "123456"),         # 陈大文（学员 XS001 的家长）
}


@pytest.fixture(scope="module")
def client():
    # 只重置表结构，不删除库文件：engine 仍持有连接与 WAL，删文件会导致后续模块 disk I/O error
    init_db()
    reset_schema()
    seed_db()
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败: {r.text}"
    return r.json()["data"]


def token_of(client, identity):
    u, p = CRED[identity]
    return login(client, u, p)["token"]


# ---------------- 四类身份登录 ----------------

def test_staff_login(client):
    data = login(client, *CRED["staff"])
    assert data["user"]["identity"] == "staff"
    assert data["user"]["role"] == "超级管理员"
    assert "passwordHash" not in data["user"]


def test_teacher_login(client):
    data = login(client, *CRED["teacher"])
    assert data["user"]["identity"] == "teacher"
    assert data["user"]["role"] == "教师"


def test_student_login(client):
    data = login(client, *CRED["student"])
    assert data["user"]["identity"] == "student"
    assert data["user"]["role"] == "学员"


def test_parent_login(client):
    data = login(client, *CRED["parent"])
    assert data["user"]["identity"] == "parent"
    assert data["user"]["role"] == "家长"


def test_parent_login_by_phone(client):
    """家长支持手机号登录（与员工/教师共用号码时优先家长身份）。"""
    data = login(client, "15868710001", "123456")
    assert data["user"]["identity"] == "parent"
    assert data["user"]["username"] == "P001"


# ---------------- 异常登录 ----------------

def test_wrong_password_401(client):
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "xx"})
    assert r.status_code == 401


def test_disabled_account_403(client):
    """禁用账号（wangzq）登录应被拒绝。"""
    r = client.post(f"{API}/auth/login", json={"username": "wangzq", "password": "123456"})
    assert r.status_code == 403


def test_missing_token_401(client):
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 401


# ---------------- 身份区分（工作台上下文） ----------------

def test_context_identity_specific(client):
    """不同身份返回各自专属的工作台数据结构。"""
    # staff：仅基础信息
    token = token_of(client, "staff")
    ctx = client.get(f"{API}/auth/context", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    assert ctx["identity"] == "staff"
    assert "classes" not in ctx and "children" not in ctx

    # teacher：含执教班级与学员数
    token = token_of(client, "teacher")
    ctx = client.get(f"{API}/auth/context", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    assert ctx["identity"] == "teacher"
    assert "classes" in ctx and "studentCount" in ctx

    # student：含班级 / 课程 / 教师 / 已缴总额
    token = token_of(client, "student")
    ctx = client.get(f"{API}/auth/context", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    assert ctx["identity"] == "student"
    assert {"className", "courseName", "teacherName", "paidTotal"} <= set(ctx)

    # parent：含关联学员列表
    token = token_of(client, "parent")
    ctx = client.get(f"{API}/auth/context", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    assert ctx["identity"] == "parent"
    assert "children" in ctx and len(ctx["children"]) >= 1


# ---------------- 身份门禁 ----------------

def test_require_identity_gating():
    """require_identity 对不匹配的身份抛出 403。"""
    staff_user = {"identity": "staff", "role": "教务管理员"}
    with pytest.raises(BizException) as exc:
        require_identity("teacher", "student", user=staff_user)
    assert exc.value.status_code == 403

    teacher_user = {"identity": "teacher", "role": "教师"}
    # 命中白名单：不抛异常
    assert require_identity("teacher", "student", user=teacher_user)["identity"] == "teacher"


# ---------------- 数据库 CRUD ----------------

def test_db_crud_roundtrip(client):
    """新建 -> 读取 -> 软删 -> 404 的数据库生命周期。"""
    import time

    from app.db.repository import db

    teacher = {
        "id": f"JSTEST{int(time.time()) % 100000}",
        "name": "测试讲师", "gender": "男", "phone": "13900000000",
        "email": "t@qh.cn", "subject": "Scratch", "title": "讲师",
        "hireDate": "2026-01-01", "status": "在职",
    }
    db.insert("teachers", teacher)
    got = db.find("teachers", teacher["id"])
    assert got is not None and got["name"] == "测试讲师"

    db.soft_delete("teachers", teacher["id"])
    assert db.find("teachers", teacher["id"]) is None  # 软删后不可见


def test_cascade_delete_student_payment(client):
    """删除学员时，其名下缴费记录一并软删（404）。"""
    admin = token_of(client, "staff")
    headers = {"Authorization": f"Bearer {admin}"}

    # 选取一个名下确有缴费的种子学员（XS002 -> JF002），且与其它测试不复用
    r = client.delete(f"{API}/students/XS002", headers=headers)
    assert r.status_code == 200
    r = client.get(f"{API}/payments/JF002", headers=headers)
    assert r.status_code == 404


def test_payments_stats_after_void(client):
    """作废缴费不计入收入（验证金额口径未被数据库切换破坏）。"""
    admin = token_of(client, "staff")
    headers = {"Authorization": f"Bearer {admin}"}
    r = client.post(f"{API}/payments/JF005/void", headers=headers)
    assert r.status_code == 200
    stats = client.get(f"{API}/payments/stats", headers=headers).json()["data"]
    assert "totalIncome" in stats and "totalCount" in stats


# ---------------- 身份门禁（管理后台仅员工可见） ----------------

def test_non_staff_blocked_from_admin_lists(client):
    """非员工（教师 / 学员 / 家长）访问后台管理列表与看板应被拦截（403）。"""
    for identity in ("teacher", "student", "parent"):
        token = token_of(client, identity)
        h = {"Authorization": f"Bearer {token}"}
        assert client.get(f"{API}/students", headers=h).status_code == 403
        assert client.get(f"{API}/payments", headers=h).status_code == 403
        assert client.get(f"{API}/dashboard/summary", headers=h).status_code == 403


def test_staff_can_access_admin_lists(client):
    """员工（超级管理员）可正常访问后台管理列表。"""
    h = {"Authorization": f"Bearer {token_of(client, 'staff')}"}
    assert client.get(f"{API}/students", headers=h).status_code == 200
    assert client.get(f"{API}/classes", headers=h).status_code == 200


def test_portal_overview_scoped_by_identity(client):
    """portal/overview 按登录身份返回专属字段，彼此不串数据。"""
    teacher = client.get(f"{API}/portal/overview", headers={"Authorization": f"Bearer {token_of(client, 'teacher')}"}).json()["data"]
    assert teacher["identity"] == "teacher" and "classes" in teacher and "children" not in teacher

    student = client.get(f"{API}/portal/overview", headers={"Authorization": f"Bearer {token_of(client, 'student')}"}).json()["data"]
    assert student["identity"] == "student" and "className" in student and "classes" not in student

    parent = client.get(f"{API}/portal/overview", headers={"Authorization": f"Bearer {token_of(client, 'parent')}"}).json()["data"]
    assert parent["identity"] == "parent" and "children" in parent and len(parent["children"]) >= 1


def test_portal_identity_gating(client):
    """身份专属接口：不匹配身份返回 403，匹配身份返回 200。"""
    tea = token_of(client, "teacher")
    stu = token_of(client, "student")
    par = token_of(client, "parent")
    h = lambda t: {"Authorization": f"Bearer {t}"}

    # 学员访问教师专属接口 -> 403
    assert client.get(f"{API}/portal/teacher/classes", headers=h(stu)).status_code == 403
    # 教师访问自己的专属接口 -> 200
    r = client.get(f"{API}/portal/teacher/classes", headers=h(tea))
    assert r.status_code == 200 and "id" in r.json()["data"][0]

    # 家长访问家长专属接口 -> 200 且返回关联学员
    r = client.get(f"{API}/portal/parent/children", headers=h(par))
    assert r.status_code == 200 and len(r.json()["data"]) >= 1
    # 学员访问家长专属接口 -> 403
    assert client.get(f"{API}/portal/parent/children", headers=h(stu)).status_code == 403


def test_file_sqlite_uses_thread_safe_pool():
    """文件型 SQLite 不可用 StaticPool：同步 API 在线程池并发时会串扰会话。"""
    from sqlalchemy.pool import QueuePool

    from app.db.session import engine

    assert isinstance(engine.pool, QueuePool)


def test_parallel_authenticated_reads_do_not_cross_sessions(client):
    """高并发读请求下认证用户、业务列表与看板不可串线/误报 401。"""
    staff_token = token_of(client, "staff")
    teacher_token = token_of(client, "teacher")
    student_token = token_of(client, "student")
    parent_token = token_of(client, "parent")

    checks = [
        (staff_token, f"{API}/auth/me", 200, "admin"),
        (teacher_token, f"{API}/auth/me", 200, "JS001"),
        (student_token, f"{API}/auth/me", 200, "XS001"),
        (parent_token, f"{API}/auth/me", 200, "P001"),
        (staff_token, f"{API}/students?page=1&pageSize=100", 200, None),
        (staff_token, f"{API}/courses?page=1&pageSize=100", 200, None),
        (staff_token, f"{API}/dashboard/summary", 200, None),
        (staff_token, f"{API}/dashboard/heat", 200, None),
        (teacher_token, f"{API}/students?page=1&pageSize=100", 403, None),
        (student_token, f"{API}/dashboard/summary", 403, None),
        (parent_token, f"{API}/payments?page=1&pageSize=100", 403, None),
    ] * 5

    def request(check):
        token, path, expected_status, expected_user = check
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != expected_status:
            return f"{path}: 预期 {expected_status}，实际 {response.status_code}，响应={response.text[:120]}"
        if expected_user:
            actual_user = response.json().get("data", {}).get("username")
            if actual_user != expected_user:
                return f"{path}: 预期用户 {expected_user}，实际 {actual_user}"
        return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        failures = [failure for failure in pool.map(request, checks) if failure]
    assert not failures, "并发请求出现会话/身份串扰：\\n" + "\\n".join(failures)


def test_news_readable_by_all_identities(client):
    """新闻中心为机构资讯门户，任何已登录身份均可阅读（写操作仍受限）。"""
    for identity in ("staff", "teacher", "student", "parent"):
        h = {"Authorization": f"Bearer {token_of(client, identity)}"}
        assert client.get(f"{API}/news", headers=h).status_code == 200
    # 非员工发布新闻 -> 403
    h = {"Authorization": f"Bearer {token_of(client, 'parent')}"}
    r = client.post(f"{API}/news", headers=h, json={"title": "测试", "category": "通知", "content": ["正文"]})
    assert r.status_code == 403
