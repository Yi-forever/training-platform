"""认证 / 用户 / 教师 / 身份门户 业务规则。"""
from typing import Any

from app.core.config import DEFAULT_USER_PASSWORD, IDENTITY_STAFF, now_iso
from app.core.exceptions import BizException
from app.core.security import create_token, hash_password, verify_password
from app.db.repository import db
from app.core.config import ROLE_ADMIN
from app.services.base import CrudService, today
from app.services.schedule import ScheduleService
from app.services.teaching import TeachingStatsService


def public_user(user: dict) -> dict:
    """用户安全视图：剔除密码哈希与软删标记（任何响应不得泄漏）。"""
    return {k: v for k, v in user.items() if k not in ("passwordHash", "deletedAt")}


class AuthService:
    def login(self, login_id: str, password: str) -> dict:
        """四类身份统一登录：支持用户名或手机号（家长）登录。"""
        user = db.find_account(login_id)
        if user is None or not verify_password(password or "", user.get("passwordHash", "")):
            raise BizException(401, "账号或密码错误")
        if user.get("status") != "启用":
            raise BizException(403, "账号已被禁用，请联系管理员")
        return {"token": create_token(user["username"]), "user": public_user(user)}

    def change_password(self, user: dict, old_password: str, new_password: str) -> None:
        if not verify_password(old_password, user.get("passwordHash", "")):
            raise BizException(400, "原密码不正确")
        db.update_fields(
            "users", user["username"],
            {"passwordHash": hash_password(new_password), "updatedAt": now_iso()},
            label="用户",
        )

    def update_profile(self, user: dict, patch: dict) -> dict:
        """普通用户自助维护姓名 / 手机 / 邮箱（不能改角色与状态）。"""
        fields = {k: v for k, v in patch.items() if v is not None}
        if not fields:
            raise BizException(400, "没有需要更新的内容")
        fields["updatedAt"] = now_iso()
        rec = db.update_fields("users", user["username"], fields, label="用户")
        return public_user(rec)


class AccountContextService:
    """按登录身份返回专属工作台数据，清晰区分 staff / teacher / student / parent。"""

    def build(self, user: dict) -> dict[str, Any]:
        identity = user.get("identity", IDENTITY_STAFF)
        base = {
            "identity": identity,
            "role": user.get("role"),
            "name": user.get("name"),
            "username": user.get("username"),
        }
        if identity == "teacher":
            return {**base, **self._teacher(user)}
        if identity == "student":
            return {**base, **self._student(user)}
        if identity == "parent":
            return {**base, **self._parent(user)}
        return base

    def _teacher(self, user: dict) -> dict[str, Any]:
        code = user.get("refId")
        classes = db.classes_of_teacher(code or "")
        enriched = []
        total_students = 0
        for c in classes:
            students = [s for s in db.alive("students") if s.get("classId") == c["id"]]
            course = db.find("courses", c.get("courseId") or "")
            enriched.append({
                "id": c["id"], "name": c["name"],
                "courseName": course["name"] if course else "",
                "schedule": c.get("schedule"), "status": c.get("status"),
                "enrolled": len(students),
            })
            total_students += len(students)
        return {"teacherId": code, "classes": enriched, "classCount": len(enriched),
                "studentCount": total_students, **TeachingStatsService().teacher(code or ""),
                "nextSession": ScheduleService().next_session([c["id"] for c in classes])}

    def _student(self, user: dict) -> dict[str, Any]:
        code = user.get("refId")
        stu = db.find("students", code or "")
        if not stu:
            return {"studentId": code}
        cls = db.find("classes", stu.get("classId") or "")
        course = db.find("courses", cls.get("courseId") or "") if cls else None
        teacher = db.find("teachers", cls.get("teacherId") or "") if cls else None
        payments = [p for p in db.alive("payments") if p.get("studentId") == code]
        paid = sum(float(p.get("amount") or 0) for p in payments if p.get("status") == "已支付")
        return {
            "studentId": code, "studentName": stu.get("name"),
            "grade": stu.get("grade"), "status": stu.get("status"),
            "className": cls["name"] if cls else "",
            "courseName": course["name"] if course else "",
            "teacherName": teacher["name"] if teacher else "",
            "schedule": cls.get("schedule") if cls else "",
            "paidTotal": round(paid, 2), "paymentCount": len(payments),
            **TeachingStatsService().student(code or ""),
            "nextSession": ScheduleService().next_session([stu.get("classId") or ""]),
        }

    def _parent(self, user: dict) -> dict[str, Any]:
        code = user.get("refId")
        children = db.list_children_of(code or "")
        enriched = []
        for stu in children:
            cls = db.find("classes", stu.get("classId") or "")
            course = db.find("courses", cls.get("courseId") or "") if cls else None
            teacher = db.find("teachers", cls.get("teacherId") or "") if cls else None
            enriched.append({
                "studentId": stu["id"], "name": stu.get("name"),
                "grade": stu.get("grade"), "status": stu.get("status"),
                "className": cls["name"] if cls else "",
                "courseName": course["name"] if course else "",
                "teacherName": teacher["name"] if teacher else "",
            })
        return {"parentCode": code, "children": enriched, "childCount": len(enriched),
                "nextSession": ScheduleService().next_session([c["classId"] for c in children if c.get("classId")])}


class UserService(CrudService):
    coll = "users"
    label = "用户"
    search_fields = ("username", "name", "phone", "email")

    def list(self, *, role: str | None = None, **kwargs) -> dict:
        # 用户管理仅面向后台员工账号（教师 / 学员 / 家长门户账号不在此列）
        return super().list(extra_filters={"role": role, "identity": IDENTITY_STAFF}, **kwargs)

    def create(self, data: dict[str, Any]) -> dict:
        username = (data.get("username") or "").strip()
        if db.find("users", username):
            raise BizException(409, f"用户名「{username}」已存在")
        ts = now_iso()
        record = {
            "username": username,
            "passwordHash": hash_password(data.get("password") or DEFAULT_USER_PASSWORD),
            "name": data.get("name") or username,
            "role": data.get("role") or "教务管理员",
            "identity": IDENTITY_STAFF,
            "status": data.get("status") or "启用",
            "phone": data.get("phone") or "",
            "email": data.get("email") or None,
            "joinDate": data.get("joinDate") or today(),
            "refId": None,
            "createdAt": ts,
            "updatedAt": ts,
        }
        db.insert("users", record)
        return public_user(record)

    def update(self, code: str, data: dict[str, Any], *, current: dict | None = None) -> dict:
        target = db.locate("users", code, label="用户")
        fields = {k: v for k, v in data.items() if v is not None}
        if current and target["username"] == current.get("username") and fields.get("status") == "禁用":
            raise BizException(409, "不能禁用当前登录的账号")
        self._guard_admin_supply(target, fields)
        rec = super().update(code, fields)
        return public_user(rec)

    def delete(self, code: str, *, current: dict | None = None) -> None:
        target = db.locate("users", code, label="用户")
        if current and target["username"] == current.get("username"):
            raise BizException(409, "不能删除当前登录的账号")
        self._guard_admin_supply(target, {"status": "禁用"})
        db.soft_delete("users", code, label="用户")

    def reset_password(self, code: str) -> str:
        db.locate("users", code, label="用户")
        db.update_fields(
            "users", code,
            {"passwordHash": hash_password(DEFAULT_USER_PASSWORD), "updatedAt": now_iso()},
            label="用户",
        )
        return DEFAULT_USER_PASSWORD

    def _guard_admin_supply(self, target: dict, changes: dict) -> None:
        """删除 / 禁用 / 降级前，保证系统仍至少保留一个启用的超级管理员。"""
        if target.get("role") != ROLE_ADMIN or target.get("status") != "启用":
            return
        losing = changes.get("status") == "禁用" or (
            changes.get("role") is not None and changes["role"] != ROLE_ADMIN
        )
        if losing:
            admins = [u for u in db.alive("users")
                      if u.get("role") == ROLE_ADMIN and u.get("status") == "启用"
                      and u.get("identity") == IDENTITY_STAFF]
            if len(admins) <= 1:
                raise BizException(409, "系统至少需保留一个启用的超级管理员")


class TeacherService(CrudService):
    coll = "teachers"
    prefix = "JS"
    label = "教师"
    search_fields = ("id", "name", "phone", "email", "subject", "title")

    def list(self, *, subject: str | None = None, **kwargs) -> dict:
        return super().list(extra_filters={"subject": subject} if subject else None, **kwargs)

    def _before_delete(self, code: str) -> None:
        used = [c for c in db.alive("classes") if c.get("teacherId") == code]
        if used:
            names = "、".join(c["name"] for c in used[:3]) + ("等" if len(used) > 3 else "")
            raise BizException(409, f"该教师仍负责 {len(used)} 个班级（{names}），请先调整班级任教教师")
