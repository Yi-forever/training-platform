"""课表（课次）与考勤联动回归测试。

覆盖：
- 排课文本解析（单/多星期、时间归一化、无法识别）；
- 开班后按规则自动生成课次，员工可按班级/教师/日期筛选；
- 教师只能看到并调整自己班级的课次；
- 学员只看本班课表，家长只看关联学员课表（越权 403）；
- 考勤保存后对应课次标记为已完成，并可按月统计出勤率；
- 修改班级排课规则后，未来课次按新规则重建。
"""
import os
import tempfile
from datetime import date

# 与其它测试模块共用同一隔离库（pytest 收集时首个模块决定 engine），fixture 会重置并播种
_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_identities_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app
from app.services.schedule import parse_schedule

API = "/api/v1"

CRED = {
    "admin": ("admin", "admin123"),
    "teacher": ("JS001", "123456"),    # 王志强，BJ002 / BJ003
    "student": ("XS005", "123456"),    # 李思远，BJ002
    "parent": ("P005", "123456"),      # 李国豪，关联 XS005
}


@pytest.fixture(scope="module")
def client():
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)
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


# ---------------- 排课解析 ----------------

def test_parse_schedule_variants():
    assert parse_schedule("周六 09:00-10:30") == {"weekdays": [5], "startTime": "09:00", "endTime": "10:30"}
    multi = parse_schedule("周一/三/五 09:00-12:00")
    assert multi["weekdays"] == [0, 2, 4] and multi["startTime"] == "09:00"
    assert parse_schedule("周日 9:00-10:00")["startTime"] == "09:00"
    assert parse_schedule("周六 13:30 至 17:30") is None or parse_schedule("周六 13:30 至 17:30")["weekdays"] == [5]
    assert parse_schedule("时间待定") is None
    assert parse_schedule(None) is None


# ---------------- 自动生成与筛选 ----------------

def test_sessions_generated_from_class_rule(client):
    h = headers(client, "admin")
    rows = client.get(f"{API}/sessions?start=2026-09-01&end=2026-09-30&classId=BJ001", headers=h).json()["data"]
    assert rows, "开班后应按排课规则生成课次"
    assert all(date.fromisoformat(s["date"]).weekday() == 5 for s in rows)   # 周六
    assert all(s["startTime"] == "09:00" and s["endTime"] == "10:30" for s in rows)
    assert all(s["teacherId"] == "JS002" and s["classroom"] == "A101" for s in rows)
    assert rows[0]["date"] == "2026-09-05"


def test_staff_can_filter_by_teacher_and_class(client):
    h = headers(client, "admin")
    by_teacher = client.get(f"{API}/sessions?start=2026-09-01&end=2026-12-31&teacherId=JS001", headers=h).json()["data"]
    assert by_teacher and all(s["teacherId"] == "JS001" for s in by_teacher)
    by_class = client.get(f"{API}/sessions?start=2026-09-01&end=2026-12-31&classId=BJ003", headers=h).json()["data"]
    assert by_class and all(s["classId"] == "BJ003" for s in by_class)


# ---------------- 角色可见性与课次编辑 ----------------

def test_teacher_sessions_scoped_and_editable(client):
    teacher = headers(client, "teacher")
    rows = client.get(f"{API}/portal/teacher/sessions?start=2026-09-01&end=2026-12-31", headers=teacher).json()["data"]
    assert rows and all(s["teacherId"] == "JS001" for s in rows)

    target = rows[0]
    r = client.put(f"{API}/portal/teacher/sessions/{target['id']}", headers=teacher,
                   json={"topic": "第 1 讲 环境与变量", "status": "待上课"})
    assert r.status_code == 200 and r.json()["data"]["topic"] == "第 1 讲 环境与变量"

    # 教师不能改日期（字段被过滤后无内容）
    r = client.put(f"{API}/portal/teacher/sessions/{target['id']}", headers=teacher, json={"date": "2027-01-01"})
    assert r.status_code == 400

    # 不能调整其他教师的课次
    admin = headers(client, "admin")
    other = client.get(f"{API}/sessions?start=2026-09-01&end=2026-09-30&classId=BJ001", headers=admin).json()["data"][0]
    assert client.put(f"{API}/portal/teacher/sessions/{other['id']}", headers=teacher,
                      json={"topic": "越权"}).status_code == 403


def test_student_and_parent_session_scope(client):
    student = headers(client, "student")
    parent = headers(client, "parent")

    stu_rows = client.get(f"{API}/portal/student/sessions", headers=student).json()["data"]
    assert stu_rows and all(s["classId"] == "BJ002" for s in stu_rows)

    par_rows = client.get(f"{API}/portal/parent/sessions", headers=parent).json()["data"]
    assert par_rows and all(s["studentId"] == "XS005" for s in par_rows)

    assert client.get(f"{API}/portal/parent/sessions?studentId=XS006", headers=parent).status_code == 403
    assert client.get(f"{API}/sessions", headers=student).status_code == 403


# ---------------- 考勤联动与统计 ----------------

def test_attendance_marks_session_completed_and_summary(client):
    teacher = headers(client, "teacher")
    rows = client.get(f"{API}/portal/teacher/sessions?start=2026-09-01&end=2026-12-31", headers=teacher).json()["data"]
    target = [s for s in rows if s["classId"] == "BJ002" and s["date"] >= "2026-11-01"][0]

    roster = client.get(f"{API}/portal/teacher/attendance?classId=BJ002&date={target['date']}", headers=teacher).json()["data"]
    items = [{"studentId": r["studentId"], "status": "出勤", "note": ""} for r in roster["rows"]]
    r = client.post(f"{API}/portal/teacher/attendance", headers=teacher,
                    json={"classId": "BJ002", "date": target["date"], "items": items})
    assert r.status_code == 200

    after = client.get(f"{API}/portal/teacher/sessions?start={target['date']}&end={target['date']}",
                       headers=teacher).json()["data"]
    assert after[0]["status"] == "已完成" and after[0]["attendanceSaved"] is True

    month = target["date"][:7]
    summary = client.get(f"{API}/portal/teacher/attendance/summary?classId=BJ002&month={month}",
                         headers=teacher).json()["data"]
    assert summary["totals"]["total"] >= 4 and summary["totals"]["rate"] == 100
    assert len(summary["students"]) == 4


# ---------------- 排课变更与异常 ----------------

def test_schedule_change_rebuilds_future_sessions(client):
    admin = headers(client, "admin")
    created = client.post(f"{API}/classes", headers=admin, json={
        "name": "课表重建测试班", "courseId": "KC002", "teacherId": "JS001",
        "classroom": "B203", "capacity": 10, "schedule": "周日 09:00-12:00",
        "startDate": "2027-03-01", "endDate": "2027-03-31", "status": "未开班",
    })
    assert created.status_code == 200, created.text
    cid = created.json()["data"]["id"]
    rows = client.get(f"{API}/sessions?start=2027-03-01&end=2027-03-31&classId={cid}", headers=admin).json()["data"]
    assert rows and all(date.fromisoformat(s["date"]).weekday() == 6 for s in rows)   # 周日

    updated = client.put(f"{API}/classes/{cid}", headers=admin, json={"schedule": "周六 09:00-12:00"})
    assert updated.status_code == 200
    rows = client.get(f"{API}/sessions?start=2027-03-01&end=2027-03-31&classId={cid}", headers=admin).json()["data"]
    assert rows and all(date.fromisoformat(s["date"]).weekday() == 5 for s in rows)   # 改为周六


def test_generate_rejects_unparseable_schedule(client):
    admin = headers(client, "admin")
    created = client.post(f"{API}/classes", headers=admin, json={
        "name": "无固定时间班", "courseId": "KC002", "teacherId": "JS001",
        "classroom": "B203", "capacity": 10, "schedule": "时间待定",
        "startDate": "2027-04-01", "endDate": "2027-04-30", "status": "未开班",
    })
    assert created.status_code == 200
    cid = created.json()["data"]["id"]
    r = client.post(f"{API}/sessions/generate", headers=admin, json={"classId": cid})
    assert r.status_code == 400
