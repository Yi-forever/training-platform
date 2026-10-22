"""ORM 模型：账户（四类身份）+ 八类业务实体 + 家长-学员关系 + 系统配置。

设计要点：
- 列名与旧版 JSON 存储的字典键保持一致（如 courseId / parentPhone / startDate），
  repository 层据此零成本在「数据库行 ↔ 业务字典」间互转，service 层无需改动；
- 仅 ``accounts`` / ``student_parents`` / ``config`` 为数据库原生关系结构，
  清晰承载「四类登录身份」与「家长-学员」关联，体现真实的库表建模；
- 所有业务表统一带 ``deletedAt`` 软删除列；
- 日期类字段以字符串（YYYY-MM-DD）存储，与既有服务层字符串比较逻辑一致。
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.db.session import Base


class Config(Base):
    """系统配置键值表（机构信息 org + 业务开关 settings）。"""
    __tablename__ = "config"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)  # JSON 字符串


class Account(Base):
    """统一登录账户表：承载 staff / teacher / student / parent 四类身份。

    - identity 区分身份；role 为展示角色（员工为职务，其余为「教师/学员/家长」）；
    - refId 指向业务档案编号（教师 JSxxx / 学员 XSxxx / 家长 Pxxx），员工为 NULL；
    - username 全局唯一，可作登录名；phone 支持家长用手机号登录。
    """
    __tablename__ = "accounts"
    username = Column(String(64), primary_key=True)
    passwordHash = Column(String(200), nullable=False)
    name = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    identity = Column(String(16), nullable=False)
    status = Column(String(8), nullable=False, default="启用")
    phone = Column(String(32), nullable=False, default="")
    email = Column(String(128), nullable=True)
    joinDate = Column(String(32), nullable=True)
    refId = Column(String(32), nullable=True)
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)
    # 注：手机号不强制唯一（员工与对应教师可能共用同一号码）；
    # 手机号登录在 repository.find_account 中优先匹配家长身份。


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(String(16), primary_key=True)  # 工号 JS001
    name = Column(String(64), nullable=False)
    gender = Column(String(2), nullable=False, default="女")
    phone = Column(String(32), nullable=False, default="")
    email = Column(String(128), nullable=True)
    subject = Column(String(32), nullable=False)
    title = Column(String(32), nullable=False, default="讲师")
    hireDate = Column(String(32), nullable=True)
    status = Column(String(8), nullable=False, default="在职")
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Course(Base):
    __tablename__ = "courses"
    id = Column(String(16), primary_key=True)  # 课程编号 KC001
    name = Column(String(128), nullable=False)
    category = Column(String(32), nullable=False)
    level = Column(String(16), nullable=False, default="入门")
    hours = Column(Integer, nullable=False)
    price = Column(Numeric(12, 2), nullable=False, default=0)
    target = Column(String(128), nullable=True)
    desc = Column(Text, nullable=True)
    status = Column(String(8), nullable=False, default="在售")
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Class(Base):
    __tablename__ = "classes"
    id = Column(String(16), primary_key=True)  # 班级编号 BJ001
    name = Column(String(128), nullable=False)
    courseId = Column(String(16), nullable=False)
    teacherId = Column(String(16), nullable=False)
    classroom = Column(String(32), nullable=True)
    capacity = Column(Integer, nullable=False)
    schedule = Column(String(128), nullable=True)
    startDate = Column(String(32), nullable=True)
    endDate = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="未开班")
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Student(Base):
    __tablename__ = "students"
    id = Column(String(16), primary_key=True)  # 学号 XS001
    name = Column(String(64), nullable=False)
    gender = Column(String(2), nullable=False, default="女")
    grade = Column(String(16), nullable=False)
    parent = Column(String(64), nullable=False)
    parentPhone = Column(String(32), nullable=False, default="")
    classId = Column(String(16), nullable=False)
    enrollDate = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="在读")
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(String(16), primary_key=True)  # 流水号 JF001
    studentId = Column(String(16), nullable=False)
    classId = Column(String(16), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    method = Column(String(16), nullable=False, default="微信")
    date = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="待确认")
    note = Column(String(256), nullable=True)
    billId = Column(String(16), nullable=True)  # 关联应收账单（空 = 历史流水 / 教材费等非学费流水）
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Bill(Base):
    """应收账单：家长端「应缴 / 已缴 / 欠费」的口径来源。

    - 报名时按课程价自动生成（``BillService.create_for_student``）；
    - 实收金额不落库，由 ``payments.billId`` 关联的「已支付」流水实时汇总，
      避免账单与流水两套金额互相漂移；
    - ``status`` 仅存「待缴 / 已作废」，部分缴 / 已缴 / 已逾期均为读取时派生。
    """
    __tablename__ = "bills"
    id = Column(String(16), primary_key=True)  # 账单编号 ZD001
    studentId = Column(String(16), nullable=False)
    classId = Column(String(16), nullable=False)
    courseId = Column(String(16), nullable=False)
    period = Column(String(16), nullable=False, default="")   # 账期 YYYY-MM
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(16), nullable=False, default="待缴")  # 待缴 / 已作废
    dueDate = Column(String(32), nullable=True)                 # 到期日 YYYY-MM-DD
    note = Column(String(256), nullable=True)
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class News(Base):
    __tablename__ = "news"
    id = Column(String(16), primary_key=True)  # 编号 XW001
    title = Column(String(128), nullable=False)
    category = Column(String(32), nullable=False)
    top = Column(Boolean, nullable=False, default=False)
    date = Column(String(32), nullable=True)
    author = Column(String(64), nullable=False, default="")
    views = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="草稿")
    summary = Column(String(256), nullable=True)
    content = Column(Text, nullable=True)  # JSON 数组字符串
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Resource(Base):
    __tablename__ = "resources"
    id = Column(String(16), primary_key=True)  # 编号 ZY001
    title = Column(String(128), nullable=False)
    type = Column(String(16), nullable=False, default="课件PPT")
    courseId = Column(String(16), nullable=False)
    teacherId = Column(String(16), nullable=False)
    size = Column(String(32), nullable=True)
    duration = Column(String(32), nullable=True)
    downloads = Column(Integer, nullable=False, default=0)
    date = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="已发布")
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class StudentParent(Base):
    """家长-学员关联（一个家长可关联多名学员）。"""
    __tablename__ = "student_parents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    parentCode = Column(String(32), nullable=False, index=True)
    studentCode = Column(String(16), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("parentCode", "studentCode", name="uk_parent_student"),
    )


class Assignment(Base):
    """作业：教师面向某个班级布置，学生提交后由教师批改。"""
    __tablename__ = "assignments"
    id = Column(String(16), primary_key=True)  # 作业编号 HW001
    classId = Column(String(16), nullable=False, index=True)
    teacherId = Column(String(16), nullable=False, index=True)
    title = Column(String(128), nullable=False)
    content = Column(Text, nullable=True)
    dueDate = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="进行中")  # 进行中 / 已结束
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)


class Submission(Base):
    """作业提交与批改：一份作业每个学员至多一条提交记录（可修改后重新提交）。"""
    __tablename__ = "submissions"
    id = Column(String(16), primary_key=True)  # 提交编号 TJ001
    assignmentId = Column(String(16), nullable=False, index=True)
    studentId = Column(String(16), nullable=False, index=True)
    content = Column(Text, nullable=True)
    submittedAt = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="已提交")  # 已提交 / 已批改
    score = Column(Integer, nullable=True)       # 0-100
    comment = Column(Text, nullable=True)
    gradedAt = Column(String(32), nullable=True)
    gradedBy = Column(String(32), nullable=True)
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)
    __table_args__ = (
        UniqueConstraint("assignmentId", "studentId", name="uk_submission_assignment_student"),
    )


class Attendance(Base):
    """考勤：教师按「班级 + 日期 + 学员」记录到班情况。"""
    __tablename__ = "attendance"
    id = Column(String(16), primary_key=True)  # 考勤编号 KQ001
    classId = Column(String(16), nullable=False, index=True)
    studentId = Column(String(16), nullable=False, index=True)
    date = Column(String(32), nullable=False, index=True)
    status = Column(String(8), nullable=False, default="出勤")  # 出勤/迟到/请假/缺勤
    note = Column(String(256), nullable=True)
    teacherId = Column(String(16), nullable=False)
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)
    __table_args__ = (
        UniqueConstraint("classId", "studentId", "date", name="uk_attendance_class_student_date"),
    )


class ClassSession(Base):
    """课次（课表条目）：由班级的周排课规则自动生成，也可单独调整。"""
    __tablename__ = "class_sessions"
    id = Column(String(16), primary_key=True)  # 课次编号 SK001
    classId = Column(String(16), nullable=False, index=True)
    teacherId = Column(String(16), nullable=False, index=True)
    date = Column(String(32), nullable=False, index=True)
    startTime = Column(String(8), nullable=False)   # HH:MM
    endTime = Column(String(8), nullable=False)     # HH:MM
    classroom = Column(String(32), nullable=True)
    topic = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False, default="待上课")  # 待上课/已完成/已取消
    createdAt = Column(String(32), nullable=True)
    updatedAt = Column(String(32), nullable=True)
    deletedAt = Column(String(32), nullable=True)
    __table_args__ = (
        UniqueConstraint("classId", "date", "startTime", name="uk_session_class_date_start"),
    )
