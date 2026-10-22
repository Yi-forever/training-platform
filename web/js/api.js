/* =========================================================
 * api.js —— 前端 API 客户端（阶段三：对接 FastAPI /api/v1）
 * - 统一请求封装：Bearer 注入、响应壳解析、401 自动跳登录
 * - 会话管理：token + 用户信息（记住我 -> localStorage，否则 sessionStorage）
 * 依赖顺序：本文件须先于 common.js / 页面脚本引入
 * ========================================================= */

'use strict';

const API_BASE = '/api/v1';
const TOKEN_KEY = 'qihang_token';
const USER_KEY = 'qihang_user';

/* ---------- 会话管理 ---------- */

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || '';
}

function saveSession(token, user, remember) {
  clearSession();
  const store = remember ? localStorage : sessionStorage;
  store.setItem(TOKEN_KEY, token);
  store.setItem(USER_KEY, JSON.stringify(user));
}

/** 资料更新后同步本地缓存的用户信息（保持原有存储位置）。 */
function updateCachedUser(user) {
  if (localStorage.getItem(TOKEN_KEY) !== null) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

/** 读取当前会话用户信息（无会话或解析失败时返回 null）。 */
function getSessionUser() {
  const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    clearSession();
    return null;
  }
}

/* ---------- 请求封装 ---------- */

/**
 * 发送请求并解析统一响应壳 { code, message, data }，成功返回 data。
 * 401 表示登录失效：清理会话并跳转登录页。
 */
async function request(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let resp;
  try {
    resp = await fetch(API_BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error('网络异常，请确认后端服务已启动');
  }

  if (resp.status === 401) {
    clearSession();
    location.href = 'login.html';
    throw new Error('登录已失效，请重新登录');
  }

  let payload = null;
  try { payload = await resp.json(); } catch (e) { /* 非 JSON 响应 */ }

  if (!resp.ok || !payload || payload.code !== 0) {
    throw new Error((payload && payload.message) || ('请求失败（HTTP ' + resp.status + '）'));
  }
  return payload.data;
}

/** 拼接查询串（过滤空值）。 */
function qs(params) {
  const entries = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return entries.length ? '?' + new URLSearchParams(entries).toString() : '';
}

/* ---------- API 方法 ---------- */

const api = {
  /* 通用 CRUD：resource ∈ users/teachers/courses/classes/students/payments/news/resources */
  list(resource, params) {
    return request('GET', '/' + resource + qs({ page: 1, pageSize: 100, ...params }));
  },
  get(resource, code) {
    return request('GET', '/' + resource + '/' + encodeURIComponent(code));
  },
  create(resource, data) {
    return request('POST', '/' + resource, data);
  },
  update(resource, code, data) {
    return request('PUT', '/' + resource + '/' + encodeURIComponent(code), data);
  },
  remove(resource, code) {
    return request('DELETE', '/' + resource + '/' + encodeURIComponent(code));
  },

  /* 认证与个人中心 */
  login(username, password) {
    return request('POST', '/auth/login', { username, password });
  },
  me() {
    return request('GET', '/auth/me');
  },
  authContext() {
    return request('GET', '/auth/context');
  },
  /* 身份门户：缴费详情（服务端按身份 / 关联关系做数据范围校验） */
  portalStudentPayments() {
    return request('GET', '/portal/student/payments');
  },
  portalParentPayments(studentId) {
    return request('GET', '/portal/parent/' + encodeURIComponent(studentId) + '/payments');
  },
  updateProfile(data) {
    return request('PUT', '/auth/profile', data);
  },
  changePassword(oldPassword, newPassword) {
    return request('PUT', '/auth/password', { oldPassword, newPassword });
  },
  resetPassword(username) {
    return request('POST', '/users/' + encodeURIComponent(username) + '/reset-password');
  },

  /* 缴费专用 */
  paymentStats() {
    return request('GET', '/payments/stats');
  },
  paymentConfirm(id) {
    return request('POST', '/payments/' + encodeURIComponent(id) + '/confirm');
  },
  paymentVoid(id) {
    return request('POST', '/payments/' + encodeURIComponent(id) + '/void');
  },

  /* 新闻 / 资源专用 */
  newsView(id) {
    return request('POST', '/news/' + encodeURIComponent(id) + '/view');
  },
  resourceDownload(id) {
    return request('POST', '/resources/' + encodeURIComponent(id) + '/download');
  },

  /* 工作台 */
  dashboard: {
    summary() { return request('GET', '/dashboard/summary'); },
    heat() { return request('GET', '/dashboard/heat'); },
    recentClasses() { return request('GET', '/dashboard/recent-classes'); },
    recentPayments() { return request('GET', '/dashboard/recent-payments'); },
  },

  /* 作业与考勤（教师 / 学员 / 家长门户） */
  teacherAssignments(classId) {
    return request('GET', '/portal/teacher/assignments' + qs({ classId }));
  },
  createAssignment(data) {
    return request('POST', '/portal/teacher/assignments', data);
  },
  updateAssignment(id, data) {
    return request('PUT', '/portal/teacher/assignments/' + encodeURIComponent(id), data);
  },
  deleteAssignment(id) {
    return request('DELETE', '/portal/teacher/assignments/' + encodeURIComponent(id));
  },
  assignmentSubmissions(id) {
    return request('GET', '/portal/teacher/assignments/' + encodeURIComponent(id) + '/submissions');
  },
  gradeSubmission(id, score, comment) {
    return request('POST', '/portal/teacher/submissions/' + encodeURIComponent(id) + '/grade', { score, comment });
  },
  teacherAttendance(classId, date) {
    return request('GET', '/portal/teacher/attendance' + qs({ classId, date }));
  },
  saveAttendance(data) {
    return request('POST', '/portal/teacher/attendance', data);
  },
  studentAssignments() {
    return request('GET', '/portal/student/assignments');
  },
  submitAssignment(id, content) {
    return request('POST', '/portal/student/assignments/' + encodeURIComponent(id) + '/submit', { content });
  },
  studentAttendance() {
    return request('GET', '/portal/student/attendance');
  },
  parentAssignments(studentId) {
    return request('GET', '/portal/parent/assignments' + qs({ studentId }));
  },
  parentAttendance(studentId) {
    return request('GET', '/portal/parent/attendance' + qs({ studentId }));
  },

  /* 课表（员工 / 教师 / 学员 / 家长） */
  sessions(start, end, classId, teacherId) {
    return request('GET', '/sessions' + qs({ start, end, classId, teacherId }));
  },
  generateSessions(classId, fromDate) {
    return request('POST', '/sessions/generate', { classId, fromDate });
  },
  updateSession(id, data) {
    return request('PUT', '/sessions/' + encodeURIComponent(id), data);
  },
  teacherSessions(start, end) {
    return request('GET', '/portal/teacher/sessions' + qs({ start, end }));
  },
  updateTeacherSession(id, data) {
    return request('PUT', '/portal/teacher/sessions/' + encodeURIComponent(id), data);
  },
  studentSessions(start, end) {
    return request('GET', '/portal/student/sessions' + qs({ start, end }));
  },
  parentSessions(studentId, start, end) {
    return request('GET', '/portal/parent/sessions' + qs({ studentId, start, end }));
  },
  teacherAttendanceSummary(classId, month) {
    return request('GET', '/portal/teacher/attendance/summary' + qs({ classId, month }));
  },

  /* 系统设置 */
  settingsGet() {
    return request('GET', '/settings');
  },
  settingsUpdate(data) {
    return request('PUT', '/settings', data);
  },
  settingsReset() {
    return request('POST', '/settings/reset');
  },
};

/**
 * 写操作统一包装：成功返回响应数据（无数据时为 true），失败 toast 错误并返回 false。
 * @param {Function} fn 返回 Promise 的 API 调用
 * @param {string} [successMsg] 成功提示文案（不传则不提示）
 */
async function apiOk(fn, successMsg) {
  try {
    const data = await fn();
    if (successMsg) showToast(successMsg);
    return data === undefined || data === null ? true : data;
  } catch (e) {
    showToast(e.message, 'error');
    return false;
  }
}
