"""角色权限矩阵回归测试（《02-总体设计》§4.3）。

覆盖需求：
- 防提权：学员 / 教师 / 家长（非 staff 身份）直接调用后台管理写接口一律 403；
- 员工内部按职务分岗：教务 / 财务 / 前台 / 教师岗仅能执行矩阵允许的写操作；
- 用户管理 / 系统设置仅超级管理员；学员/教师/家长无任何后台写权限。

运行：``uv run python -m pytest tests/test_permissions.py -q``
"""
import os
import tempfile

# 必须在导入 app 之前确定数据库位置（SQLAlchemy engine 在导入时即创建）
_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_permissions_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app

API = "/api/v1"

# 演示账号（见 app/db/seed.py / README.md）
CRED = {
    "admin": ("admin", "admin123"),     # 超级管理员
    "jiaowu": ("jiaowu", "123456"),     # 教务管理员
    "caiwu": ("caiwu", "123456"),       # 财务专员
    "qiantai": ("qiantai", "123456"),   # 前台接待
    "student": ("XS001", "123456"),     # 学员门户账号（非员工）
    "teacher": ("JS001", "123456"),     # 教师门户账号（非员工）
    "parent": ("P001", "123456"),       # 家长门户账号（非员工）
}


@pytest.fixture(scope="module")
def client():
    # 只重置表结构，不删除库文件：engine 仍持有连接与 WAL，删文件会导致后续模块 disk I/O error
    init_db()
    reset_schema()
    seed_db()
    with TestClient(app) as c:
        yield c


def token_of(client, who: str) -> str:
    u, p = CRED[who]
    r = client.post(f"{API}/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, f"登录失败: {r.text}"
    return r.json()["data"]["token"]


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def first_id(client, token: str, resource: str) -> str:
    r = client.get(f"{API}/{resource}", headers=h(token))
    assert r.status_code == 200, f"拉取 {resource} 失败"
    rows = r.json()["data"]["list"]
    assert rows, f"{resource} 无数据"
    return rows[0]["id"]


def write_probes(news_id: str, res_id: str) -> list[tuple[str, str, dict | None]]:
    """覆盖全部后台写接口（权限依赖先于参数校验执行，越权必 403 而非 422）。"""
    return [
        ("POST", "/teachers", {"name": "x", "gender": "男", "phone": "13900000001", "subject": "Python"}),
        ("PUT", "/teachers/JS001", {"phone": "13900000001"}),
        ("DELETE", "/teachers/JS003", None),
        ("POST", "/courses", {"name": "x", "category": "Scratch", "level": "入门", "hours": 8, "price": 100}),
        ("PUT", "/courses/KC001", {"price": 100}),
        ("DELETE", "/courses/KC001", None),
        ("POST", "/classes", {"name": "x", "courseId": "KC001", "teacherId": "JS001", "capacity": 10}),
        ("PUT", "/classes/BJ001", {"capacity": 10}),
        ("DELETE", "/classes/BJ001", None),
        ("POST", "/students", {"name": "x", "gender": "男", "grade": "一年级", "parent": "p", "parentPhone": "15800000001", "classId": "BJ001"}),
        ("PUT", "/students/XS001", {"grade": "一年级"}),
        ("DELETE", "/students/XS001", None),
        ("POST", "/payments", {"studentId": "XS001", "classId": "BJ001", "amount": 100, "method": "现金"}),
        ("PUT", "/payments/JF001", {"note": "x"}),
        ("DELETE", "/payments/JF001", None),
        ("POST", "/payments/JF002/confirm", None),
        ("POST", "/payments/JF001/void", None),
        ("POST", "/news", {"title": "x", "category": "机构动态", "date": "2026-09-01", "summary": "x", "content": ["x"]}),
        ("PUT", f"/news/{news_id}", {"title": "x"}),
        ("DELETE", f"/news/{news_id}", None),
        ("POST", "/resources", {"title": "x", "type": "课件PPT", "courseId": "KC001", "teacherId": "JS001"}),
        ("PUT", f"/resources/{res_id}", {"title": "x"}),
        ("DELETE", f"/resources/{res_id}", None),
        ("PUT", "/settings", {"newStudentStatus": "在读"}),
        ("POST", "/settings/reset", None),
    ]


# ---------------- 防提权：非员工身份打后台接口一律 403 ----------------

@pytest.mark.parametrize("who", ["student", "teacher", "parent"])
def test_non_staff_cannot_write_admin_apis(client, who):
    """学员 / 教师 / 家长账号直接调用全部后台写接口 -> 403（防提权核心用例）。"""
    token = token_of(client, who)
    # 新闻 / 资源读接口任何身份可读（门户可见），但写接口必须 403
    news_id = first_id(client, token, "news")
    res_id = first_id(client, token, "resources")
    for method, path, body in write_probes(news_id, res_id):
        r = client.request(method, f"{API}{path}", headers=h(token), json=body)
        assert r.status_code == 403, f"{who} {method} {path} 期望 403，实际 {r.status_code}: {r.text}"


@pytest.mark.parametrize("who, path", [
    ("student", "/students"),
    ("student", "/payments"),
    ("student", "/dashboard/summary"),
    ("student", "/users"),
    ("student", "/settings"),
    ("teacher", "/teachers"),
    ("teacher", "/classes"),
    ("parent", "/students"),
    ("parent", "/payments/stats"),
])
def test_non_staff_cannot_read_admin_apis(client, who, path):
    """后台管理数据读接口同样仅员工可见（门户数据由 /auth/context、/portal 提供）。"""
    token = token_of(client, who)
    r = client.get(f"{API}{path}", headers=h(token))
    assert r.status_code == 403, f"{who} GET {path} 期望 403，实际 {r.status_code}"


@pytest.mark.parametrize("who", ["student", "teacher", "parent"])
def test_non_staff_can_read_public_content(client, who):
    """新闻 / 资源读接口对全部登录身份开放（门户可阅内容，白名单）。"""
    token = token_of(client, who)
    assert client.get(f"{API}/news", headers=h(token)).status_code == 200
    assert client.get(f"{API}/resources", headers=h(token)).status_code == 200


# ---------------- 权限矩阵：员工内部按职务分岗 ----------------

def test_admin_full_access(client):
    """超管：全部写接口可执行（抽查各域 + 用户管理 + 系统设置）。"""
    token = token_of(client, "admin")
    r = client.post(f"{API}/teachers", headers=h(token),
                    json={"name": "矩阵超管教师", "gender": "男", "phone": "13900000090", "subject": "Web"})
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    assert client.delete(f"{API}/teachers/{tid}", headers=h(token)).status_code == 200
    assert client.get(f"{API}/users", headers=h(token)).status_code == 200
    assert client.get(f"{API}/settings", headers=h(token)).status_code == 200
    assert client.put(f"{API}/settings", headers=h(token), json={"newStudentStatus": "在读"}).status_code == 200


def test_academic_scope(client):
    """教务：教务域写 ✓（教师/新闻/资源等），缴费 ✗，用户/设置写 ✗。"""
    token = token_of(client, "jiaowu")
    r = client.post(f"{API}/teachers", headers=h(token),
                    json={"name": "矩阵教务教师", "gender": "女", "phone": "13900000091", "subject": "Python"})
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    r = client.post(f"{API}/news", headers=h(token),
                    json={"title": "教务发布", "category": "机构动态", "date": "2026-09-01", "summary": "x", "content": ["x"]})
    assert r.status_code == 200, r.text
    nid = r.json()["data"]["id"]
    r = client.post(f"{API}/resources", headers=h(token), json={"title": "教务课件", "type": "课件PPT", "courseId": "KC001", "teacherId": "JS001"})
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["id"]
    # 员工可读系统设置（机构信息展示），但写仅超管
    assert client.get(f"{API}/settings", headers=h(token)).status_code == 200
    assert client.put(f"{API}/settings", headers=h(token), json={"newStudentStatus": "在读"}).status_code == 403
    # 缴费域与用户管理拒绝
    assert client.post(f"{API}/payments", headers=h(token),
                       json={"studentId": "XS001", "classId": "BJ001", "amount": 100, "method": "现金"}).status_code == 403
    assert client.post(f"{API}/payments/JF002/confirm", headers=h(token)).status_code == 403
    assert client.get(f"{API}/users", headers=h(token)).status_code == 403
    # 清理自建数据
    client.delete(f"{API}/teachers/{tid}", headers=h(token))
    client.delete(f"{API}/news/{nid}", headers=h(token))
    client.delete(f"{API}/resources/{rid}", headers=h(token))


def test_finance_scope(client):
    """财务：缴费写 ✓（登记/确认/作废），教务域写 ✗。"""
    token = token_of(client, "caiwu")
    r = client.post(f"{API}/payments", headers=h(token),
                    json={"studentId": "XS001", "classId": "BJ001", "amount": 100, "method": "现金"})
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "待确认"
    assert client.post(f"{API}/payments/{pid}/confirm", headers=h(token)).status_code == 200
    assert client.post(f"{API}/payments/{pid}/void", headers=h(token)).status_code == 200
    # 教务域写全部拒绝
    assert client.post(f"{API}/teachers", headers=h(token),
                       json={"name": "x", "gender": "男", "phone": "13900000092", "subject": "Python"}).status_code == 403
    assert client.delete(f"{API}/teachers/JS003", headers=h(token)).status_code == 403
    assert client.post(f"{API}/courses", headers=h(token),
                       json={"name": "x", "category": "Scratch", "level": "入门", "hours": 8, "price": 100}).status_code == 403
    assert client.post(f"{API}/classes", headers=h(token),
                       json={"name": "x", "courseId": "KC001", "teacherId": "JS001", "capacity": 10}).status_code == 403
    assert client.post(f"{API}/students", headers=h(token),
                       json={"name": "x", "gender": "男", "grade": "一年级", "parent": "p", "parentPhone": "15800000002", "classId": "BJ001"}).status_code == 403
    assert client.post(f"{API}/news", headers=h(token),
                       json={"title": "x", "category": "机构动态", "date": "2026-09-01", "summary": "x", "content": ["x"]}).status_code == 403
    assert client.post(f"{API}/resources", headers=h(token), json={"title": "x", "type": "课件PPT", "courseId": "KC001"}).status_code == 403


def test_frontdesk_scope(client):
    """前台：学员报名写 ✓（含修改/删除），课程/教师/缴费/新闻写 ✗。"""
    token = token_of(client, "qiantai")
    r = client.post(f"{API}/students", headers=h(token),
                    json={"name": "前台报名学员", "gender": "女", "grade": "二年级", "parent": "前台家长", "parentPhone": "15800000009", "classId": "BJ001"})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    assert client.put(f"{API}/students/{sid}", headers=h(token), json={"grade": "三年级"}).status_code == 200
    assert client.delete(f"{API}/students/{sid}", headers=h(token)).status_code == 200
    # 其他域写拒绝
    assert client.post(f"{API}/payments", headers=h(token),
                       json={"studentId": "XS001", "classId": "BJ001", "amount": 100, "method": "现金"}).status_code == 403
    assert client.post(f"{API}/payments/JF002/confirm", headers=h(token)).status_code == 403
    assert client.post(f"{API}/courses", headers=h(token),
                       json={"name": "x", "category": "Scratch", "level": "入门", "hours": 8, "price": 100}).status_code == 403
    assert client.post(f"{API}/teachers", headers=h(token),
                       json={"name": "x", "gender": "男", "phone": "13900000093", "subject": "Python"}).status_code == 403
    assert client.post(f"{API}/news", headers=h(token),
                       json={"title": "x", "category": "机构动态", "date": "2026-09-01", "summary": "x", "content": ["x"]}).status_code == 403


def test_staff_teacher_role_scope(client):
    """staff 教师岗（wangzq）：课件资源上传 ✓，教务 / 财务 / 新闻写 ✗。

    种子中 wangzq 为禁用的教师岗演示账号（identity=staff，role=教师），
    由管理员临时启用测试，结束恢复禁用。
    """
    admin = token_of(client, "admin")
    assert client.put(f"{API}/users/wangzq", headers=h(admin), json={"status": "启用"}).status_code == 200
    r = client.post(f"{API}/auth/login", json={"username": "wangzq", "password": "123456"})
    assert r.status_code == 200, r.text
    wz = r.json()["data"]["token"]
    # 资源上传放行（矩阵：教师 ✅ 上传课件）
    r = client.post(f"{API}/resources", headers=h(wz), json={"title": "教师岗课件", "type": "课件PPT", "courseId": "KC001", "teacherId": "JS001"})
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["id"]
    # 其余域写拒绝
    assert client.post(f"{API}/students", headers=h(wz),
                       json={"name": "x", "gender": "男", "grade": "一年级", "parent": "p", "parentPhone": "15800000003", "classId": "BJ001"}).status_code == 403
    assert client.post(f"{API}/payments", headers=h(wz),
                       json={"studentId": "XS001", "classId": "BJ001", "amount": 100, "method": "现金"}).status_code == 403
    assert client.post(f"{API}/news", headers=h(wz),
                       json={"title": "x", "category": "机构动态", "date": "2026-09-01", "summary": "x", "content": ["x"]}).status_code == 403
    assert client.post(f"{API}/teachers", headers=h(wz),
                       json={"name": "x", "gender": "男", "phone": "13900000094", "subject": "Python"}).status_code == 403
    assert client.get(f"{API}/users", headers=h(wz)).status_code == 403
    # 清理并恢复种子状态
    client.delete(f"{API}/resources/{rid}", headers=h(wz))
    client.put(f"{API}/users/wangzq", headers=h(admin), json={"status": "禁用"})
