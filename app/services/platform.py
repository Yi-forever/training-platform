"""工作台聚合统计 / 系统设置。"""
from datetime import datetime
from typing import Any

from app.core.config import NEW_STUDENT_STATUS_OPTIONS
from app.core.exceptions import BizException
from app.db.repository import db


class DashboardService:
    def summary(self) -> dict:
        students = db.alive("students")
        teachers = db.alive("teachers")
        classes = db.alive("classes")
        payments = db.alive("payments")
        paid = [p for p in payments if p.get("status") == "已支付"]
        pending = [p for p in payments if p.get("status") == "待确认"]
        month_prefix = datetime.now().strftime("%Y-%m")

        def _sum(items: list[dict]) -> float:
            return round(sum(float(p.get("amount") or 0) for p in items), 2)

        return {
            "students": {
                "total": len(students),
                "active": sum(1 for s in students if s.get("status") == "在读"),
            },
            "teachers": {
                "total": len(teachers),
                "active": sum(1 for t in teachers if t.get("status") == "在职"),
            },
            "classes": {
                "total": len(classes),
                "running": sum(1 for c in classes if c.get("status") == "进行中"),
                "notStarted": sum(1 for c in classes if c.get("status") == "未开班"),
            },
            "income": {
                "month": _sum([p for p in paid if str(p.get("date") or "").startswith(month_prefix)]),
                "total": _sum(paid),
                "pending": _sum(pending),
                "pendingCount": len(pending),
            },
        }

    def heat(self, limit: int = 5) -> list[dict]:
        """班级报名热度：进行中的班级按报名人数降序。"""
        rows = []
        for c in db.alive("classes"):
            if c.get("status") != "进行中":
                continue
            enrolled = sum(1 for s in db.alive("students") if s.get("classId") == c["id"])
            course = db.find("courses", c.get("courseId") or "")
            rows.append({
                "id": c["id"],
                "name": c["name"],
                "courseName": course["name"] if course else "",
                "enrolled": enrolled,
                "capacity": int(c.get("capacity") or 0),
            })
        rows.sort(key=lambda r: -r["enrolled"])
        return rows[:limit]

    def recent_classes(self, limit: int = 4) -> list[dict]:
        """即将开课 / 进行中的班级：非已结课，按开班日期升序。"""
        rows = [c for c in db.alive("classes") if c.get("status") != "已结课"]
        rows.sort(key=lambda c: str(c.get("startDate") or ""))
        result = []
        for c in rows[:limit]:
            course = db.find("courses", c.get("courseId") or "")
            teacher = db.find("teachers", c.get("teacherId") or "")
            enrolled = sum(1 for s in db.alive("students") if s.get("classId") == c["id"])
            result.append({
                "id": c["id"],
                "name": c["name"],
                "courseName": course["name"] if course else "",
                "teacherName": teacher["name"] if teacher else "",
                "startDate": c.get("startDate") or "",
                "endDate": c.get("endDate") or "",
                "schedule": c.get("schedule") or "",
                "classroom": c.get("classroom") or "",
                "capacity": int(c.get("capacity") or 0),
                "enrolled": enrolled,
                "status": c.get("status") or "",
            })
        return result

    def recent_payments(self, limit: int = 6) -> list[dict]:
        """最新缴费动态：按缴费日期倒序。"""
        rows = sorted(db.alive("payments"), key=lambda p: str(p.get("date") or ""), reverse=True)
        result = []
        for p in rows[:limit]:
            student = db.find("students", p.get("studentId") or "")
            cls = db.find("classes", p.get("classId") or "")
            course = db.find("courses", cls.get("courseId") or "") if cls else None
            result.append({
                "id": p["id"],
                "studentName": student["name"] if student else "",
                "className": cls["name"] if cls else "",
                "courseName": course["name"] if course else "",
                "amount": p.get("amount") or 0,
                "method": p.get("method") or "",
                "date": p.get("date") or "",
                "status": p.get("status") or "",
            })
        return result


class SettingsService:
    _ORG_KEYS = ("name", "phone", "address", "intro")
    _SETTINGS_KEYS = ("allowLeave", "scheduleRemind", "receiptPrint", "newStudentStatus")

    def get(self) -> dict:
        return {"org": db.org, "settings": db.settings}

    def update(self, data: dict[str, Any]) -> dict:
        org_patch = {k: data[k] for k in self._ORG_KEYS if data.get(k) is not None}
        settings_patch = {k: data[k] for k in self._SETTINGS_KEYS if data.get(k) is not None}
        if "newStudentStatus" in settings_patch and settings_patch["newStudentStatus"] not in NEW_STUDENT_STATUS_OPTIONS:
            raise BizException(400, "新学员默认状态仅支持：在读 / 休学")
        return db.save_settings(org_patch, settings_patch)

    def reset(self) -> dict:
        """一键重置演示数据（仅管理员入口调用）：全部集合回到种子状态。"""
        data = db.reset()
        # 种子只包含班级排课规则，课次需按规则重新展开
        from app.services.schedule import ScheduleService
        ScheduleService().ensure_all()
        return {"org": data["org"], "settings": data["settings"]}
