/* ============================================================
 * common.js —— 公共脚本：布局渲染 / 数据缓存 / 通用组件
 * 依赖：api.js（先于本文件引入）
 * 数据来源：FastAPI /api/v1，页面 boot 后统一拉取到 window.DB
 * ============================================================ */

/* ---------- 图标库（feather 风格内联 SVG） ---------- */
const _svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICONS = {
  dashboard: _svg('<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>'),
  book:      _svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
  users:     _svg('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
  teacher:   _svg('<path d="M2 3h20"/><path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"/><path d="m7 21 5-5 5 5"/>'),
  student:   _svg('<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  wallet:    _svg('<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>'),
  idcard:    _svg('<rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="8" cy="10" r="2"/><path d="M14 9h5"/><path d="M14 13h5"/><path d="M5.5 16a3 3 0 0 1 5 0"/>'),
  gear:      _svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12"/>'),
  logout:    _svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'),
  search:    _svg('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
  plus:      _svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>'),
  edit:      _svg('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>'),
  trash:     _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
  check:     _svg('<polyline points="20 6 9 17 4 12"/>'),
  x:         _svg('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  warn:      _svg('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
  info:      _svg('<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'),
  clock:     _svg('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  calendar:  _svg('<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>'),
  chart:     _svg('<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>'),
  coin:      _svg('<circle cx="12" cy="12" r="10"/><path d="M12 7v10M9.5 9.5c.6-.9 1.6-1.3 2.5-1.3 1.4 0 2.5.8 2.5 1.9s-1.1 1.6-2.5 1.9c-1.4.3-2.5.8-2.5 1.9s1.1 1.9 2.5 1.9c.9 0 1.9-.4 2.5-1.3"/>'),
  menu:      _svg('<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>'),
  empty:     _svg('<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'),
  refresh:   _svg('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'),
  userplus:  _svg('<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>'),
  arrow:     _svg('<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>'),
  building:  _svg('<rect x="4" y="2" width="16" height="20" rx="2"/><line x1="9" y1="7" x2="10" y2="7"/><line x1="14" y1="7" x2="15" y2="7"/><line x1="9" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="15" y2="12"/><path d="M10 22v-4a2 2 0 0 1 4 0v4"/>'),
  lock:      _svg('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
  news:      _svg('<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>'),
  folder:    _svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  video:     _svg('<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/>'),
  download:  _svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
  eye:       _svg('<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>'),
  filetext:  _svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
  package:   _svg('<line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>'),
  trophy:    _svg('<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'),
  usercog:   _svg('<circle cx="9" cy="7" r="4"/><path d="M2 21v-2a4 4 0 0 1 4-4h6"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M17.5 13.5v1.2M17.5 20.3v1.2M14.8 15.9l1 .6M20.2 18.5l1 .6M14.8 18.5l1-.6M20.2 15.9l1-.6"/>')
};

/* ---------- 基础工具 ---------- */
const $  = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => [...p.querySelectorAll(s)];

function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function money(n) { return '¥' + Number(n || 0).toLocaleString('zh-CN'); }
function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function valid(fields) {
  for (const [el, name] of fields) {
    if (!el.value.trim()) { showToast(`请填写${name}`, 'error'); el.focus(); return false; }
  }
  return true;
}

/* ---------- 数据缓存（后端为唯一数据源） ----------
 * 页面 boot 时并行拉取全量集合（演示数据量级 ≤100 条/集合），
 * 写操作成功后重新 hydrate，保证本地视图与服务器一致。
 */
window.DB = { users: [], teachers: [], courses: [], classes: [], students: [], payments: [], news: [], resources: [], org: {}, settings: {} };

async function hydrate() {
  const user = getSessionUser();
  const staff = isStaff(user);
  const admin = isAdmin(user);
  const failed = [];

  // 逐集合容错：某个集合无权限或请求失败时降级为空，不影响其余数据与页面渲染
  const fetchList = async (resource, allowed = true) => {
    if (!allowed) return { list: [] };
    try {
      const data = await api.list(resource);
      return { list: (data && data.list) || [] };
    } catch (e) {
      failed.push(resource);
      return { list: [] };
    }
  };
  const fetchConf = async () => {
    if (!staff) return { org: {}, settings: {} };   // /settings 仅员工可读（后端已收紧），门户身份直接跳过
    try {
      return await api.settingsGet();
    } catch (e) {
      failed.push('settings');
      return { org: {}, settings: {} };
    }
  };

  // 管理类集合（学员/班级/课程/教师/缴费）仅员工可见；用户列表仅超级管理员可拉取
  const [teachers, courses, classes, students, payments, news, resources, conf, users] = await Promise.all([
    fetchList('teachers', staff), fetchList('courses', staff), fetchList('classes', staff),
    fetchList('students', staff), fetchList('payments', staff),
    fetchList('news'), fetchList('resources'),
    fetchConf(), fetchList('users', admin),
  ]);
  DB.teachers = teachers.list;  DB.courses = courses.list;  DB.classes = classes.list;
  DB.students = students.list;  DB.payments = payments.list; DB.news = news.list;
  DB.resources = resources.list; DB.users = users.list;
  DB.org = conf.org || {}; DB.settings = conf.settings || {};

  if (failed.length) showToast('部分数据加载失败：' + failed.join('、'), 'error');
}

/**
 * 页面启动入口：同步渲染布局（含会话校验）→ 拉取业务数据 → 返回当前用户。
 * 会话无效时自动跳转登录页并返回 null。
 * @param {string} pageKey 当前页面标识（见 PAGE_TITLES）
 * @param {boolean} [needData=true] 是否拉取业务集合（工作台等纯接口页可传 false）
 */
async function boot(pageKey, needData = true) {
  const user = renderLayout(pageKey);
  if (!user) return null;
  // 员工专属页面：非员工（教师 / 学员 / 家长）统一引导到身份门户
  if (STAFF_PAGES.has(pageKey) && !isStaff(user)) {
    location.replace('portal.html');
    return null;
  }
  // 管理员专属页面：非超级管理员（教务 / 财务 / 前台）引导回工作台
  if (ADMIN_PAGES.has(pageKey) && !isAdmin(user)) {
    showToast('您没有权限访问该页面', 'error');
    location.replace('dashboard.html');
    return null;
  }
  if (needData) {
    try {
      await hydrate();
    } catch (e) {
      showToast('数据加载失败：' + e.message, 'error');
    }
  }
  return user;
}

/* ---------- 关联查询 ---------- */
const byId = (list, id) => list.find(x => x.id === id);
const courseName  = id => (byId(DB.courses,  id) || {}).name  || '—';
const teacherName = id => (byId(DB.teachers, id) || {}).name  || '—';
const studentName = id => (byId(DB.students, id) || {}).name  || '—';
const className   = id => (byId(DB.classes,  id) || {}).name  || '—';

/* ---------- 头像 / 徽章 / 空状态 ---------- */
const AVATAR_COLORS = ['#4f46e5', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#f97316'];
function avatarColor(name) {
  let h = 0; for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
function avatarHtml(name, cls = '') {
  const n = String(name || '?');
  return `<span class="avatar ${cls}" style="background:${avatarColor(n)}">${esc(n.length > 2 ? n.slice(-2) : n)}</span>`;
}
const BADGE_MAP = {
  '在售': 'success', '停售': 'gray', '在职': 'success', '离职': 'gray',
  '在读': 'success', '休学': 'warning', '已结课': 'info',
  '未开班': 'warning', '进行中': 'success', '已结束': 'gray',
  '已支付': 'success', '待确认': 'warning', '已退款': 'danger', '已作废': 'gray',
  '启用': 'success', '禁用': 'danger', '已发布': 'success', '草稿': 'gray',
  '未提交': 'warning', '已提交': 'info', '已批改': 'success', '已退回': 'danger',
  '出勤': 'success', '迟到': 'warning', '请假': 'info', '缺勤': 'danger',
  '待上课': 'info', '已上课': 'success', '已完成': 'success', '已取消': 'gray', '已调课': 'warning', '待考勤': 'warning',
  '待缴': 'warning', '部分缴': 'info', '已缴': 'success', '已逾期': 'danger',
  '待审核': 'warning', '已通过': 'success', '已驳回': 'danger', '已退课': 'gray', '候补': 'info',
  '已撤回': 'gray'

};
function badge(text) { return `<span class="badge badge-${BADGE_MAP[text] || 'gray'}">${esc(text)}</span>`; }
function emptyRow(cols, text = '暂无数据') {
  return `<tr><td colspan="${cols}" class="table-empty"><div style="padding:36px 0">${ICONS.empty}<div style="margin-top:8px">${esc(text)}</div></div></td></tr>`;
}

/* ---------- 可复用区块：页面头 / 空状态 / 骨架屏 ---------- */
function pageHead(title, sub = '', actions = '') {
  return `<div class="page-head reveal" data-d="1">
    <div class="page-head-main">
      <h1>${esc(title)}</h1>
      ${sub ? `<div class="sub">${esc(sub)}</div>` : ''}
    </div>
    <div class="page-head-actions">${actions}</div>
  </div>`;
}
function emptyState(icon, title, desc = '', actions = '') {
  const ic = ICONS[icon] || ICONS.empty;
  return `<div class="empty-state">
    <div class="empty-ico">${ic}</div>
    <h3>${esc(title)}</h3>
    ${desc ? `<p>${esc(desc)}</p>` : ''}
    ${actions ? `<div class="empty-actions">${actions}</div>` : ''}
  </div>`;
}
function skeleton(lines = 3, block = true) {
  let h = '';
  if (block) h += `<div class="skeleton sk-block"></div>`;
  const w = [92, 80, 86, 70];
  for (let i = 0; i < lines; i++) h += `<div class="skeleton sk-line" style="width:${w[i % 4]}%"></div>`;
  return h;
}

/* ---------- 页面导航配置 ---------- */
const NAV_GROUPS = [
  { title: '总 览', items: [
    { key: 'dashboard', label: '工作台',   icon: 'dashboard', href: 'dashboard.html' }
  ]},
  { title: '业务管理', items: [
    { key: 'courses',  label: '课程管理', icon: 'book',     href: 'courses.html' },
    { key: 'classes',  label: '班级管理', icon: 'calendar', href: 'classes.html' },
    { key: 'timetable', label: '课表',     icon: 'clock',    href: 'timetable.html' },
    { key: 'teachers', label: '教师管理', icon: 'teacher',  href: 'teachers.html' },
    { key: 'students', label: '学生管理', icon: 'student',  href: 'students.html' },
    { key: 'enrollments', label: '选课管理', icon: 'userplus', href: 'enrollments.html' },
    { key: 'payments', label: '缴费管理', icon: 'wallet',   href: 'payments.html' }
  ]},
  { title: '内容管理', items: [
    { key: 'news',      label: '新闻中心', icon: 'news',   href: 'news.html' },
    { key: 'resources', label: '课件资源', icon: 'folder', href: 'resources.html' }
  ]},
  { title: '系 统', items: [
    { key: 'users',    label: '用户管理', icon: 'usercog', href: 'users.html', adminOnly: true },
    { key: 'profile',  label: '个人信息', icon: 'idcard',  href: 'profile.html' },
    { key: 'settings', label: '系统设置', icon: 'gear',    href: 'settings.html', adminOnly: true }
  ]}
];
const PAGE_TITLES = {
  dashboard: '工作台', courses: '课程管理', classes: '班级管理', teachers: '教师管理',
  students: '学生管理', payments: '缴费管理', news: '新闻中心', resources: '课件资源',
  users: '用户管理', profile: '个人信息', settings: '系统设置', portal: '我的门户',
  timetable: '课表', enrollments: '选课管理'
};

/* 非员工（教师 / 学员 / 家长）专属导航：仅开放门户与可阅读的内容 */
const PORTAL_NAV_GROUPS = [
  { title: '我 的', items: [
    { key: 'portal', label: '我的门户', icon: 'usercog', href: 'portal.html' }
  ]},
  { title: '内 容', items: [
    { key: 'news',      label: '新闻中心', icon: 'news',   href: 'news.html' },
    { key: 'resources', label: '课件资源', icon: 'folder', href: 'resources.html' }
  ]},
  { title: '账 户', items: [
    { key: 'profile',  label: '个人信息', icon: 'idcard',  href: 'profile.html' }
  ]}
];

/* 仅员工（后台）可见的页面：非员工访问会被重定向到门户 */
const STAFF_PAGES = new Set(['dashboard', 'courses', 'classes', 'timetable', 'teachers', 'students', 'enrollments', 'payments', 'users', 'settings']);

/* 仅超级管理员可见的页面：非管理员（含教务 / 财务 / 前台）访问会被重定向到工作台 */
const ADMIN_PAGES = new Set(['users', 'settings']);

function isAdmin(user) { return !!user && user.role === '超级管理员'; }
function isStaff(user) { return !!user && user.identity === 'staff'; }
function navGroupsFor(user) { return isStaff(user) ? NAV_GROUPS : PORTAL_NAV_GROUPS; }

/* ---------- 角色权限矩阵（《02-总体设计》§4.3，与后端 require_roles 同源） ----------
 * 服务端 403 才是安全边界；这里仅做入口隐藏 / 按钮禁用的体验优化。
 * -------------------------------------------------------------------------- */
function hasRole(user, ...roles) { return !!user && isStaff(user) && roles.includes(user.role); }
// 教师 / 课程 / 班级管理（写）：超管 + 教务
function canManageAcademic(user) { return hasRole(user, '超级管理员', '教务管理员'); }
// 学员管理（写 = 报名）：超管 + 教务 + 前台
function canEnrollStudent(user) { return hasRole(user, '超级管理员', '教务管理员', '前台接待'); }
// 缴费管理（登记 / 确认 / 作废 / 删除）：超管 + 财务
function canManageFinance(user) { return hasRole(user, '超级管理员', '财务专员'); }
// 新闻发布：超管 + 教务
function canPublishNews(user) { return hasRole(user, '超级管理员', '教务管理员'); }
// 课件资源（上传 / 编辑 / 删除）：超管 + 教务 + 教师岗
function canManageResource(user) { return hasRole(user, '超级管理员', '教务管理员', '教师'); }

/* 身份元数据：用于顶栏徽章与门户区分 */
const IDENTITY_META = {
  staff:   { label: '后台员工', pill: 'staff' },
  teacher: { label: '教师',   pill: 'teacher' },
  student: { label: '学员',   pill: 'student' },
  parent:  { label: '家长',   pill: 'parent' },
};
function identityPill(user) {
  const m = IDENTITY_META[user.identity] || { label: user.identity || '用户', pill: 'staff' };
  return `<span class="identity-pill ${m.pill}"><span class="dot"></span>${esc(m.label)}</span>`;
}

/* ---------- 会话（token 存取见 api.js） ---------- */
function doLogout() {
  clearSession();
  location.href = 'login.html';
}

/* ---------- 布局渲染（侧边栏 + 顶栏） ---------- */
function renderLayout(pageKey) {
  const user = getSessionUser();
  if (!user) { location.href = 'login.html'; return null; }

  $('#sidebar').innerHTML = `
    <div class="brand">
      <div class="brand-logo">启</div>
      <div>
        <div class="brand-name">启航编程</div>
        <div class="brand-sub">培训管理系统</div>
      </div>
    </div>
    <nav class="sidebar-nav">
      ${navGroupsFor(user).map(g => {
        const items = g.items.filter(it => !it.adminOnly || isAdmin(user));
        if (!items.length) return '';
        return `
        <div class="nav-group-title">${g.title}</div>
        ${items.map(it => `
          <a class="nav-item ${it.key === pageKey ? 'active' : ''}" href="${it.href}">${ICONS[it.icon]}<span>${it.label}</span></a>
        `).join('')}`;
      }).join('')}
    </nav>
    <div class="sidebar-foot">启航编程管理系统 v0.5<br>演示版 · 前后端联调</div>`;

  $('#topbar').innerHTML = `
    <button class="icon-btn hamburger" id="btn-menu" title="菜单">${ICONS.menu}</button>
    <div class="topbar-title">${PAGE_TITLES[pageKey] || ''}</div>
    <div class="topbar-user">
      <div class="user-meta">
        <div class="user-name">${esc(user.name)}</div>
        <div class="user-role">${esc(user.role)}</div>
      </div>
      ${identityPill(user)}
      ${avatarHtml(user.name)}
      <button class="icon-btn" id="btn-logout" title="退出登录">${ICONS.logout}</button>
    </div>`;

  // 移动端侧边栏开关
  $('#btn-menu').addEventListener('click', () => {
    $('#sidebar').classList.add('open');
    const mask = document.createElement('div');
    mask.className = 'sidebar-mask show';
    mask.addEventListener('click', () => { $('#sidebar').classList.remove('open'); mask.remove(); });
    document.body.appendChild(mask);
  });
  // 退出登录
  $('#btn-logout').addEventListener('click', () => {
    askConfirm('退出登录', '确定要退出当前账号吗？', doLogout);
  });
  return user;
}

/* ---------- Toast 轻提示 ---------- */
(function initToastWrap() {
  const wrap = document.createElement('div');
  wrap.className = 'toast-wrap';
  document.body.appendChild(wrap);
})();
function showToast(msg, type = 'success') {
  const icon = { success: 'check', error: 'warn', info: 'info' }[type] || 'info';
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `${ICONS[icon]}<span>${esc(msg)}</span>`;
  $('.toast-wrap').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, 2300);
}

/* ---------- 模态框 ---------- */
function openModal(id) { $('#' + id).classList.add('show'); }
function closeModal(id) { $('#' + id).classList.remove('show'); }

// 点击遮罩 / [data-close] 关闭；ESC 关闭最上层
document.addEventListener('click', (e) => {
  const closer = e.target.closest('[data-close]');
  if (closer) { closer.closest('.modal').classList.remove('show'); return; }
  if (e.target.classList.contains('modal-mask')) e.target.closest('.modal').classList.remove('show');
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $$('.modal.show').forEach(m => m.classList.remove('show'));
});

/* ---------- 确认对话框 ---------- */
function askConfirm(title, message, onOk) {
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-mask"></div>
    <div class="modal-box modal-sm">
      <div class="modal-head"><h3>${esc(title)}</h3></div>
      <div class="modal-body"><p class="confirm-msg">${esc(message)}</p></div>
      <div class="modal-foot">
        <button class="btn btn-ghost" data-close>取 消</button>
        <button class="btn btn-danger" data-ok>确 定</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add('show'));
  wrap.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) wrap.remove(); });
  wrap.querySelector('[data-ok]').addEventListener('click', () => { wrap.remove(); onOk && onOk(); });
}

/* ---------- 静态 HTML 图标占位替换 ----------
 * 用法：在 HTML 中写 <span data-icon="search"></span>，
 * 加载后自动替换为对应 SVG 图标。
 * -------------------------------------------------- */
function mountIcons(root = document) {
  $$('[data-icon]', root).forEach(el => {
    const name = el.dataset.icon;
    if (ICONS[name]) el.outerHTML = ICONS[name];
  });
}
document.addEventListener('DOMContentLoaded', () => mountIcons());



