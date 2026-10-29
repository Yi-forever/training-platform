"""课程负责人与教师开课申请回归测试。

覆盖：
- 课程可指定 / 更换 / 清空授课教师，离职教师不能担任负责人；
- 教师提交开课申请（待审核）、同名重复提交 409；
- 学员 / 家长 / 前台不能访问审核接口，教师不能直接建课；
- 教务审核通过后自动创建课程（负责人 = 申请教师），申请状态与 courseId 回写；
- 驳回带审核意见，已审核申请不可重复审核；
- 教师可撤回本人待审核申请，不能撤回他人或已通过的申请。
"""
import os
import tempfile

_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_identities_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app

API = "/api/v1"

CRED = {
    "admin": ("admin", "admin123"),
    "academic": ("jiaowu", "123456"),
    "frontdesk": ("qiantai", "123456"),
    "teacher": ("JS005", "123456"),      # 孙浩然，Web / 机器人
    "teacher2": ("JS001", "123456"),     # 王志强
    "teacher3": ("JS006", "123456"),     # 周美琳，机器人
    "student": ("XS005", "123456"),
    "parent": ("P005", "123456"),
}


@pytest.fixture(scope="module")
def client():
    init_db()
    reset_schema()
    seed_db()
    with TestClient(app) as c:
        yield c


def headers(client, who):
    username, password = CRED[who]
    r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


# ---------------- 课程负责人 ----------------

def test_course_can_assign_teacher(client):
    admin = headers(client, "admin")
    r = client.post(f"{API}/courses", headers=admin, json={
        "name": "测试课程·负责人", "category": "Python", "level": "入门",
        "hours": 20, "price": 2000, "teacherId": "JS001",
    })
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["teacherId"] == "JS001"
    assert body["teacherName"] == "王志强"

    # 列表与详情都带出教师姓名
    rows = client.get(f"{API}/courses", headers=admin, params={"pageSize": 100}).json()["data"]["list"]
    row = next(c for c in rows if c["id"] == body["id"])
    assert row["teacherName"] == "王志强"

    # 更换负责人
    r = client.put(f"{API}/courses/{body['id']}", headers=admin, json={"teacherId": "JS002"})
    assert r.status_code == 200 and r.json()["data"]["teacherName"] == "林晓芸"

    # 清空负责人
    r = client.put(f"{API}/courses/{body['id']}", headers=admin, json={"teacherId": None})
    assert r.status_code == 200
    assert r.json()["data"]["teacherId"] is None


def test_resigned_teacher_cannot_own_course(client):
    r = client.post(f"{API}/courses", headers=headers(client, "admin"), json={
        "name": "离职教师课程", "category": "Python", "level": "入门",
        "hours": 20, "price": 2000, "teacherId": "JS007",
    })
    assert r.status_code == 409
    assert "已离职" in r.json()["message"]


def test_teacher_cannot_create_course_directly(client):
    r = client.post(f"{API}/courses", headers=headers(client, "teacher"), json={
        "name": "教师越权建课", "category": "Web", "level": "入门", "hours": 10, "price": 1000,
    })
    assert r.status_code == 403


# ---------------- 教师提交申请 ----------------

def test_teacher_submit_proposal(client):
    h = headers(client, "teacher")
    payload = {
        "name": "Python 数据分析实战", "category": "Python", "level": "进阶",
        "hours": 40, "price": 4600, "target": "学完 Python 入门",
        "preferredSchedule": "周日 09:00-12:00", "desc": "pandas 与可视化",
    }
    r = client.post(f"{API}/portal/teacher/course-proposals", headers=h, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "待审核"
    assert body["teacherName"] == "孙浩然"
    assert body["preferredSchedule"] == "周日 09:00-12:00"

    # 同名待审核申请不可重复提交
    r = client.post(f"{API}/portal/teacher/course-proposals", headers=h, json=payload)
    assert r.status_code == 409

    mine = client.get(f"{API}/portal/teacher/course-proposals", headers=h).json()["data"]
    assert any(p["id"] == body["id"] for p in mine)


def test_proposal_identity_guards(client):
    for who in ("student", "parent"):
        h = headers(client, who)
        assert client.get(f"{API}/portal/teacher/course-proposals", headers=h).status_code == 403
        assert client.post(f"{API}/portal/teacher/course-proposals", headers=h, json={
            "name": "越权申请", "category": "Python", "hours": 10, "price": 100,
        }).status_code == 403

    # 教师不能查看 / 审核全部申请
    assert client.get(f"{API}/course-proposals", headers=headers(client, "teacher")).status_code == 403

    # 前台、财务没有审核权限
    for who in ("frontdesk",):
        assert client.get(f"{API}/course-proposals", headers=headers(client, who)).status_code == 403


# ---------------- 审核 ----------------

def test_approve_creates_course(client):
    teacher_h = headers(client, "teacher")
    mine = client.get(f"{API}/portal/teacher/course-proposals", headers=teacher_h).json()["data"]
    target = next(p for p in mine if p["status"] == "待审核" and p["name"] == "Python 数据分析实战")

    r = client.post(
        f"{API}/course-proposals/{target['id']}/review",
        headers=headers(client, "academic"),
        json={"action": "approve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "已通过"
    assert body["courseId"]

    course = client.get(f"{API}/courses/{body['courseId']}", headers=headers(client, "admin")).json()["data"]
    assert course["name"] == "Python 数据分析实战"
    assert course["teacherId"] == "JS005"
    assert course["status"] == "在售"
    assert course["price"] == 4600

    # 已审核不可重复审核
    r = client.post(
        f"{API}/course-proposals/{target['id']}/review",
        headers=headers(client, "academic"),
        json={"action": "reject", "note": "重复"},
    )
    assert r.status_code == 409


def test_reject_with_note(client):
    r = client.post(
        f"{API}/course-proposals/KK001/review",
        headers=headers(client, "academic"),
        json={"action": "reject", "note": "本学期课时已排满"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "已驳回"
    assert r.json()["data"]["reviewNote"] == "本学期课时已排满"

    mine = client.get(f"{API}/portal/teacher/course-proposals", headers=headers(client, "teacher")).json()["data"]
    row = next(p for p in mine if p["id"] == "KK001")
    assert row["status"] == "已驳回" and row["reviewNote"] == "本学期课时已排满"


# ---------------- 撤回 ----------------

def test_teacher_can_cancel_pending_only(client):
    h = headers(client, "teacher3")
    r = client.post(f"{API}/portal/teacher/course-proposals", headers=h, json={
        "name": "机器人临时课", "category": "机器人", "level": "入门", "hours": 10, "price": 1200,
    })
    assert r.status_code == 200
    code = r.json()["data"]["id"]

    # 他人不能撤回
    assert client.delete(
        f"{API}/portal/teacher/course-proposals/{code}", headers=headers(client, "teacher")
    ).status_code == 403

    assert client.delete(f"{API}/portal/teacher/course-proposals/{code}", headers=h).status_code == 200
    # 已撤回不可重复撤回
    assert client.delete(f"{API}/portal/teacher/course-proposals/{code}", headers=h).status_code == 409

    # 已通过的申请不可撤回
    approved = next(
        p for p in client.get(f"{API}/portal/teacher/course-proposals", headers=headers(client, "teacher")).json()["data"]
        if p["status"] == "已通过"
    )
    assert client.delete(
        f"{API}/portal/teacher/course-proposals/{approved['id']}", headers=headers(client, "teacher")
    ).status_code == 409


def test_proposal_stats(client):
    stats = client.get(f"{API}/course-proposals/stats", headers=headers(client, "admin")).json()["data"]
    assert stats["total"] >= 4
    assert stats["approved"] >= 1
    assert stats["rejected"] >= 2
    assert stats["withdrawn"] >= 1
    assert stats["pending"] >= 1
