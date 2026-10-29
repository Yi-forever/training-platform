"""Pydantic 请求模型：字段经 to_camel 别名与前端 camelCase 完全对齐。

- 前端可直接提交 camelCase 字段（如 parentPhone、joinDate）；
- 亦兼容 snake_case（populate_by_name）；
- extra="ignore"：忽略未声明字段，避免原型前端多传字段报错。
"""
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


# ---------- 认证 ----------

class LoginRequest(CamelModel):
    username: str
    password: str


class ChangePasswordRequest(CamelModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=32)


class ProfileUpdate(CamelModel):
    """普通用户自助维护的资料字段（auth/profile）。"""
    name: str | None = Field(default=None, min_length=1, max_length=32)
    phone: str | None = Field(default=None, min_length=5, max_length=20)
    email: str | None = None


# ---------- 用户 ----------

class UserCreate(CamelModel):
    username: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(min_length=1, max_length=32)
    role: str = "教务管理员"
    phone: str = Field(min_length=5, max_length=20)
    email: str | None = None
    join_date: str | None = None
    status: str = "启用"
    password: str | None = Field(default=None, min_length=6, max_length=32)


class UserUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    role: str | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=20)
    email: str | None = None
    join_date: str | None = None
    status: str | None = None


# ---------- 教师 ----------

class TeacherCreate(CamelModel):
    name: str = Field(min_length=1, max_length=32)
    gender: str = "男"
    phone: str = Field(min_length=5, max_length=20)
    email: str | None = None
    subject: str
    title: str | None = None
    hire_date: str | None = None
    status: str = "在职"


class TeacherUpdate(CamelModel):
    name: str | None = None
    gender: str | None = None
    phone: str | None = None
    email: str | None = None
    subject: str | None = None
    title: str | None = None
    hire_date: str | None = None
    status: str | None = None


# ---------- 课程 ----------

class CourseCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    category: str
    level: str
    hours: int = Field(gt=0, le=999)
    price: float = Field(ge=0)
    target: str | None = None
    desc: str | None = None
    teacher_id: str | None = None   # 负责 / 默认授课教师（可选）
    status: str = "在售"


class CourseUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    category: str | None = None
    level: str | None = None
    hours: int | None = Field(default=None, gt=0, le=999)
    price: float | None = Field(default=None, ge=0)
    target: str | None = None
    desc: str | None = None
    teacher_id: str | None = None
    status: str | None = None


# ---------- 教师开课申请 ----------

class CourseProposalCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    category: str
    level: str = "入门"
    hours: int = Field(gt=0, le=999)
    price: float = Field(ge=0)
    target: str | None = Field(default=None, max_length=128)
    desc: str | None = Field(default=None, max_length=2000)
    preferred_schedule: str | None = Field(default=None, max_length=128)


class CourseProposalReview(CamelModel):
    action: str = Field(pattern=r"^(approve|reject)$")
    note: str | None = Field(default=None, max_length=200)


# ---------- 班级 ----------

class ClassCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    course_id: str
    teacher_id: str
    classroom: str | None = None
    schedule: str | None = None
    capacity: int = Field(gt=0, le=999)
    start_date: str | None = None
    end_date: str | None = None
    status: str = "未开班"


class ClassUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    course_id: str | None = None
    teacher_id: str | None = None
    classroom: str | None = None
    schedule: str | None = None
    capacity: int | None = Field(default=None, gt=0, le=999)
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None


# ---------- 排课规则 / 课次 ----------

class ScheduleCreate(CamelModel):
    weekday: int = Field(ge=1, le=7)
    start_time: str = Field(min_length=4, max_length=8)
    end_time: str = Field(min_length=4, max_length=8)
    effective_from: str | None = None
    effective_to: str | None = None
    classroom: str | None = Field(default=None, max_length=32)


class ScheduleUpdate(CamelModel):
    weekday: int | None = Field(default=None, ge=1, le=7)
    start_time: str | None = Field(default=None, min_length=4, max_length=8)
    end_time: str | None = Field(default=None, min_length=4, max_length=8)
    effective_from: str | None = None
    effective_to: str | None = None
    classroom: str | None = Field(default=None, max_length=32)


class SessionReschedule(CamelModel):
    session_date: str
    start_time: str | None = None
    end_time: str | None = None
    classroom: str | None = Field(default=None, max_length=32)


class SessionGenerate(CamelModel):
    """按规则补齐课次：兼容「班级 + 起始日」与「日期区间」两种提交方式。"""
    class_id: str | None = None
    from_date: str | None = None
    date_from: str | None = Field(default=None, alias="from")
    date_to: str | None = Field(default=None, alias="to")


# ---------- 学员 ----------

class StudentCreate(CamelModel):
    name: str = Field(min_length=1, max_length=32)
    gender: str = "男"
    grade: str
    parent: str = Field(min_length=1, max_length=32)
    parent_phone: str = Field(min_length=5, max_length=20)
    class_id: str
    enroll_date: str | None = None
    status: str | None = None


class StudentUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    gender: str | None = None
    grade: str | None = None
    parent: str | None = Field(default=None, min_length=1, max_length=32)
    parent_phone: str | None = Field(default=None, min_length=5, max_length=20)
    class_id: str | None = None
    enroll_date: str | None = None
    status: str | None = None


# ---------- 缴费 ----------

class PaymentCreate(CamelModel):
    student_id: str
    class_id: str
    amount: float = Field(gt=0)
    method: str
    date: str | None = None
    status: str = "待确认"
    note: str | None = None
    bill_id: str | None = None  # 可空：按学员自动挂到最早未缴清账单


class PaymentUpdate(CamelModel):
    amount: float | None = Field(default=None, gt=0)
    method: str | None = None
    date: str | None = None
    note: str | None = None


# ---------- 新闻 ----------

class NewsCreate(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    category: str
    top: bool = False
    date: str | None = None
    author: str | None = None
    summary: str | None = None
    content: list[str] = []
    status: str = "草稿"


class NewsUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = None
    top: bool | None = None
    date: str | None = None
    author: str | None = None
    summary: str | None = None
    content: list[str] | None = None
    status: str | None = None


# ---------- 课件资源 ----------

class ResourceCreate(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    type: str
    course_id: str
    teacher_id: str
    size: str | None = None
    duration: str | None = None
    date: str | None = None
    status: str = "已发布"


class ResourceUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = None
    course_id: str | None = None
    teacher_id: str | None = None
    size: str | None = None
    duration: str | None = None
    date: str | None = None
    status: str | None = None


# ---------- 作业与考勤 ----------

class AssignmentCreate(CamelModel):
    class_id: str
    title: str = Field(min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=5000)
    due_date: str | None = None
    session_id: str | None = None
    allow_late: bool = False


class AssignmentUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=5000)
    due_date: str | None = None
    session_id: str | None = None
    allow_late: bool | None = None
    status: str | None = None


class SubmissionCreate(CamelModel):
    content: str = Field(min_length=1, max_length=5000)


class GradeRequest(CamelModel):
    score: int = Field(ge=0, le=100)
    comment: str | None = Field(default=None, max_length=500)


class ReturnRequest(CamelModel):
    reason: str = Field(min_length=2, max_length=100)


class AttendanceItem(CamelModel):
    student_id: str
    status: str = "出勤"
    note: str | None = Field(default=None, max_length=200)


class AttendanceSave(CamelModel):
    class_id: str
    date: str
    items: list[AttendanceItem] = []


# ---------- 课表 ----------

class SessionUpdate(CamelModel):
    """课次维护：主题 / 状态（调课仍走 reschedule 以保留追溯）。"""
    topic: str | None = Field(default=None, max_length=128)
    status: str | None = None
    classroom: str | None = Field(default=None, max_length=32)


# ---------- 选课 ----------

class EnrollmentApply(CamelModel):
    class_id: str
    note: str | None = Field(default=None, max_length=200)


class ParentEnrollmentApply(CamelModel):
    student_id: str
    class_id: str
    note: str | None = Field(default=None, max_length=200)


class StaffEnrollmentCreate(CamelModel):
    student_id: str
    class_id: str
    note: str | None = Field(default=None, max_length=200)


class EnrollmentReview(CamelModel):
    action: str = Field(pattern=r"^(approve|reject)$")
    note: str | None = Field(default=None, max_length=200)


# ---------- 系统设置 ----------

class SettingsUpdate(CamelModel):
    """机构信息（org）与业务设置（settings）合并提交。"""
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    intro: str | None = None
    allow_leave: bool | None = None
    schedule_remind: bool | None = None
    receipt_print: bool | None = None
    new_student_status: str | None = None

