"""种子数据：与前端原型 DEFAULT_DB 完全一致（2026 秋季学期背景）。

在数据库版中：
- 业务实体（教师/课程/班级/学员/缴费/新闻/资源）按原结构入库；
- 登录账户统一写入 ``accounts`` 表，并区分四类身份：
  * staff   —— 5 个后台员工（含被禁用的 wangzq，用于演示禁用拦截）；
  * teacher —— 每个教师一个门户账号（用户名=工号 JSxxx，初始密码 123456）；
  * student —— 每个学员一个门户账号（用户名=学号 XSxxx）；
  * parent  —— 由学员的「家长 + 家长电话」去重生成，建立 student_parents 关联。
密码统一经 PBKDF2 哈希落库，绝不存明文。
"""
from typing import Any
from datetime import date, timedelta

from app.core.config import DEFAULT_USER_PASSWORD, now_iso
from app.core.security import hash_password
from app.db.models import (
    Account,
    Assignment,
    Attendance,
    Bill,
    Class,
    ClassSchedule,
    ClassSession,
    Config,
    Course,
    CourseProposal,
    Enrollment,
    News,
    Payment,
    Resource,
    Student,
    StudentParent,
    Submission,
    Teacher,
)
from app.db.session import SessionLocal
from app.services.scheduling import expand_dates, parse_date, parse_schedule_text, session_status

import json as _json

_ORG: dict[str, Any] = {
    "name": "启航编程教育",
    "phone": "0571-88886666",
    "address": "杭州市西湖区文三路 100 号 启航大厦 3 楼",
    "intro": "专注 6-18 岁青少年编程教育，课程覆盖 Scratch、Python、C++ 信奥、人工智能启蒙、Web 前端与机器人方向。",
}

_SETTINGS: dict[str, Any] = {
    "allowLeave": True,
    "scheduleRemind": True,
    "receiptPrint": False,
    "newStudentStatus": "在读",
}

# 明文密码仅在此处出现一次，落库前即转哈希
_USERS: list[dict[str, Any]] = [
    {"username": "admin",   "password": "admin123", "name": "张明远", "role": "超级管理员", "phone": "13800000001", "email": "admin@qihangcode.cn",   "joinDate": "2024-01-10", "status": "启用"},
    {"username": "jiaowu",  "password": "123456",   "name": "李文静", "role": "教务管理员", "phone": "13800000002", "email": "jiaowu@qihangcode.cn",  "joinDate": "2024-03-15", "status": "启用"},
    {"username": "caiwu",   "password": "123456",   "name": "周慧敏", "role": "财务专员",   "phone": "13800000003", "email": "caiwu@qihangcode.cn",   "joinDate": "2024-06-01", "status": "启用"},
    {"username": "qiantai", "password": "123456",   "name": "刘晓燕", "role": "前台接待",   "phone": "13800000004", "email": "qiantai@qihangcode.cn", "joinDate": "2025-02-10", "status": "启用"},
    {"username": "wangzq",  "password": "123456",   "name": "王志强", "role": "教师",       "phone": "13957100001", "email": "wangzq@qihangcode.cn",  "joinDate": "2021-03-15", "status": "禁用"},
]

_TEACHERS: list[dict[str, Any]] = [
    {"id": "JS001", "name": "王志强", "gender": "男", "phone": "13957100001", "email": "wangzq@qihangcode.cn", "subject": "Python", "title": "高级讲师", "hireDate": "2021-03-15", "status": "在职"},
    {"id": "JS002", "name": "林晓芸", "gender": "女", "phone": "13957100002", "email": "linxy@qihangcode.cn", "subject": "Scratch", "title": "讲师", "hireDate": "2022-06-01", "status": "在职"},
    {"id": "JS003", "name": "陈国栋", "gender": "男", "phone": "13957100003", "email": "chengd@qihangcode.cn", "subject": "C++", "title": "金牌竞赛教练", "hireDate": "2020-09-10", "status": "在职"},
    {"id": "JS004", "name": "赵雨桐", "gender": "女", "phone": "13957100004", "email": "zhaoyt@qihangcode.cn", "subject": "人工智能", "title": "讲师", "hireDate": "2023-02-20", "status": "在职"},
    {"id": "JS005", "name": "孙浩然", "gender": "男", "phone": "13957100005", "email": "sunhr@qihangcode.cn", "subject": "Web", "title": "讲师", "hireDate": "2022-11-05", "status": "在职"},
    {"id": "JS006", "name": "周美琳", "gender": "女", "phone": "13957100006", "email": "zhouml@qihangcode.cn", "subject": "机器人", "title": "助教", "hireDate": "2024-07-08", "status": "在职"},
    {"id": "JS007", "name": "吴建军", "gender": "男", "phone": "13957100007", "email": "wujj@qihangcode.cn", "subject": "Java", "title": "讲师", "hireDate": "2019-04-18", "status": "离职"},
]

_COURSES: list[dict[str, Any]] = [
    {"id": "KC001", "teacherId": "JS002", "name": "Scratch 趣味编程启蒙", "category": "Scratch", "level": "启蒙", "hours": 32, "price": 2400, "target": "6-9 岁，零基础", "status": "在售", "desc": "拖拽积木式编程，培养逻辑思维与创作兴趣，完成互动故事与小游戏作品。"},
    {"id": "KC002", "teacherId": "JS001", "name": "Python 零基础入门", "category": "Python", "level": "入门", "hours": 48, "price": 3600, "target": "10-15 岁，零基础", "status": "在售", "desc": "学习变量、循环、函数等基础语法，完成计算器、猜数字等小项目。"},
    {"id": "KC003", "teacherId": "JS001", "name": "Python 进阶与数据处理", "category": "Python", "level": "进阶", "hours": 60, "price": 4800, "target": "已完成 Python 入门", "status": "在售", "desc": "面向对象、文件处理、爬虫入门与数据可视化综合实战。"},
    {"id": "KC004", "teacherId": "JS003", "name": "C++ 信息学奥赛（CSP-J）", "category": "C++", "level": "竞赛", "hours": 72, "price": 6800, "target": "五年级以上，有编程基础", "status": "在售", "desc": "系统学习 C++ 语法、数据结构与算法，备战 CSP-J/S 入门级认证。"},
    {"id": "KC005", "teacherId": "JS004", "name": "人工智能启蒙（AI）", "category": "人工智能", "level": "启蒙", "hours": 36, "price": 3200, "target": "8-12 岁", "status": "在售", "desc": "认识机器学习基本概念，动手训练自己的图像识别小模型。"},
    {"id": "KC006", "teacherId": "JS005", "name": "Web 前端开发实战", "category": "Web", "level": "进阶", "hours": 56, "price": 5200, "target": "12 岁以上", "status": "在售", "desc": "HTML / CSS / JavaScript 全流程，独立开发个人网站与网页应用。"},
    {"id": "KC007", "teacherId": "JS006", "name": "机器人搭建与编程", "category": "机器人", "level": "入门", "hours": 40, "price": 3800, "target": "7-11 岁", "status": "在售", "desc": "机械结构搭建 + 图形化编程，锻炼动手能力与工程思维。"},
    {"id": "KC008", "name": "Java 计算思维养成", "category": "Java", "level": "入门", "hours": 48, "price": 4200, "target": "13 岁以上", "status": "停售", "desc": "面向对象编程思想训练，为后续深入学习打下基础。"},
]

_CLASSES: list[dict[str, Any]] = [
    {"id": "BJ001", "name": "Scratch 周六启蒙 A 班", "courseId": "KC001", "teacherId": "JS002", "classroom": "A101", "schedule": "周六 09:00-10:30", "capacity": 16, "startDate": "2026-09-05", "endDate": "2026-12-19", "status": "进行中"},
    {"id": "BJ002", "name": "Python 入门 · 周日班", "courseId": "KC002", "teacherId": "JS001", "classroom": "B203", "schedule": "周日 09:00-12:00", "capacity": 20, "startDate": "2026-09-06", "endDate": "2026-12-20", "status": "进行中"},
    {"id": "BJ003", "name": "Python 入门 · 周五晚班", "courseId": "KC002", "teacherId": "JS001", "classroom": "B203", "schedule": "周五 18:30-21:00", "capacity": 20, "startDate": "2026-09-04", "endDate": "2026-12-18", "status": "进行中"},
    {"id": "BJ004", "name": "C++ 信奥秋季集训班", "courseId": "KC004", "teacherId": "JS003", "classroom": "C305", "schedule": "周六 13:30-17:30", "capacity": 24, "startDate": "2026-09-12", "endDate": "2027-01-10", "status": "进行中"},
    {"id": "BJ005", "name": "AI 启蒙 · 周六班", "courseId": "KC005", "teacherId": "JS004", "classroom": "A102", "schedule": "周六 10:40-12:10", "capacity": 16, "startDate": "2026-10-17", "endDate": "2027-01-23", "status": "未开班"},
    {"id": "BJ006", "name": "Web 前端暑期班", "courseId": "KC006", "teacherId": "JS005", "classroom": "C305", "schedule": "周一/三/五 09:00-12:00", "capacity": 20, "startDate": "2026-07-06", "endDate": "2026-08-28", "status": "已结课"},
]

_STUDENTS: list[dict[str, Any]] = [
    {"id": "XS001", "name": "陈一诺", "gender": "女", "grade": "三年级", "parent": "陈大文", "parentPhone": "15868710001", "classId": "BJ001", "enrollDate": "2026-08-20", "status": "在读"},
    {"id": "XS002", "name": "黄子睿", "gender": "男", "grade": "二年级", "parent": "黄志伟", "parentPhone": "15868710002", "classId": "BJ001", "enrollDate": "2026-08-22", "status": "在读"},
    {"id": "XS003", "name": "林诗涵", "gender": "女", "grade": "三年级", "parent": "林建国", "parentPhone": "15868710003", "classId": "BJ001", "enrollDate": "2026-08-25", "status": "在读"},
    {"id": "XS004", "name": "徐浩宇", "gender": "男", "grade": "四年级", "parent": "徐鹏", "parentPhone": "15868710004", "classId": "BJ001", "enrollDate": "2026-09-01", "status": "在读"},
    {"id": "XS005", "name": "李思远", "gender": "男", "grade": "初一", "parent": "李国豪", "parentPhone": "15868710005", "classId": "BJ002", "enrollDate": "2026-08-15", "status": "在读"},
    {"id": "XS006", "name": "王雨欣", "gender": "女", "grade": "六年级", "parent": "王建军", "parentPhone": "15868710006", "classId": "BJ002", "enrollDate": "2026-08-18", "status": "在读"},
    {"id": "XS007", "name": "张一鸣", "gender": "男", "grade": "初二", "parent": "张伟", "parentPhone": "15868710007", "classId": "BJ002", "enrollDate": "2026-08-28", "status": "在读"},
    {"id": "XS008", "name": "刘美琪", "gender": "女", "grade": "初一", "parent": "刘强", "parentPhone": "15868710008", "classId": "BJ002", "enrollDate": "2026-09-03", "status": "在读"},
    {"id": "XS009", "name": "周子墨", "gender": "男", "grade": "六年级", "parent": "周涛", "parentPhone": "15868710009", "classId": "BJ003", "enrollDate": "2026-08-30", "status": "在读"},
    {"id": "XS010", "name": "吴佳怡", "gender": "女", "grade": "初一", "parent": "吴斌", "parentPhone": "15868710010", "classId": "BJ003", "enrollDate": "2026-09-05", "status": "在读"},
    {"id": "XS011", "name": "郑天佑", "gender": "男", "grade": "五年级", "parent": "郑成", "parentPhone": "15868710011", "classId": "BJ003", "enrollDate": "2026-09-08", "status": "休学"},
    {"id": "XS012", "name": "孙铭泽", "gender": "男", "grade": "初二", "parent": "孙立", "parentPhone": "15868710012", "classId": "BJ004", "enrollDate": "2026-08-10", "status": "在读"},
    {"id": "XS013", "name": "马悦然", "gender": "女", "grade": "初一", "parent": "马啸", "parentPhone": "15868710013", "classId": "BJ004", "enrollDate": "2026-08-12", "status": "在读"},
    {"id": "XS014", "name": "朱柏宇", "gender": "男", "grade": "初三", "parent": "朱宏", "parentPhone": "15868710014", "classId": "BJ004", "enrollDate": "2026-09-10", "status": "在读"},
    {"id": "XS015", "name": "何静怡", "gender": "女", "grade": "高一", "parent": "何强", "parentPhone": "15868710015", "classId": "BJ006", "enrollDate": "2026-06-20", "status": "已结课"},
    {"id": "XS016", "name": "罗一鸣", "gender": "男", "grade": "高二", "parent": "罗刚", "parentPhone": "15868710016", "classId": "BJ006", "enrollDate": "2026-06-22", "status": "已结课"},
]

_PAYMENTS: list[dict[str, Any]] = [
    {"id": "JF001", "studentId": "XS001", "classId": "BJ001", "amount": 2400, "method": "微信",     "date": "2026-08-20", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF002", "studentId": "XS002", "classId": "BJ001", "amount": 2400, "method": "支付宝",   "date": "2026-08-22", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF003", "studentId": "XS003", "classId": "BJ001", "amount": 2400, "method": "微信",     "date": "2026-08-25", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF004", "studentId": "XS004", "classId": "BJ001", "amount": 1200, "method": "现金",     "date": "2026-09-01", "status": "待确认", "note": "报名定金，余款待缴"},
    {"id": "JF005", "studentId": "XS005", "classId": "BJ002", "amount": 3600, "method": "微信",     "date": "2026-08-15", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF006", "studentId": "XS006", "classId": "BJ002", "amount": 3600, "method": "支付宝",   "date": "2026-08-18", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF007", "studentId": "XS007", "classId": "BJ002", "amount": 3600, "method": "银行转账", "date": "2026-08-28", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF008", "studentId": "XS008", "classId": "BJ002", "amount": 1800, "method": "微信",     "date": "2026-09-03", "status": "待确认", "note": "分期第一期"},
    {"id": "JF009", "studentId": "XS009", "classId": "BJ003", "amount": 3600, "method": "微信",     "date": "2026-08-30", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF010", "studentId": "XS010", "classId": "BJ003", "amount": 3600, "method": "支付宝",   "date": "2026-09-05", "status": "已支付", "note": "秋季班学费"},
    {"id": "JF011", "studentId": "XS011", "classId": "BJ003", "amount": 3600, "method": "微信",     "date": "2026-09-08", "status": "已退款", "note": "学员休学，全额退费"},
    {"id": "JF012", "studentId": "XS012", "classId": "BJ004", "amount": 6800, "method": "银行转账", "date": "2026-08-10", "status": "已支付", "note": "秋季集训学费"},
    {"id": "JF013", "studentId": "XS013", "classId": "BJ004", "amount": 6800, "method": "微信",     "date": "2026-08-12", "status": "已支付", "note": "秋季集训学费"},
    {"id": "JF014", "studentId": "XS014", "classId": "BJ004", "amount": 6800, "method": "银行转账", "date": "2026-09-10", "status": "已支付", "note": "秋季集训学费"},
    {"id": "JF015", "studentId": "XS015", "classId": "BJ006", "amount": 5200, "method": "微信",     "date": "2026-06-20", "status": "已支付", "note": "暑期班学费"},
    {"id": "JF016", "studentId": "XS016", "classId": "BJ006", "amount": 5200, "method": "支付宝",   "date": "2026-06-22", "status": "已支付", "note": "暑期班学费"},
    {"id": "JF017", "studentId": "XS005", "classId": "BJ002", "amount": 600,  "method": "现金",     "date": "2026-09-15", "status": "已支付", "note": "教材费补缴"},
    {"id": "JF018", "studentId": "XS012", "classId": "BJ004", "amount": 800,  "method": "微信",     "date": "2026-09-18", "status": "已支付", "note": "竞赛模拟赛报名费"},
]

_NEWS: list[dict[str, Any]] = [
    {"id": "XW001", "title": "2026 秋季班全面开班：Python / C++ 信奥热门班级仅剩少量余位", "category": "开班信息", "top": True,  "date": "2026-09-02", "author": "张明远", "views": 486, "status": "已发布",
     "summary": "秋季学期各班级已陆续开课，Python 入门周日班、C++ 信奥秋季集训班报名火爆，目前仅剩少量余位，欢迎新老学员咨询。",
     "content": ["新学期伊始，启航编程 2026 秋季班已全面开班。", "其中 Python 零基础入门周日班、C++ 信息学奥赛（CSP-J）秋季集训班报名情况最为火爆。", "秋季班课程表已同步更新至「班级管理」模块。"]},
    {"id": "XW002", "title": "喜报！我机构 6 名学员晋级 CSP-J/S 复赛", "category": "比赛获奖", "top": False, "date": "2026-09-25", "author": "陈国栋", "views": 352, "status": "已发布",
     "summary": "在刚公布的 CSP-J/S 2026 第一轮认证成绩中，我机构 6 名学员成功晋级第二轮（复赛），创历史最好成绩。",
     "content": ["9 月 24 日，CCF CSP-J/S 2026 第一轮认证成绩公布。", "本次晋级的 6 名学员均来自陈国栋教练执教的 C++ 信奥集训班。"]},
    {"id": "XW003", "title": "「编程奇妙夜」中秋亲子体验活动圆满举办", "category": "活动通知", "top": False, "date": "2026-09-15", "author": "林晓芸", "views": 275, "status": "已发布",
     "summary": "9 月 14 日晚，中秋亲子编程体验活动在机构一层多功能厅举行，60 余组家庭参与了 Scratch 月兔奔月挑战。",
     "content": ["9 月 14 日晚，启航编程「编程奇妙夜」中秋亲子体验活动热闹举行。", "活动以「月兔奔月」为主题，家长与孩子组队用 Scratch 完成闯关小游戏。"]},
    {"id": "XW004", "title": "新课程上线：人工智能启蒙（AI）系列课", "category": "机构动态", "top": False, "date": "2026-09-10", "author": "赵雨桐", "views": 198, "status": "已发布",
     "summary": "面向 8-12 岁青少年的人工智能启蒙课程正式上线，孩子们将亲手训练自己的图像识别小模型。",
     "content": ["经过三个月的课程研发与试讲打磨，启航编程「人工智能启蒙（AI）」系列课于本学期正式上线。", "课程共 36 课时，采用「不插电 + 上机」结合的教学方式。"]},
    {"id": "XW005", "title": "关于国庆节放假及课程调整安排的通知", "category": "活动通知", "top": False, "date": "2026-09-26", "author": "李文静", "views": 413, "status": "已发布",
     "summary": "国庆假期（10 月 1 日—7 日）全机构停课，10 月 4 日（周日）原课程顺延或调至线上，详见正文安排。",
     "content": ["根据国家法定节假日安排，现将 2026 年国庆节放假及课程调整安排通知如下：", "一、10 月 1 日（周四）至 10 月 7 日（周三）全体班级停课放假。"]},
    {"id": "XW006", "title": "Python 入门班学员作品展示：小创意大能量", "category": "机构动态", "top": False, "date": "2026-09-18", "author": "王志强", "views": 241, "status": "已发布",
     "summary": "Python 入门班学员本周完成了结课作品展示，从猜数字到成语接龙，14 个小项目各具巧思。",
     "content": ["本周，Python 入门周日班与周五晚班联合举办了阶段作品展示课。", "张一鸣同学的「成语接龙闯关」将语文知识融入程序逻辑。"]},
]

_RESOURCES: list[dict[str, Any]] = [
    {"id": "ZY001", "title": "第1讲 初识 Python 与开发环境搭建", "type": "课件PPT", "courseId": "KC002", "teacherId": "JS001", "size": "8.2 MB", "duration": "", "downloads": 156, "date": "2026-09-06", "status": "已发布"},
    {"id": "ZY002", "title": "第3讲 变量与数据类型（含课堂练习）", "type": "课件PPT", "courseId": "KC002", "teacherId": "JS001", "size": "11.6 MB", "duration": "", "downloads": 132, "date": "2026-09-13", "status": "已发布"},
    {"id": "ZY003", "title": "循环结构精讲 · 名师教学录像", "type": "教学视频", "courseId": "KC002", "teacherId": "JS001", "size": "326 MB", "duration": "42 分钟", "downloads": 98, "date": "2026-09-15", "status": "已发布"},
    {"id": "ZY004", "title": "Scratch 舞台与角色入门示范课录像", "type": "教学视频", "courseId": "KC001", "teacherId": "JS002", "size": "512 MB", "duration": "38 分钟", "downloads": 87, "date": "2026-09-08", "status": "已发布"},
    {"id": "ZY005", "title": "CSP-J 入门级语法专项习题册（含解析）", "type": "习题册", "courseId": "KC004", "teacherId": "JS003", "size": "2.6 MB", "duration": "", "downloads": 204, "date": "2026-09-12", "status": "已发布"},
    {"id": "ZY006", "title": "Python 入门综合测试卷 A / B 卷", "type": "习题册", "courseId": "KC002", "teacherId": "JS001", "size": "1.8 MB", "duration": "", "downloads": 118, "date": "2026-09-18", "status": "已发布"},
    {"id": "ZY007", "title": "机器人课程机械结构素材包（图纸+3D）", "type": "素材包", "courseId": "KC007", "teacherId": "JS006", "size": "128 MB", "duration": "", "downloads": 64, "date": "2026-09-05", "status": "已发布"},
    {"id": "ZY008", "title": "AI 启蒙：什么是机器学习（教师版）", "type": "课件PPT", "courseId": "KC005", "teacherId": "JS004", "size": "14.3 MB", "duration": "", "downloads": 45, "date": "2026-09-20", "status": "已发布"},
    {"id": "ZY009", "title": "Web 前端暑期班结课作品路演全程录像", "type": "教学视频", "courseId": "KC006", "teacherId": "JS005", "size": "754 MB", "duration": "65 分钟", "downloads": 73, "date": "2026-08-30", "status": "已发布"},
    {"id": "ZY010", "title": "Scratch 主题素材合集：太空探险", "type": "素材包", "courseId": "KC001", "teacherId": "JS002", "size": "86 MB", "duration": "", "downloads": 121, "date": "2026-09-10", "status": "已发布"},
]


def _stamp() -> str:
    return now_iso()


def _at(day: str, hhmm: str = "10:00") -> str:
    """构造与 now_iso 同格式的演示时间戳（用于选课记录排序）。"""
    return f"{day}T{hhmm}:00+08:00"


# 选课记录：存量学员的入班记录（已通过）+ 若干待审核 / 已驳回申请，供演示审核流程
_ENROLLMENTS: list[dict[str, Any]] = [
    *[
        {"id": f"XK{idx:03d}", "studentId": st["id"], "classId": st["classId"], "status": "已通过",
         "source": "员工", "note": "", "reviewNote": "历史报名补录", "reviewedBy": "admin",
         "reviewedAt": _at(st["enrollDate"]), "waitlistNo": None, "createdAt": _at(st["enrollDate"])}
        for idx, st in enumerate(_STUDENTS, start=1)
    ],
    {"id": "XK017", "studentId": "XS005", "classId": "BJ001", "status": "待审核",
     "source": "学员", "note": "想同时学 Scratch 打基础", "reviewNote": None, "reviewedBy": None,
     "reviewedAt": None, "waitlistNo": None, "createdAt": _at("2026-10-26", "20:15")},
    {"id": "XK018", "studentId": "XS006", "classId": "BJ004", "status": "待审核",
     "source": "家长", "note": "孩子想冲 CSP-J，麻烦老师评估", "reviewNote": None, "reviewedBy": None,
     "reviewedAt": None, "waitlistNo": None, "createdAt": _at("2026-10-27", "09:40")},
    {"id": "XK019", "studentId": "XS007", "classId": "BJ005", "status": "已驳回",
     "source": "学员", "note": "", "reviewNote": "该班与现有 Python 班时间冲突，建议改报周六下午班",
     "reviewedBy": "jiaowu", "reviewedAt": _at("2026-10-25", "15:20"), "waitlistNo": None,
     "createdAt": _at("2026-10-24", "18:05")},
    {"id": "XK020", "studentId": "XS010", "classId": "BJ005", "status": "待审核",
     "source": "家长", "note": "对 AI 课程感兴趣", "reviewNote": None, "reviewedBy": None,
     "reviewedAt": None, "waitlistNo": None, "createdAt": _at("2026-10-28", "11:30")},
]


# 作业（教师面向班级布置）
_ASSIGNMENTS: list[dict[str, Any]] = [
    {"id": "HW001", "classId": "BJ002", "teacherId": "JS001", "title": "第 4 讲课后练习：循环与条件判断",
     "content": "完成课本第 4 章练习 1-3：用 for/while 输出乘法表，并判断一个年份是否为闰年。提交代码与运行结果截图说明。",
     "dueDate": "2026-11-01", "status": "进行中"},
    {"id": "HW002", "classId": "BJ002", "teacherId": "JS001", "title": "阶段小测：列表与字典",
     "content": "实现学生成绩录入与统计：用列表保存成绩，用字典统计各分数段人数。",
     "dueDate": "2026-10-18", "status": "已结束"},
    {"id": "HW003", "classId": "BJ003", "teacherId": "JS001", "title": "周五晚班：函数练习",
     "content": "编写 3 个函数：求最大值、判断素数、字符串反转，并各写一个调用示例。",
     "dueDate": "2026-11-06", "status": "进行中"},
    {"id": "HW004", "classId": "BJ001", "teacherId": "JS002", "title": "Scratch 角色移动小练习",
     "content": "让小猫按键盘方向键移动，碰到边缘时反弹，并说出「到边界啦」。",
     "dueDate": "2026-10-30", "status": "进行中"},
    {"id": "HW005", "classId": "BJ004", "teacherId": "JS003", "title": "CSP-J 模拟题第一套",
     "content": "完成模拟题第一套的选择题与两道编程题，注意时间复杂度。",
     "dueDate": "2026-11-08", "allowLate": True, "status": "进行中"},
]

# 作业提交 / 批改
_SUBMISSIONS: list[dict[str, Any]] = [
    {"id": "TJ001", "assignmentId": "HW001", "studentId": "XS005", "content": "已提交乘法表与闰年判断代码，附运行结果。",
     "submittedAt": "2026-10-20", "status": "已提交", "score": None, "comment": None, "gradedAt": None, "gradedBy": None},
    {"id": "TJ002", "assignmentId": "HW001", "studentId": "XS006", "content": "乘法表用嵌套循环实现，闰年判断考虑了整百年份。",
     "submittedAt": "2026-10-20", "status": "已批改", "score": 92, "comment": "循环边界处理得很好，闰年规则完整。", "gradedAt": "2026-10-21", "gradedBy": "JS001"},
    {"id": "TJ003", "assignmentId": "HW002", "studentId": "XS005", "content": "成绩统计程序已提交。",
     "submittedAt": "2026-10-17", "status": "已批改", "score": 85, "comment": "字典统计正确，建议补充输入校验。", "gradedAt": "2026-10-18", "gradedBy": "JS001"},
    {"id": "TJ004", "assignmentId": "HW003", "studentId": "XS009", "content": "三个函数均已实现，附调用示例。",
     "submittedAt": "2026-10-21", "status": "已提交", "score": None, "comment": None, "gradedAt": None, "gradedBy": None},
    {"id": "TJ005", "assignmentId": "HW004", "studentId": "XS001", "content": "小猫可以按方向键移动，碰到边缘会反弹并说话。",
     "submittedAt": "2026-10-19", "status": "已批改", "score": 95, "comment": "动作衔接自然，反弹效果完成得很好。", "gradedAt": "2026-10-20", "gradedBy": "JS002"},
    {"id": "TJ006", "assignmentId": "HW005", "studentId": "XS012", "content": "选择题完成，编程题第二题超时，正在优化。",
     "submittedAt": "2026-10-21", "status": "已提交", "score": None, "comment": None, "gradedAt": None, "gradedBy": None},
]

# 考勤（班级 + 日期 + 学员）
_ATTENDANCE: list[dict[str, Any]] = [
    {"id": "KQ001", "classId": "BJ001", "studentId": "XS001", "date": "2026-10-17", "status": "出勤", "note": "", "teacherId": "JS002"},
    {"id": "KQ002", "classId": "BJ001", "studentId": "XS002", "date": "2026-10-17", "status": "出勤", "note": "", "teacherId": "JS002"},
    {"id": "KQ003", "classId": "BJ001", "studentId": "XS003", "date": "2026-10-17", "status": "迟到", "note": "迟到 10 分钟", "teacherId": "JS002"},
    {"id": "KQ004", "classId": "BJ001", "studentId": "XS004", "date": "2026-10-17", "status": "出勤", "note": "", "teacherId": "JS002"},
    {"id": "KQ005", "classId": "BJ002", "studentId": "XS005", "date": "2026-10-18", "status": "出勤", "note": "", "teacherId": "JS001"},
    {"id": "KQ006", "classId": "BJ002", "studentId": "XS006", "date": "2026-10-18", "status": "出勤", "note": "", "teacherId": "JS001"},
    {"id": "KQ007", "classId": "BJ002", "studentId": "XS007", "date": "2026-10-18", "status": "迟到", "note": "迟到 15 分钟", "teacherId": "JS001"},
    {"id": "KQ008", "classId": "BJ002", "studentId": "XS008", "date": "2026-10-18", "status": "请假", "note": "家长提前请假", "teacherId": "JS001"},
    {"id": "KQ009", "classId": "BJ003", "studentId": "XS009", "date": "2026-10-16", "status": "出勤", "note": "", "teacherId": "JS001"},
    {"id": "KQ010", "classId": "BJ003", "studentId": "XS010", "date": "2026-10-16", "status": "出勤", "note": "", "teacherId": "JS001"},
    {"id": "KQ011", "classId": "BJ003", "studentId": "XS011", "date": "2026-10-16", "status": "缺勤", "note": "学员休学中", "teacherId": "JS001"},
]


# 教师开课申请（演示：待审核 2 条、已驳回 1 条）
_COURSE_PROPOSALS: list[dict[str, Any]] = [
    {"id": "KK001", "teacherId": "JS005", "name": "Web 前端进阶：Vue 3 实战", "category": "Web",
     "level": "进阶", "hours": 48, "price": 5600, "target": "12 岁以上，已掌握 HTML/CSS/JS",
     "desc": "以组件化思维完成一个完整的后台管理前端，涵盖 Vue 3、Pinia、路由与接口联调。",
     "preferredSchedule": "周日 14:00-17:00", "status": "待审核", "reviewNote": None,
     "reviewedBy": None, "reviewedAt": None, "courseId": None, "createdAt": _at("2026-10-27", "19:20")},
    {"id": "KK002", "teacherId": "JS006", "name": "机器人竞赛集训（WRO）", "category": "机器人",
     "level": "竞赛", "hours": 36, "price": 4800, "target": "9-13 岁，有机器人基础",
     "desc": "围绕 WRO 常规赛任务开展结构搭建、巡线与任务编程集训，含两场模拟赛。",
     "preferredSchedule": "周六 15:00-17:30", "status": "待审核", "reviewNote": None,
     "reviewedBy": None, "reviewedAt": None, "courseId": None, "createdAt": _at("2026-10-28", "10:05")},
    {"id": "KK003", "teacherId": "JS003", "name": "C++ 信奥冲刺（CSP-S）", "category": "C++",
     "level": "竞赛", "hours": 60, "price": 7800, "target": "已通过 CSP-J 的学员",
     "desc": "面向 CSP-S 提高级的高强度算法冲刺，覆盖图论、动态规划与真题精讲。",
     "preferredSchedule": "周六 18:00-21:00", "status": "已驳回",
     "reviewNote": "本学期 C++ 师资已排满，建议下学期再评估",
     "reviewedBy": "jiaowu", "reviewedAt": _at("2026-10-25", "16:40"), "courseId": None,
     "createdAt": _at("2026-10-24", "20:10")},
]

def _make_account(
    username: str,
    password: str,
    *,
    name: str,
    role: str,
    identity: str,
    status: str = "启用",
    phone: str = "",
    email=None,
    join_date: str | None = None,
    ref_id: str | None = None,
) -> Account:
    ts = _stamp()
    return Account(
        username=username,
        passwordHash=hash_password(password),
        name=name,
        role=role,
        identity=identity,
        status=status,
        phone=phone,
        email=email,
        joinDate=join_date,
        refId=ref_id,
        createdAt=ts,
        updatedAt=ts,
    )


def _seed_schedules(session, ts: str) -> None:
    """按班级「上课时间」文本生成排课规则与整个学期的课次（种子数据）。"""
    today_date = date.today()
    rule_no = 0
    session_no = 0
    for cls in _CLASSES:
        specs = parse_schedule_text(cls.get("schedule"))
        start = parse_date(cls["startDate"], label="开班日期")
        end = parse_date(cls["endDate"], label="结课日期")
        for spec in specs:
            rule_no += 1
            session.add(ClassSchedule(
                id=f"PB{rule_no:03d}", classId=cls["id"], weekday=spec["weekday"],
                startTime=spec["startTime"], endTime=spec["endTime"],
                effectiveFrom=cls["startDate"], effectiveTo=cls["endDate"],
                classroom=cls.get("classroom") or "", createdAt=ts, updatedAt=ts,
            ))
        for spec in specs:
            for day in expand_dates(spec["weekday"], start, end):
                session_no += 1
                session.add(ClassSession(
                    id=f"SK{session_no:03d}", classId=cls["id"], teacherId=cls["teacherId"],
                    sessionDate=day.isoformat(), startTime=spec["startTime"],
                    endTime=spec["endTime"], classroom=cls.get("classroom") or "",
                    topic=None, status=session_status(day, today_date), source="auto",
                    createdAt=ts, updatedAt=ts,
                ))


def seed_db() -> None:
    """将完整种子数据写入数据库（reset_schema 之后调用）。"""
    ts = _stamp()
    with SessionLocal() as s:
        # 系统配置
        s.add(Config(key="org", value=_json.dumps(_ORG, ensure_ascii=False)))
        s.add(Config(key="settings", value=_json.dumps(_SETTINGS, ensure_ascii=False)))

        # 员工账号（staff）
        for u in _USERS:
            s.add(_make_account(
                u["username"], u["password"],
                name=u["name"], role=u["role"], identity="staff",
                status=u["status"], phone=u["phone"], email=u["email"],
                join_date=u["joinDate"],
            ))

        # 教师门户账号（teacher）
        for t in _TEACHERS:
            s.add(_make_account(
                t["id"], DEFAULT_USER_PASSWORD,
                name=t["name"], role="教师", identity="teacher",
                status="启用" if t["status"] == "在职" else "禁用",
                phone=t["phone"], email=t["email"],
                join_date=t["hireDate"], ref_id=t["id"],
            ))

        # 学员门户账号（student）
        for st in _STUDENTS:
            s.add(_make_account(
                st["id"], DEFAULT_USER_PASSWORD,
                name=st["name"], role="学员", identity="student",
                phone=st.get("parentPhone", ""), ref_id=st["id"],
                join_date=st["enrollDate"],
            ))

        # 家长门户账号（parent）：按「家长 + 家长电话」去重
        parent_groups: dict[tuple[str, str], list[str]] = {}
        for st in _STUDENTS:
            key = (st["parent"], st["parentPhone"])
            parent_groups.setdefault(key, []).append(st["id"])
        for idx, ((pname, pphone), children) in enumerate(parent_groups.items(), start=1):
            pcode = f"P{idx:03d}"
            s.add(_make_account(
                pcode, DEFAULT_USER_PASSWORD,
                name=pname, role="家长", identity="parent",
                phone=pphone, ref_id=pcode,
            ))
            for sid in children:
                s.add(StudentParent(parentCode=pcode, studentCode=sid))

        # 业务实体
        for t in _TEACHERS:
            s.add(Teacher(**{**t, "createdAt": ts, "updatedAt": ts}))
        for c in _COURSES:
            s.add(Course(**{**c, "createdAt": ts, "updatedAt": ts}))
        for c in _CLASSES:
            s.add(Class(**{**c, "createdAt": ts, "updatedAt": ts}))
        # 排课规则与课次：解析班级的上课时间文本，按起止日期生成整个学期的课次
        _seed_schedules(s, ts)
        for st in _STUDENTS:
            s.add(Student(**{**st, "createdAt": ts, "updatedAt": ts}))

        # 应收账单：每名学员一条，金额 = 班级课程价，账期 = 报名月，到期日 = 报名日 + 14 天；
        # 已全额退费的学员（XS011）账单直接作废，避免家长端出现虚假欠费。
        class_by_id = {c["id"]: c for c in _CLASSES}
        course_by_id = {c["id"]: c for c in _COURSES}
        bill_of_student: dict[str, str] = {}
        for idx, st in enumerate(_STUDENTS, start=1):
            cls = class_by_id[st["classId"]]
            course = course_by_id[cls["courseId"]]
            refunded = any(
                p["studentId"] == st["id"] and p["status"] == "已退款" for p in _PAYMENTS
            )
            bill_id = f"ZD{idx:03d}"
            bill_of_student[st["id"]] = bill_id
            s.add(Bill(
                id=bill_id, studentId=st["id"], classId=cls["id"], courseId=course["id"],
                period=st["enrollDate"][:7], amount=course["price"],
                status="已作废" if refunded else "待缴",
                dueDate=(date.fromisoformat(st["enrollDate"]) + timedelta(days=14)).isoformat(),
                note="报名学费（种子数据）", createdAt=ts, updatedAt=ts,
            ))

        # 缴费流水：学费 / 定金 / 分期挂到对应账单；教材费、报名费等留作历史流水
        for p in _PAYMENTS:
            bill_id = bill_of_student.get(p["studentId"])
            linked = bill_id and any(k in (p.get("note") or "") for k in ("学费", "定金", "分期"))
            s.add(Payment(**{**p, "billId": bill_id if linked else None,
                             "createdAt": ts, "updatedAt": ts}))
        for n in _NEWS:
            s.add(News(**{**n, "content": _json.dumps(n["content"], ensure_ascii=False),
                          "createdAt": ts, "updatedAt": ts}))
        for r in _RESOURCES:
            s.add(Resource(**{**r, "createdAt": ts, "updatedAt": ts}))
        for a in _ASSIGNMENTS:
            s.add(Assignment(**{**a, "createdAt": ts, "updatedAt": ts}))
        for sub in _SUBMISSIONS:
            s.add(Submission(**{**sub, "createdAt": ts, "updatedAt": ts}))
        for att in _ATTENDANCE:
            s.add(Attendance(**{**att, "createdAt": ts, "updatedAt": ts}))
        for e in _ENROLLMENTS:
            s.add(Enrollment(**{**e, "updatedAt": e["createdAt"]}))
        for p in _COURSE_PROPOSALS:
            s.add(CourseProposal(**{**p, "updatedAt": p["createdAt"]}))
        s.commit()
