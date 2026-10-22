"""数据库仓储层：对外暴露与旧版 JsonDB 完全一致的接口。

service / api 层无需任何改动即可从「JSON 文件」平滑切换到「关系数据库」：

- ``alive / find / locate / insert / update_fields / soft_delete / next_code``
- ``org / settings / save_settings / reset / transaction``
- 新增：``find_account``（按用户名或手机号解析四类身份）、
  ``soft_delete_student_cascade``（学员删除级联软删其缴费）、
  ``list_children_of`` / ``student_of`` 等身份关联查询。

行 ↔ 字典互转规则见 ``_read`` / ``_write``：列名即字典键，
仅 ``news.top/content`` 与 ``payments.amount`` 做类型转换。
"""
import copy
import json
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import select

from app.core.exceptions import BizException
from app.db.models import (
    Account,
    Assignment,
    Attendance,
    Bill,
    Class,
    ClassSession,
    Config,
    Course,
    News,
    Payment,
    Resource,
    Student,
    StudentParent,
    Submission,
    Teacher,
)
from app.db.session import Base, SessionLocal, engine

# 集合名 -> ORM 模型
MODELS: dict[str, type] = {
    "users": Account,        # 登录账户集合（四类身份统一存放）
    "teachers": Teacher,
    "courses": Course,
    "classes": Class,
    "students": Student,
    "payments": Payment,
    "bills": Bill,           # 应收账单（缴费详情口径）
    "news": News,
    "resources": Resource,
    "assignments": Assignment,
    "submissions": Submission,
    "attendance": Attendance,
    "sessions": ClassSession,
}
PK_OF = {name: ("username" if name == "users" else "id") for name in MODELS}

# 仅整型/布尔/JSON 等需要类型转换的字段：(read, write)
_TRANSFORMS: dict[str, dict[str, tuple[Any, Any]]] = {
    "news": {
        "top": (lambda v: bool(v), lambda v: 1 if v else 0),
        "content": (lambda v: json.loads(v) if v else [], lambda v: json.dumps(v or [])),
    },
    "payments": {
        "amount": (lambda v: float(v) if v is not None else 0.0, lambda v: float(v) if v is not None else 0.0),
    },
    "bills": {
        "amount": (lambda v: float(v) if v is not None else 0.0, lambda v: float(v) if v is not None else 0.0),
    },
}


def _read(coll: str, name: str, val: Any) -> Any:
    tf = _TRANSFORMS.get(coll, {}).get(name)
    return tf[0](val) if tf else val


def _write(coll: str, name: str, val: Any) -> Any:
    tf = _TRANSFORMS.get(coll, {}).get(name)
    return tf[1](val) if tf else val


def _row_to_dict(coll: str, obj: Any) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for col in obj.__table__.columns:
        name = col.name
        if name == "deletedAt":
            continue
        d[name] = _read(coll, name, getattr(obj, name))
    return d


def _cols_of(coll: str) -> set[str]:
    return {c.name for c in MODELS[coll].__table__.columns}


class DB:
    # ---------- 查询 ----------

    def alive(self, coll: str) -> list[dict[str, Any]]:
        """未删除记录（业务可见数据）。"""
        Model = MODELS[coll]
        with SessionLocal() as s:
            rows = s.scalars(select(Model).where(Model.deletedAt.is_(None))).all()
            return [_row_to_dict(coll, r) for r in rows]

    def raw(self, coll: str) -> list[dict[str, Any]]:
        """含软删记录（取号时用于避免编号复用）。"""
        Model = MODELS[coll]
        with SessionLocal() as s:
            rows = s.scalars(select(Model)).all()
            return [_row_to_dict(coll, r) for r in rows]

    def find(self, coll: str, code: str) -> dict[str, Any] | None:
        return self._get(coll, code)

    def find_one(self, coll: str, **filters: Any) -> dict[str, Any] | None:
        """按任意字段组合查找单条未删除记录（小数据量，走 ORM 过滤即可）。"""
        if not filters:
            return None
        for row in self.alive(coll):
            if all(str(row.get(key)) == str(value) for key, value in filters.items()):
                return row
        return None

    def locate(self, coll: str, code: str, *, label: str = "记录") -> dict[str, Any]:
        rec = self._get(coll, code)
        if rec is None:
            raise BizException(404, f"{label}不存在或已被删除")
        return rec

    def _get(self, coll: str, code: str) -> dict[str, Any] | None:
        """按主键取单条未删除记录（会话内即转为字典，避免使用分离实例）。"""
        Model = MODELS[coll]
        pk = PK_OF[coll]
        with SessionLocal() as s:
            stmt = select(Model).where(getattr(Model, pk) == code)
            # 软删除列存在时，默认只返回未删除记录（与 JSON 版 locate 行为一致）
            if hasattr(Model, "deletedAt"):
                stmt = stmt.where(Model.deletedAt.is_(None))
            rec = s.scalars(stmt).first()
            return _row_to_dict(coll, rec) if rec is not None else None

    # ---------- 单条写入 ----------

    def insert(self, coll: str, record: dict[str, Any]) -> dict[str, Any]:
        Model = MODELS[coll]
        cols = _cols_of(coll)
        data = {k: _write(coll, k, v) for k, v in record.items() if k in cols and k != "deletedAt"}
        with SessionLocal() as s:
            obj = Model(**data)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return _row_to_dict(coll, obj)

    def update_fields(
        self, coll: str, code: str, fields: dict[str, Any], *, label: str = "记录"
    ) -> dict[str, Any]:
        Model = MODELS[coll]
        cols = _cols_of(coll)
        with SessionLocal() as s:
            obj = s.get(Model, code)
            if obj is None or getattr(obj, "deletedAt") is not None:
                raise BizException(404, f"{label}不存在或已被删除")
            for k, v in fields.items():
                if k in cols:
                    setattr(obj, k, _write(coll, k, v))
            s.commit()
            s.refresh(obj)
            return _row_to_dict(coll, obj)

    def soft_delete(self, coll: str, code: str, *, label: str = "记录") -> dict[str, Any]:
        from app.core.config import now_iso

        return self.update_fields(coll, code, {"deletedAt": now_iso()}, label=label)

    def next_code(self, coll: str, prefix: str) -> str:
        """生成下一个业务编号：prefix + 三位递增数字（扫描含软删记录防复用）。"""
        Model = MODELS[coll]
        pk = PK_OF[coll]
        with SessionLocal() as s:
            rows = s.scalars(select(getattr(Model, pk))).all()
        best = 0
        for code in rows:
            code = str(code)
            tail = code[len(prefix):]
            if code.startswith(prefix) and tail.isdigit():
                best = max(best, int(tail))
        return f"{prefix}{best + 1:03d}"

    # ---------- 账户 / 身份 ----------

    def find_account(self, login_id: str) -> dict[str, Any] | None:
        """按用户名或手机号解析登录账户（支持家长用手机号登录）。

        手机号登录优先匹配家长身份，避免与员工/学员共用号码时误判。
        """
        login_id = (login_id or "").strip()
        with SessionLocal() as s:
            acc = s.get(Account, login_id)
            if acc is not None and acc.deletedAt is None:
                return _row_to_dict("users", acc)
            # 手机号登录：优先家长，其次任意匹配
            parent = s.scalars(
                select(Account).where(
                    Account.phone == login_id,
                    Account.identity == "parent",
                    Account.deletedAt.is_(None),
                )
            ).first()
            if parent is not None:
                return _row_to_dict("users", parent)
            acc = s.scalars(
                select(Account).where(Account.phone == login_id, Account.deletedAt.is_(None))
            ).first()
            return _row_to_dict("users", acc) if acc is not None else None

    def soft_delete_student_cascade(self, code: str) -> None:
        """删除学员并级联软删其全部缴费 / 账单记录（同一数据库事务内完成）。"""
        from app.core.config import now_iso
        from sqlalchemy import update as _sa_update

        ts = now_iso()
        with SessionLocal() as s:
            stu = s.get(Student, code)
            if stu is None or stu.deletedAt is not None:
                raise BizException(404, "学员不存在或已被删除")
            stu.deletedAt = ts
            # 批量软删该学员的全部缴费记录与应收账单（避免逐条 ORM 迭代的刷写边界问题）
            for Model in (Payment, Bill):
                s.execute(
                    _sa_update(Model)
                    .where(Model.studentId == code, Model.deletedAt.is_(None))
                    .values(deletedAt=ts)
                )
            s.commit()

    def list_children_of(self, parent_code: str) -> list[dict[str, Any]]:
        """某家长关联的全部学员档案。"""
        with SessionLocal() as s:
            links = s.scalars(
                select(StudentParent.studentCode).where(StudentParent.parentCode == parent_code)
            ).all()
            codes = set(links)
            rows = s.scalars(select(Student).where(Student.deletedAt.is_(None))).all()
            return [_row_to_dict("students", r) for r in rows if r.id in codes]

    def classes_of_teacher(self, teacher_code: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.scalars(
                select(Class).where(Class.teacherId == teacher_code, Class.deletedAt.is_(None))
            ).all()
            return [_row_to_dict("classes", r) for r in rows]

    # ---------- 顶层配置 ----------

    @property
    def org(self) -> dict[str, Any]:
        return self._config_get("org", {})

    @property
    def settings(self) -> dict[str, Any]:
        return self._config_get("settings", {})

    def _config_get(self, key: str, default: Any) -> Any:
        with SessionLocal() as s:
            row = s.get(Config, key)
            if row is None:
                return copy.deepcopy(default)
            return json.loads(row.value)

    def save_settings(self, org_patch: dict[str, Any], settings_patch: dict[str, Any]) -> dict[str, Any]:
        with SessionLocal() as s:
            org_row = s.get(Config, "org")
            settings_row = s.get(Config, "settings")
            org = json.loads(org_row.value) if org_row else {}
            settings = json.loads(settings_row.value) if settings_row else {}
            org.update(org_patch)
            settings.update(settings_patch)
            if org_row is None:
                s.add(Config(key="org", value=json.dumps(org, ensure_ascii=False)))
            else:
                org_row.value = json.dumps(org, ensure_ascii=False)
            if settings_row is None:
                s.add(Config(key="settings", value=json.dumps(settings, ensure_ascii=False)))
            else:
                settings_row.value = json.dumps(settings, ensure_ascii=False)
            s.commit()
        return {"org": self.org, "settings": self.settings}

    # ---------- 生命周期 ----------

    def load(self) -> dict[str, Any]:
        """兼容接口：组装旧版 JSON 全量结构（测试/迁移偶尔用到）。"""
        data = {coll: self.alive(coll) for coll in MODELS}
        data["org"] = self.org
        data["settings"] = self.settings
        return data

    def reset(self) -> dict[str, Any]:
        """清空并重置为种子数据（对应前端「重置演示数据」入口）。"""
        from app.db.session import reset_schema
        from app.db.seed import seed_db

        reset_schema()
        seed_db()
        return {"org": self.org, "settings": self.settings}

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """会话级事务上下文（写操作后提交，异常回滚）。"""
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# 全局单例（与旧版 jsondb.db 同名，service 层仅改 import 即可）
db = DB()
