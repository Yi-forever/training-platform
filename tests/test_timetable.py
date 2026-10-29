"""课表（课次）与考勤联动回归测试（合并远端课表能力后）。

覆盖：
- 排课文本解析（单/多星期、时间归一化、无法识别）；
- 员工跨班级周课表与班级 / 教师筛选；
- 员工维护课次主题 / 状态（教师无权改他人课次）；
- 教师课表按本人班级隔离，学员 / 家长按归属隔离（越权 403）；
- 考勤保存后对应课次标记为已上课，并可按月统计出勤率；
- 修改班级「上课时间」文本后，未来课次按新规则重建。
"""
import os
import tempfile
from datetime import date, timedelta

# 与其它测试模块共用同一隔离库（pytest 收集时首个模块决定 engine），fixture 会重置并播种
_DB_FILE = os.path.join(tempfile.gettempdir(), "qihang_identities_test.db")
os.environ["QIHANG_DB_URL"] = f"sqlite:///{_DB_FILE}"

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed_db
from app.db.session import init_db, reset_schema
from app.main import app
from app.services.scheduling import parse_schedule_text

API = "/api/v1"

CRED = {
    "admin": ("admin", "admin123"),
    "teacher": ("JS001", "123456"),    # 王志强，BJ002 / BJ003
    "student": ("XS005", "123456"),    # 李思远，BJ002
    "parent": ("P005", "123456"),      # 李国豪，关联 XS005
}


@pytest.fixture(scope="module")
def client():

    # 只重置表结构，不删除库文件：engine 仍持有连接与 WAL，删文件会导致后续模块 disk I/O error

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
    assert parse_schedule_text("周六 09:00-10:30") == [
        {"weekday": 6, "startTime": "09:00", "endTime": "10:30"}
    ]
    multi = parse_schedule_text("周一/三/五 09:00-12:00")
    assert [item["weekday"] for item in multi] == [1, 3, 5]
    assert parse_schedule_text("周日 9:00-10:00")[0]["startTime"] == "09:00"
    assert parse_schedule_text("时间待定") == []
    assert parse_schedule_text(None) == []


# ---------------- 员工课表与筛选 ----------------

def test_staff_sessions_and_filters(client):
    h = headers(client, "admin")
    rows = client.get(
        f"{API}/sessions?start=2026-09-01&end=2026-09-30&classId=BJ001", headers=h
    ).json()["data"]
    assert rows, "开班后应按排课规则生成课次"
    assert all(r["classId"] == "BJ001" for r in rows)
    assert all(date.fromisoformat(r["date"]).weekday() == 5 for r in rows)  # 周六
    assert all(r["startTime"] == "09:00" and r["endTime"] == "10:30" for r in rows)
    assert all(r["teacherId"] == "JS002" and r["classroom"] == "A101" for r in rows)
    assert rows[0]["date"] == "2026-09-05"
    assert rows[0]["date"] == rows[0]["sessionDate"]

    by_teacher = client.get(
        f"{API}/sessions?start=2026-09-01&end=2026-12-31&teacherId=JS001", headers=h
    ).json()["data"]
    assert by_teacher and all(r["teacherId"] == "JS001" for r in by_teacher)
    by_class = client.get(
        f"{API}/sessions?start=2026-09-01&end=2026-12-31&classId=BJ003", headers=h
    ).json()["data"]
    assert by_class and all(r["classId"] == "BJ003" for r in by_class)


def test_staff_can_update_session_topic_and_status(client):
    admin = headers(client, "admin")
    rows = client.get(
        f"{API}/sessions?start=2026-09-01&end=2026-09-30&classId=BJ001", headers=admin
    ).json()["data"]
    target = rows[0]

    r = client.put(f"{API}/sessions/{target['id']}", headers=admin,
                   json={"topic": "第 1 讲 环境与变量", "status": "已完成"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["topic"] == "第 1 讲 环境与变量"
    assert r.json()["data"]["status"] == "已上课"      # 兼容「已完成」旧叫法

    # 日期 / 时间不在课次维护接口内（调课走 reschedule）
    assert client.put(f"{API}/sessions/{target['id']}", headers=admin,
                      json={"date": "2027-01-01"}).status_code == 400
    assert client.put(f"{API}/sessions/{target['id']}", headers=admin,
                      json={"status": "旷课"}).status_code == 400


# ---------------- 角色可见性与教师课表 ----------------

def test_teacher_sessions_scoped(client):
    teacher = headers(client, "teacher")
    rows = client.get(
        f"{API}/portal/teacher/sessions?start=2026-09-01&end=2026-12-31", headers=teacher
    ).json()["data"]
    assert rows and all(s["teacherId"] == "JS001" for s in rows)
    assert {s["classId"] for s in rows} <= {"BJ002", "BJ003"}

    # 教师可维护本人班级课次的主题
    target = rows[0]
    updated = client.put(f"{API}/portal/teacher/sessions/{target['id']}", headers=teacher,
                         json={"topic": "教师维护的主题"})
    assert updated.status_code == 200
    assert updated.json()["data"]["topic"] == "教师维护的主题"

    assert client.get(
        f"{API}/portal/teacher/sessions?classId=BJ001", headers=teacher
    ).status_code == 403
    assert client.get(f"{API}/sessions", headers=teacher).status_code == 403
    assert client.put(
        f"{API}/sessions/{rows[0]['id']}", headers=teacher, json={"topic": "越权"}
    ).status_code == 403

    # 不能改其他教师班级的课次
    admin = headers(client, "admin")
    other = client.get(
        f"{API}/sessions?start=2026-09-01&end=2026-09-30&classId=BJ001", headers=admin
    ).json()["data"][0]
    assert client.put(f"{API}/portal/teacher/sessions/{other['id']}", headers=teacher,
                      json={"topic": "越权"}).status_code == 403


def test_student_and_parent_session_scope(client):
    student = headers(client, "student")
    parent = headers(client, "parent")

    stu = client.get(f"{API}/portal/student/timetable", headers=student).json()["data"]
    assert stu["sessions"] and all(s["classId"] == "BJ002" for s in stu["sessions"])

    par = client.get(f"{API}/portal/parent/XS005/timetable", headers=parent).json()["data"]
    assert par["sessions"] and all(s["classId"] == "BJ002" for s in par["sessions"])
    assert client.get(f"{API}/portal/parent/XS006/timetable", headers=parent).status_code == 403


# ---------------- 考勤联动与统计 ----------------

def test_attendance_marks_session_completed_and_summary(client):
    teacher = headers(client, "teacher")
    admin = headers(client, "admin")
    future = (date.today() + timedelta(days=7)).isoformat()
    rows = client.get(
        f"{API}/portal/teacher/sessions?start={future}"
        f"&end={(date.today() + timedelta(days=60)).isoformat()}", headers=teacher,
    ).json()["data"]
    target = next(s for s in rows if s["classId"] == "BJ002")

    roster = client.get(
        f"{API}/portal/teacher/attendance?classId=BJ002&date={target['date']}", headers=teacher
    ).json()["data"]
    items = [{"studentId": r["studentId"], "status": "出勤", "note": ""} for r in roster["rows"]]
    r = client.post(f"{API}/portal/teacher/attendance", headers=teacher,
                    json={"classId": "BJ002", "date": target["date"], "items": items})
    assert r.status_code == 200

    after = client.get(
        f"{API}/sessions?start={target['date']}&end={target['date']}&classId=BJ002", headers=admin
    ).json()["data"]
    hit = [s for s in after if s["id"] == target["id"]][0]
    assert hit["status"] == "已上课"
    assert hit["attendanceSaved"] is True
    assert hit["attendance"]["出勤"] == len(items)

    month = target["date"][:7]
    summary = client.get(
        f"{API}/portal/teacher/attendance/summary?classId=BJ002&month={month}", headers=teacher
    ).json()["data"]
    assert summary["totals"]["total"] >= len(items)
    assert summary["totals"]["rate"] == 100
    assert len(summary["students"]) == 4


# ---------------- 排课文本变更与异常 ----------------

def test_schedule_text_change_rebuilds_future_sessions(client):
    admin = headers(client, "admin")
    created = client.post(f"{API}/classes", headers=admin, json={
        "name": "课表重建测试班", "courseId": "KC002", "teacherId": "JS001",
        "classroom": "B203", "capacity": 10, "schedule": "周日 09:00-12:00",
        "startDate": "2027-03-01", "endDate": "2027-03-31", "status": "未开班",
    })
    assert created.status_code == 200, created.text
    cid = created.json()["data"]["id"]

    rows = client.get(
        f"{API}/classes/{cid}/sessions?from=2027-03-01&to=2027-03-31", headers=admin
    ).json()["data"]
    assert rows and all(date.fromisoformat(s["sessionDate"]).weekday() == 6 for s in rows)  # 周日
    assert len(rows) == 4

    updated = client.put(f"{API}/classes/{cid}", headers=admin, json={"schedule": "周六 09:00-12:00"})
    assert updated.status_code == 200, updated.text
    rows = client.get(
        f"{API}/classes/{cid}/sessions?from=2027-03-01&to=2027-03-31", headers=admin
    ).json()["data"]
    assert rows and all(date.fromisoformat(s["sessionDate"]).weekday() == 5 for s in rows)  # 周六
    assert len(rows) == 4


def test_unparseable_schedule_generates_no_sessions(client):
    admin = headers(client, "admin")
    created = client.post(f"{API}/classes", headers=admin, json={
        "name": "无固定时间班", "courseId": "KC002", "teacherId": "JS001",
        "classroom": "B203", "capacity": 10, "schedule": "时间待定",
        "startDate": "2027-04-01", "endDate": "2027-04-30", "status": "未开班",
    })
    assert created.status_code == 200
    cid = created.json()["data"]["id"]
    assert client.get(f"{API}/classes/{cid}/schedules", headers=admin).json()["data"] == []
    r = client.post(f"{API}/classes/{cid}/sessions/generate", headers=admin, json={})
    assert r.status_code == 200 and r.json()["data"]["created"] == 0
