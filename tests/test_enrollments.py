"""选课系统回归测试（学员 / 家长 / 员工三类身份）。

覆盖：
- 可选班级目录：排除已结课班级，返回剩余名额与本人选课状态；
- 学员申请：重复申请 409、与已选班级时间冲突 409、名额已满进入候补；
- 员工审核：通过后同步班级归属并生成该班账单；驳回带审核意见，学员可重新申请；
- 退课：释放名额，候补按顺位自动转正；
- 家长只能为关联学员选课；学员不能审核或退他人的选课；教师不能调用学员选课接口；
- 员工代报名校验名额，统计接口返回各状态数量。
"""
import os
import tempfile

# 与其余测试共用同一隔离库；本模块 fixture 会重置并播种
_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_identities_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app
from app.services.schedule import ScheduleService

API = "/api/v1"

CRED = {
    "admin": ("admin", "admin123"),
    "student": ("XS009", "123456"),     # 周子墨，BJ003（周五 18:30-21:00）
    "student2": ("XS001", "123456"),    # 陈一诺，BJ001（周六 09:00-10:30）
    "student3": ("XS012", "123456"),    # 孙铭泽，BJ004（周六 13:30-17:30）
    "student4": ("XS006", "123456"),    # 王雨欣，BJ002（周日 09:00-12:00）
    "student5": ("XS005", "123456"),    # 李思远，BJ002 + 待审核的 BJ001 申请
    "parent": ("P005", "123456"),       # 李国豪，关联 XS005
    "teacher": ("JS001", "123456"),
}


@pytest.fixture(scope="module")
def client():
    init_db()
    reset_schema()
    seed_db()
    ScheduleService().ensure_all()
    with TestClient(app) as c:
        yield c


def token(client, who):
    username, password = CRED[who]
    r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def headers(client, who):
    return {"Authorization": f"Bearer {token(client, who)}"}


def make_class(client, admin_h, *, name, course, teacher, schedule, capacity, start):
    r = client.post(f"{API}/classes", headers=admin_h, json={
        "name": name, "courseId": course, "teacherId": teacher,
        "schedule": schedule, "capacity": capacity, "startDate": start,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


# ---------------- 目录 ----------------

def test_catalog_excludes_finished_classes(client):
    r = client.get(f"{API}/enrollments/catalog", headers=headers(client, "student"))
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows, "目录不应为空"
    assert all(row["classStatus"] != "已结课" for row in rows)
    assert all(row["remaining"] >= 0 for row in rows)
    # 学员已选 / 已申请的班级带出本人状态
    mine = {row["classId"]: row for row in rows}
    assert mine["BJ003"]["myStatus"] == "已通过"
    assert mine["BJ002"]["myStatus"] == ""
    assert mine["BJ002"]["canApply"] is True

    rows5 = client.get(f"{API}/enrollments/catalog", headers=headers(client, "student5")).json()["data"]
    mine5 = {row["classId"]: row for row in rows5}
    assert mine5["BJ001"]["myStatus"] == "待审核"
    assert mine5["BJ001"]["canApply"] is False


# ---------------- 申请 ----------------

def test_student_apply_and_duplicate(client):
    h = headers(client, "student")
    r = client.post(f"{API}/portal/student/enrollments", headers=h, json={"classId": "BJ005"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "待审核"

    r = client.post(f"{API}/portal/student/enrollments", headers=h, json={"classId": "BJ005"})
    assert r.status_code == 409
    assert "无需重复提交" in r.json()["message"]


def test_time_conflict_blocked(client):
    admin_h = headers(client, "admin")
    class_id = make_class(
        client, admin_h, name="时间冲突测试班", course="KC001", teacher="JS002",
        schedule="周六 09:30-11:00", capacity=10, start="2026-11-07",
    )
    r = client.post(
        f"{API}/portal/student/enrollments",
        headers=headers(client, "student2"),
        json={"classId": class_id},
    )
    assert r.status_code == 409
    assert "时间冲突" in r.json()["message"]


def test_full_class_goes_waitlist(client):
    admin_h = headers(client, "admin")
    class_id = make_class(
        client, admin_h, name="候补测试班", course="KC005", teacher="JS004",
        schedule="周日 15:00-17:00", capacity=1, start="2026-11-08",
    )
    # 员工先占满唯一名额
    r = client.post(f"{API}/enrollments", headers=admin_h, json={"studentId": "XS010", "classId": class_id})
    assert r.status_code == 200, r.text

    # 名额已满：直接报名 409，学员申请进入候补
    r = client.post(f"{API}/enrollments", headers=admin_h, json={"studentId": "XS013", "classId": class_id})
    assert r.status_code == 409
    assert "名额已满" in r.json()["message"]

    r = client.post(
        f"{API}/portal/student/enrollments",
        headers=headers(client, "student3"),
        json={"classId": class_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "候补"
    assert body["waitlistNo"] == 1


# ---------------- 审核 ----------------

def test_staff_approve_syncs_class_and_bill(client):
    admin_h = headers(client, "admin")
    student_h = headers(client, "student")

    pending = client.get(
        f"{API}/enrollments", headers=admin_h, params={"status": "待审核", "pageSize": 100}
    ).json()["data"]["list"]
    target = next(e for e in pending if e["studentId"] == "XS009" and e["classId"] == "BJ005")

    r = client.post(f"{API}/enrollments/{target['id']}/review", headers=admin_h, json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "已通过"

    ctx = client.get(f"{API}/auth/context", headers=student_h).json()["data"]
    assert "AI 启蒙 · 周六班" in ctx["classNames"]
    assert ctx["className"] == "Python 入门 · 周五晚班"   # 主班保持不变（兼报）

    bills = client.get(f"{API}/portal/student/payments", headers=student_h).json()["data"]["bills"]
    assert any(b["className"] == "AI 启蒙 · 周六班" and b["amount"] == 3200 for b in bills)

    # 已通过的记录不能重复审核
    r = client.post(f"{API}/enrollments/{target['id']}/review", headers=admin_h, json={"action": "approve"})
    assert r.status_code == 409


def test_reject_then_reapply(client):
    admin_h = headers(client, "admin")
    student_h = headers(client, "student4")

    pending = client.get(
        f"{API}/enrollments", headers=admin_h, params={"status": "待审核", "pageSize": 100}
    ).json()["data"]["list"]
    target = next(e for e in pending if e["studentId"] == "XS006")

    r = client.post(
        f"{API}/enrollments/{target['id']}/review",
        headers=admin_h,
        json={"action": "reject", "note": "请先完成 Python 入门课程"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "已驳回"
    assert "Python 入门" in r.json()["data"]["reviewNote"]

    # 驳回后可重新申请，复用同一条记录
    r = client.post(f"{API}/portal/student/enrollments", headers=student_h, json={"classId": target["classId"]})
    assert r.status_code == 200
    assert r.json()["data"]["id"] == target["id"]
    assert r.json()["data"]["status"] == "待审核"
    assert r.json()["data"]["reviewNote"] is None


# ---------------- 退课与候补顺延 ----------------

def test_withdraw_releases_seat_and_promotes_waitlist(client):
    admin_h = headers(client, "admin")
    classes = client.get(f"{API}/classes", headers=admin_h, params={"pageSize": 100}).json()["data"]["list"]
    waitlist_class = next(c for c in classes if c["name"] == "候补测试班")

    all_rows = client.get(f"{API}/enrollments", headers=admin_h, params={"pageSize": 100}).json()["data"]["list"]
    seat = next(
        e for e in all_rows
        if e["classId"] == waitlist_class["id"] and e["status"] == "已通过"
    )

    r = client.delete(f"{API}/enrollments/{seat['id']}", headers=admin_h)
    assert r.status_code == 200, r.text
    promoted = r.json()["data"]["promoted"]
    assert promoted and promoted["studentName"] == "孙铭泽"
    assert promoted["status"] == "已通过"

    mine = client.get(f"{API}/portal/student/enrollments", headers=headers(client, "student3")).json()["data"]
    row = next(e for e in mine if e["classId"] == waitlist_class["id"])
    assert row["status"] == "已通过"
    assert row["waitlistNo"] is None


# ---------------- 家长 ----------------

def test_parent_can_apply_for_child(client):
    parent_h = headers(client, "parent")
    r = client.post(
        f"{API}/portal/parent/enrollments", headers=parent_h,
        json={"studentId": "XS005", "classId": "BJ004"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["source"] == "家长"

    rows = client.get(f"{API}/portal/parent/enrollments", headers=parent_h).json()["data"]
    assert any(e["classId"] == "BJ004" and e["status"] == "待审核" for e in rows)


def test_parent_cannot_apply_for_others(client):
    r = client.post(
        f"{API}/portal/parent/enrollments", headers=headers(client, "parent"),
        json={"studentId": "XS006", "classId": "BJ005"},
    )
    assert r.status_code == 403


def test_parent_catalog_scoped_to_child(client):
    parent_h = headers(client, "parent")
    assert client.get(
        f"{API}/enrollments/catalog", headers=parent_h, params={"studentId": "XS005"}
    ).status_code == 200
    assert client.get(
        f"{API}/enrollments/catalog", headers=parent_h, params={"studentId": "XS006"}
    ).status_code == 403


# ---------------- 权限 ----------------

def test_identity_guards(client):
    student_h = headers(client, "student")
    assert client.get(f"{API}/enrollments", headers=student_h).status_code == 403
    assert client.get(f"{API}/portal/student/enrollments", headers=headers(client, "teacher")).status_code == 403

    # 学员不能审核、不能退他人的选课
    assert client.post(
        f"{API}/enrollments/XK001/review", headers=student_h, json={"action": "approve"}
    ).status_code == 403
    assert client.delete(f"{API}/enrollments/XK001", headers=student_h).status_code == 403

    # 员工接口仅超管 / 教务 / 前台
    assert client.get(f"{API}/enrollments", headers=headers(client, "teacher")).status_code == 403


# ---------------- 统计 ----------------

def test_stats_reflect_records(client):
    r = client.get(f"{API}/enrollments/stats", headers=headers(client, "admin"))
    assert r.status_code == 200
    stats = r.json()["data"]
    assert stats["total"] >= 16
    assert stats["approved"] >= 16
    assert stats["pending"] >= 1
    assert stats["classCount"] >= 6
