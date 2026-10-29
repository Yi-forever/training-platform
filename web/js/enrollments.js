/* ============================================================
 * enrollments.js —— 选课管理：申请列表 / 审核 / 候补 / 退课 / 代报名
 * 数据来源：/api/v1/enrollments*（服务端按员工角色门禁）
 * ============================================================ */

let ENROLLMENTS = [];
let ENROLL_STATS = {};
let CATALOG = [];
let canWriteEnroll = false;
let rejectId = null;

document.addEventListener('DOMContentLoaded', async () => {
  const user = await boot('enrollments');
  if (!user) return;

  canWriteEnroll = hasRole(user, '超级管理员', '教务管理员', '前台接待');
  if (!canWriteEnroll) $('#btn-enroll').style.display = 'none';

  $('#kw').addEventListener('input', renderEnrollTable);
  $('#f-status').addEventListener('change', renderEnrollTable);
  $('#f-class').addEventListener('change', renderEnrollTable);
  $('#btn-enroll').addEventListener('click', openEnrollModal);
  $('#btn-enroll-submit').addEventListener('click', submitEnroll);
  $('#btn-reject-submit').addEventListener('click', submitReject);
  $('#tbody').addEventListener('click', onEnrollAction);

  await loadEnrollments();
});

async function loadEnrollments() {
  try {
    const [stats, data, catalog] = await Promise.all([
      api.enrollmentStats(),
      api.enrollments(),
      api.catalog(),
    ]);
    ENROLL_STATS = stats || {};
    ENROLLMENTS = (data && data.list) || [];
    CATALOG = catalog || [];
  } catch (e) {
    showToast(e.message, 'error');
    return;
  }
  renderEnrollStats();
  fillClassFilter();
  renderEnrollTable();
}

/* ---------- 统计卡 ---------- */
function renderEnrollStats() {
  const s = ENROLL_STATS;
  $('#enroll-stats').innerHTML = `
    <div class="stat-card reveal" data-d="1"><div class="stat-icon warning">${ICONS.clock}</div>
      <div><div class="stat-value">${s.pending || 0}</div><div class="stat-label">待审核申请</div></div></div>
    <div class="stat-card reveal" data-d="2"><div class="stat-icon success">${ICONS.check}</div>
      <div><div class="stat-value">${s.approved || 0}</div><div class="stat-label">已通过选课</div></div></div>
    <div class="stat-card reveal" data-d="3"><div class="stat-icon info">${ICONS.users}</div>
      <div><div class="stat-value">${s.waitlist || 0}</div><div class="stat-label">候补排队</div></div></div>
    <div class="stat-card reveal" data-d="4"><div class="stat-icon primary">${ICONS.userplus}</div>
      <div><div class="stat-value">${s.monthApplied || 0}</div><div class="stat-label">本月申请</div></div></div>`;
}

/* ---------- 筛选 ---------- */
function fillClassFilter() {
  const current = $('#f-class').value;
  const options = DB.classes
    .slice()
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(c => `<option value="${c.id}">${esc(c.name)}</option>`)
    .join('');
  $('#f-class').innerHTML = `<option value="">全部班级</option>${options}`;
  if (current) $('#f-class').value = current;
}

function filteredEnrollments() {
  const kw = $('#kw').value.trim().toLowerCase();
  const status = $('#f-status').value;
  const classId = $('#f-class').value;
  return ENROLLMENTS.filter(e =>
    (!status || e.status === status) &&
    (!classId || e.classId === classId) &&
    (!kw || [e.studentName, e.studentId, e.className, e.courseName, e.id]
      .some(v => String(v || '').toLowerCase().includes(kw)))
  );
}

/* ---------- 列表 ---------- */
function renderEnrollTable() {
  const list = filteredEnrollments();
  $('#count').textContent = list.length;
  $('#tbody').innerHTML = list.length ? list.map(e => {
    const wait = e.status === '候补' && e.waitlistNo ? ` <span class="td-sub">第 ${e.waitlistNo} 位</span>` : '';
    return `
    <tr>
      <td>
        <div class="cell-main">${esc(e.studentName || e.studentId)}</div>
        <div class="td-sub">${esc(e.studentId)}${e.grade ? ' · ' + esc(e.grade) : ''}</div>
      </td>
      <td>
        <div class="cell-main">${esc(e.className || '—')}</div>
        <div class="td-sub">${esc(e.courseName || '')}${e.teacherName ? ' · ' + esc(e.teacherName) : ''}</div>
      </td>
      <td class="td-sub" style="white-space:nowrap">${esc(e.schedule || '排课待定')}<br>${esc(e.classroom || '')}</td>
      <td>${esc(e.source || '—')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(String(e.createdAt || '').slice(0, 10))}</td>
      <td>${badge(e.status)}${wait}</td>
      <td class="td-sub clamp-2">${esc(e.reviewNote || '—')}</td>
      <td class="td-actions">
        ${canWriteEnroll && (e.status === '待审核' || e.status === '候补') ? `
          <button class="btn-link success" data-act="approve" data-id="${e.id}">${ICONS.check}通过</button>
          <button class="btn-link danger" data-act="reject" data-id="${e.id}">${ICONS.x}驳回</button>` : ''}
        ${canWriteEnroll && e.status === '已通过'
          ? `<button class="btn-link danger" data-act="withdraw" data-id="${e.id}">${ICONS.logout}退课</button>` : ''}
        ${!canWriteEnroll ? '<span class="td-sub">只读</span>' : ''}
      </td>
    </tr>`;
  }).join('') : emptyRow(8, '没有符合条件的选课记录');
}

/* ---------- 行操作 ---------- */
function onEnrollAction(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const row = ENROLLMENTS.find(x => x.id === btn.dataset.id);
  if (!row) return;
  const who = row.studentName || row.studentId;
  const target = row.className || row.classId;

  if (btn.dataset.act === 'approve') {
    askConfirm('通过选课申请',
      `确认为「${who}」办理「${target}」入班？通过后将自动生成该班学费账单。`,
      async () => {
        if (!await apiOk(() => api.reviewEnrollment(row.id, 'approve', ''), '已通过选课申请')) return;
        await loadEnrollments();
      });
  } else if (btn.dataset.act === 'reject') {
    rejectId = row.id;
    $('#f-review-note').value = '';
    openModal('reject-modal');
  } else if (btn.dataset.act === 'withdraw') {
    askConfirm('办理退课',
      `确定让「${who}」退出「${target}」吗？退课后名额将释放，候补学员会自动顺延。`,
      async () => {
        const data = await apiOk(() => api.staffWithdrawEnrollment(row.id), '已办理退课');
        if (!data) return;
        await loadEnrollments();
        if (data.promoted) showToast(`候补学员「${data.promoted.studentName}」已自动转正`);
      });
  }
}

async function submitReject() {
  if (!rejectId) return;
  const note = $('#f-review-note').value.trim();
  if (!note) { showToast('请填写驳回原因', 'error'); return; }
  const ok = await apiOk(() => api.reviewEnrollment(rejectId, 'reject', note), '已驳回选课申请');
  if (!ok) return;
  closeModal('reject-modal');
  rejectId = null;
  await loadEnrollments();
}

/* ---------- 代报名 ---------- */
function openEnrollModal() {
  if (!DB.students.length) { showToast('还没有学员，请先在学生管理中报名', 'error'); return; }
  $('#f-student').innerHTML = DB.students
    .slice()
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(s => `<option value="${s.id}">${esc(s.name)}（${esc(s.id)}${s.className ? ' · ' + esc(s.className) : ''}）</option>`)
    .join('');
  $('#f-enroll-class').innerHTML = CATALOG.length
    ? CATALOG.map(c => {
        const label = c.isFull
          ? `${c.className} · 已满（${c.enrolled}/${c.capacity}）`
          : `${c.className} · 余 ${c.remaining}/${c.capacity}`;
        return `<option value="${c.classId}" ${c.isFull ? 'disabled' : ''}>${esc(label)}</option>`;
      }).join('')
    : '<option value="">暂无可选班级</option>';
  $('#f-note').value = '';
  updateEnrollHint();
  $('#f-enroll-class').onchange = updateEnrollHint;
  openModal('enroll-modal');
}

function updateEnrollHint() {
  const cls = CATALOG.find(c => c.classId === $('#f-enroll-class').value);
  $('#f-enroll-hint').innerHTML = cls
    ? `${esc(cls.courseName)} · ${esc(cls.teacherName || '教师待定')} · ${esc(cls.schedule || '排课待定')}<br>
       学费 ${money(cls.price)} · 剩余 ${cls.remaining}/${cls.capacity} 个名额`
    : '请选择班级';
}

async function submitEnroll() {
  const studentId = $('#f-student').value;
  const classId = $('#f-enroll-class').value;
  if (!studentId || !classId) { showToast('请选择学员与班级', 'error'); return; }
  const ok = await apiOk(
    () => api.staffEnroll({ studentId, classId, note: $('#f-note').value.trim() }),
    '已为该学员办理入班'
  );
  if (!ok) return;
  closeModal('enroll-modal');
  await loadEnrollments();
}
