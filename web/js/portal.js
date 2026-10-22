/* ============================================================
 * portal.js —— 身份门户：教师 / 学员 / 家长
 * - 教师：我的班级、作业管理（布置 / 编辑 / 删除 / 查看提交 / 批改）、考勤录入
 * - 学员：我的学籍、我的作业（提交 / 查看批改）、我的考勤
 * - 家长：关联学员、孩子作业与批改、孩子考勤
 * 数据来源：/api/v1/portal/*（服务端按身份门禁）
 * ============================================================ */

const IDENTITY_LABEL = { staff: '后台员工', teacher: '教师', student: '学员', parent: '家长' };
const ATT_STATUSES = ['出勤', '迟到', '请假', '缺勤'];

let USER = null;
let CTX = null;
let CLASSES = [];
let ASSIGNMENTS = [];
let CHILDREN = [];
let parentAssignments = [];
let parentAttendance = [];
let parentSessions = [];
let parentChildFilter = '';
let parentTtFilter = '';

/* ---------- 日期工具 ---------- */

function fmtDateLocal(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function portalRange(days = 14) {
  const start = new Date();
  const end = new Date();
  end.setDate(end.getDate() + days);
  return [fmtDateLocal(start), fmtDateLocal(end)];
}

function attSummaryChips(records) {
  const counts = { 出勤: 0, 迟到: 0, 请假: 0, 缺勤: 0 };
  records.forEach(r => { if (counts[r.status] !== undefined) counts[r.status] += 1; });
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const rate = total ? Math.round((counts['出勤'] + counts['迟到']) / total * 100) : 0;
  return `<div class="att-summary">
    <span class="att-chip">出勤 <b>${counts['出勤']}</b></span>
    <span class="att-chip">迟到 <b>${counts['迟到']}</b></span>
    <span class="att-chip">请假 <b>${counts['请假']}</b></span>
    <span class="att-chip">缺勤 <b>${counts['缺勤']}</b></span>
    <span class="att-chip">出勤率 <b>${rate}%</b></span>
  </div>`;
}

/* ---------- 启动 ---------- */

document.addEventListener('DOMContentLoaded', async () => {
  USER = await boot('portal', false);
  if (!USER) return;

  const el = $('#portal-content');
  el.innerHTML = pageHead(
    '我的门户',
    `${IDENTITY_LABEL[USER.identity] || USER.identity} · ${esc(USER.role || '')} · 欢迎回来`,
    ''
  );

  try {
    CTX = await api.authContext();
    const identity = CTX.identity || USER.identity;
    if (identity === 'teacher') await initTeacher(el);
    else if (identity === 'student') await initStudent(el);
    else if (identity === 'parent') await initParent(el);
    else el.insertAdjacentHTML('beforeend', staffHtml());
  } catch (e) {
    el.insertAdjacentHTML('beforeend', emptyState('warn', '加载失败', esc(e.message)));
  }
});

/* ---------- 通用弹窗 ---------- */

function openPortalModal(title, bodyHtml, submitText, onSubmit) {
  $('#pm-title').textContent = title;
  $('#pm-body').innerHTML = bodyHtml;
  const btn = $('#pm-submit');
  btn.textContent = submitText || '保 存';
  btn.style.display = submitText ? '' : 'none';
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      const keep = await onSubmit();
      if (keep !== false) closeModal('portal-modal');
    } finally {
      btn.disabled = false;
    }
  };
  openModal('portal-modal');
}

/* ============================================================
 * 教师
 * ============================================================ */

async function initTeacher(el) {
  CLASSES = CTX.classes || [];
  const [assignments, sessions] = await Promise.all([
    api.teacherAssignments(),
    api.teacherSessions(...portalRange(14)),
  ]);
  ASSIGNMENTS = assignments;
  el.insertAdjacentHTML('beforeend', teacherStatsHtml());
  el.insertAdjacentHTML('beforeend', teacherClassesHtml());
  el.insertAdjacentHTML('beforeend', teacherTimetableHtml(sessions));
  el.insertAdjacentHTML('beforeend', teacherAssignmentsHtml());
  el.insertAdjacentHTML('beforeend', teacherAttendanceHtml());

  $('#btn-new-assignment')?.addEventListener('click', () => openAssignmentEditor(null));
  $('#assignment-list')?.addEventListener('click', onAssignmentAction);
  $('#teacher-timetable')?.addEventListener('click', onTeacherSessionAction);
  $('#btn-att-summary')?.addEventListener('click', openAttendanceSummary);
  $('#att-class')?.addEventListener('change', loadAttendance);
  $('#att-date')?.addEventListener('change', loadAttendance);
  $('#att-load')?.addEventListener('click', loadAttendance);
  $('#att-save')?.addEventListener('click', saveAttendance);

  // 默认定位到最近一次课次，避免打开时落在没有课的日期上
  if (sessions.length) {
    const next = sessions.find(s => s.status !== '已取消') || sessions[0];
    const classSelect = $('#att-class');
    const dateInput = $('#att-date');
    if (classSelect) classSelect.value = next.classId;
    if (dateInput) dateInput.value = next.date;
  }
  if (CLASSES.length) await loadAttendance();
}

function teacherTimetableHtml(sessions) {
  const rows = sessions.slice(0, 12).map(s => `
    <tr>
      <td class="td-sub" style="white-space:nowrap">${esc(s.date)}</td>
      <td style="white-space:nowrap">${esc(s.startTime)}-${esc(s.endTime)}</td>
      <td>${esc(s.className)}</td>
      <td>${esc(s.topic || '—')}</td>
      <td>${badge(s.displayStatus)}${s.attendanceSaved ? ' <span class="td-sub">已考勤</span>' : ''}</td>
      <td class="td-actions">
        <button class="btn-link" data-att-class="${s.classId}" data-att-date="${s.date}">${ICONS.check}考勤</button>
      </td>
    </tr>`).join('') || emptyRow(6, '近两周暂无课次');
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.calendar} 我的课表</div>
        <div class="td-sub">近两周</div>
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>日期</th><th>时间</th><th>班级</th><th>授课主题</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="teacher-timetable">${rows}</tbody>
      </table></div></div>
    </div>`;
}

function onTeacherSessionAction(e) {
  const btn = e.target.closest('button[data-att-class]');
  if (!btn) return;
  const classId = btn.dataset.attClass;
  const date = btn.dataset.attDate;
  const classSelect = $('#att-class');
  const dateInput = $('#att-date');
  if (!classSelect || !dateInput) return;
  classSelect.value = classId;
  dateInput.value = date;
  loadAttendance();
  $('#att-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function teacherStatsHtml() {
  return `
    <div class="stat-grid">
      <div class="stat-card reveal" data-d="1"><div class="stat-icon primary">${ICONS.teacher}</div>
        <div><div class="stat-value">${CTX.classCount || 0}</div><div class="stat-label">所带班级</div></div></div>
      <div class="stat-card reveal" data-d="2"><div class="stat-icon info">${ICONS.student}</div>
        <div><div class="stat-value">${CTX.studentCount || 0}</div><div class="stat-label">在读学员</div></div></div>
      <div class="stat-card reveal" data-d="3"><div class="stat-icon warning">${ICONS.filetext}</div>
        <div><div class="stat-value">${CTX.assignmentCount || 0}</div><div class="stat-label">布置作业</div></div></div>
      <div class="stat-card reveal" data-d="4"><div class="stat-icon success">${ICONS.check}</div>
        <div><div class="stat-value">${CTX.pendingGrading || 0}</div><div class="stat-label">待批改</div></div></div>
    </div>`;
}

function teacherClassesHtml() {
  const rows = CLASSES.map(c => `
    <tr>
      <td>${esc(c.name)}</td><td>${esc(c.courseName)}</td>
      <td>${esc(c.schedule || '–')}</td>
      <td>${esc(c.status || '–')}</td>
      <td>${c.enrolled || 0}</td>
    </tr>`).join('') || emptyRow(5, '暂无带班');
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.calendar} 我的班级</div></div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>班级</th><th>课程</th><th>上课时间</th><th>状态</th><th>在读人数</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div></div>
    </div>`;
}

function teacherAssignmentsHtml() {
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.book} 作业管理</div>
        <button class="btn btn-sm" id="btn-new-assignment">${ICONS.plus} 布置作业</button>
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>作业</th><th>班级</th><th>截止日期</th><th>提交情况</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="assignment-list">${teacherAssignmentRows()}</tbody>
      </table></div></div>
    </div>`;
}

function teacherAssignmentRows() {
  if (!ASSIGNMENTS.length) return emptyRow(6, '还没有布置作业');
  return ASSIGNMENTS.map(a => `
    <tr>
      <td>
        <div class="cell-main">${esc(a.title)}</div>
        <div class="td-sub clamp-2">${esc(a.content || '')}</div>
      </td>
      <td>${esc(a.className || '–')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(a.dueDate || '–')}</td>
      <td style="white-space:nowrap">
        <div>${a.submittedCount || 0}/${a.totalStudents || 0} 已提交</div>
        <div class="td-sub">${a.gradedCount || 0} 已批改</div>
      </td>
      <td>${badge(a.status)}</td>
      <td class="td-actions">
        <button class="btn-link" data-act="subs" data-id="${a.id}">${ICONS.eye}提交情况</button>
        <button class="btn-link" data-act="edit" data-id="${a.id}">${ICONS.edit}编辑</button>
        <button class="btn-link danger" data-act="del" data-id="${a.id}">${ICONS.trash}删除</button>
      </td>
    </tr>`).join('');
}

async function reloadTeacherAssignments() {
  ASSIGNMENTS = await api.teacherAssignments();
  const tbody = $('#assignment-list');
  if (tbody) tbody.innerHTML = teacherAssignmentRows();
}

function openAssignmentEditor(a) {
  if (!CLASSES.length) { showToast('还没有所带班级，无法布置作业', 'error'); return; }
  const isEdit = !!a;
  const options = CLASSES.map(c =>
    `<option value="${c.id}" ${a && a.classId === c.id ? 'selected' : ''}>${esc(c.name)}</option>`
  ).join('');
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>作业标题<span class="req">*</span></label>
        <input class="input" id="a-title" maxlength="100" value="${a ? esc(a.title) : ''}" placeholder="如：第 5 讲课后练习">
      </div>
      <div class="form-item">
        <label>班级<span class="req">*</span></label>
        <select class="select" id="a-class">${options}</select>
      </div>
      <div class="form-item">
        <label>截止日期</label>
        <input class="input" type="date" id="a-due" value="${a ? esc(a.dueDate || '') : todayStr()}">
      </div>
      <div class="form-item full">
        <label>作业要求</label>
        <textarea class="input" id="a-content" rows="6" placeholder="请说明作业内容、提交要求与注意事项">${a ? esc(a.content || '') : ''}</textarea>
      </div>
      ${isEdit ? `
      <div class="form-item">
        <label>状态</label>
        <select class="select" id="a-status">
          <option ${a.status === '进行中' ? 'selected' : ''}>进行中</option>
          <option ${a.status === '已结束' ? 'selected' : ''}>已结束</option>
        </select>
      </div>` : ''}
    </div>`;
  openPortalModal(isEdit ? '编辑作业' : '布置作业', body, isEdit ? '保 存' : '发 布', async () => {
    const payload = {
      title: $('#a-title').value.trim(),
      classId: $('#a-class').value,
      dueDate: $('#a-due').value,
      content: $('#a-content').value.trim(),
    };
    if (!payload.title) { showToast('请填写作业标题', 'error'); return false; }
    if (isEdit) payload.status = $('#a-status').value;
    const ok = await apiOk(
      () => isEdit ? api.updateAssignment(a.id, payload) : api.createAssignment(payload),
      isEdit ? '作业已更新' : '作业已布置'
    );
    if (!ok) return false;
    await reloadTeacherAssignments();
    return true;
  });
}

function onAssignmentAction(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const a = ASSIGNMENTS.find(x => x.id === btn.dataset.id);
  if (!a) return;
  if (btn.dataset.act === 'edit') openAssignmentEditor(a);
  else if (btn.dataset.act === 'subs') openSubmissions(a);
  else if (btn.dataset.act === 'del') {
    askConfirm('删除作业', `确定删除「${a.title}」吗？该作业下的提交记录也会一并归档。`, async () => {
      const ok = await apiOk(() => api.deleteAssignment(a.id), '作业已删除');
      if (!ok) return;
      await reloadTeacherAssignments();
      await loadAttendance();
    });
  }
}

async function openSubmissions(a) {
  const data = await apiOk(() => api.assignmentSubmissions(a.id), '');
  if (!data) return;
  const rows = data.rows.map(r => `
    <tr>
      <td class="td-sub">${esc(r.studentId)}</td>
      <td>${esc(r.studentName)}</td>
      <td>${badge(r.status)}</td>
      <td class="td-sub">${esc(r.submittedAt || '–')}</td>
      <td>${r.score == null ? '–' : r.score}</td>
      <td class="td-sub">${esc(r.comment || '–')}</td>
      <td class="td-actions">
        ${r.submissionId
          ? `<button class="btn-link" data-sub="${r.submissionId}">${ICONS.edit}${r.status === '已批改' ? '重新批改' : '批改'}</button>`
          : '<span class="td-sub">等待提交</span>'}
      </td>
    </tr>`).join('') || emptyRow(7, '该班级暂无学员');
  const body = `
    <div class="td-sub" style="margin-bottom:10px">
      ${esc(a.className)} · 截止 ${esc(a.dueDate || '–')} · 已提交 ${data.submittedCount}/${data.totalStudents} · 已批改 ${data.gradedCount}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>学号</th><th>学员</th><th>状态</th><th>提交时间</th><th>分数</th><th>评语</th><th>操作</th></tr></thead>
      <tbody id="subs-body">${rows}</tbody>
    </table></div>`;
  openPortalModal(`提交情况 · ${a.title}`, body, '', async () => true);
  $('#subs-body')?.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-sub]');
    if (!b) return;
    const row = data.rows.find(x => x.submissionId === b.dataset.sub);
    if (row) openGradeForm(a, row);
  });
}

function openGradeForm(a, row) {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>${esc(row.studentName)} 的提交内容</label>
        <div class="input" style="height:auto;max-height:180px;overflow:auto;white-space:pre-wrap;background:var(--bg-soft)">${esc(row.content || '（未填写文字内容）')}</div>
      </div>
      <div class="form-item">
        <label>分数（0-100）<span class="req">*</span></label>
        <input class="input" id="g-score" type="number" min="0" max="100" value="${row.score == null ? '' : row.score}">
      </div>
      <div class="form-item full">
        <label>评语</label>
        <textarea class="input" id="g-comment" rows="3" placeholder="给学员的反馈（家长可见）">${esc(row.comment || '')}</textarea>
      </div>
    </div>`;
  openPortalModal(`批改 · ${row.studentName}`, body, '保存批改', async () => {
    const score = Number($('#g-score').value);
    if ($('#g-score').value === '' || !Number.isInteger(score) || score < 0 || score > 100) {
      showToast('请输入 0-100 的整数分数', 'error');
      return false;
    }
    const ok = await apiOk(
      () => api.gradeSubmission(row.submissionId, score, $('#g-comment').value.trim()),
      '批改成功'
    );
    if (!ok) return false;
    await reloadTeacherAssignments();
    await openSubmissions(a);
    return false;   // 由 openSubmissions 接管弹窗内容
  });
}

/* ---------- 教师：考勤 ---------- */

function teacherAttendanceHtml() {
  const options = CLASSES.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
  return `
    <div class="card reveal" data-d="4" id="att-card" style="margin-top:16px;margin-bottom:20px">
      <div class="card-head">
        <div class="card-title">${ICONS.clock} 考勤管理</div>
        <button class="btn btn-outline btn-sm" id="btn-att-summary">${ICONS.chart} 本月统计</button>
      </div>
      <div class="card-body">
        <div class="toolbar" style="padding:0 0 12px">
          <select class="select" id="att-class" style="width:230px" ${CLASSES.length ? '' : 'disabled'}>
            ${options || '<option>暂无班级</option>'}
          </select>
          <input class="input" type="date" id="att-date" value="${todayStr()}" style="width:160px">
          <button class="btn btn-outline" id="att-load">加载名单</button>
          <div class="toolbar-spacer"></div>
          <span class="td-sub" id="att-hint"></span>
          <button class="btn" id="att-save" ${CLASSES.length ? '' : 'disabled'}>保存考勤</button>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th>学号</th><th>学员</th><th>年级</th><th>考勤状态</th><th>备注</th></tr></thead>
          <tbody id="att-body">${emptyRow(5, '请选择班级与日期')}</tbody>
        </table></div>
      </div>
    </div>`;
}

async function loadAttendance() {
  const classId = $('#att-class')?.value;
  const date = $('#att-date')?.value;
  if (!classId || !date) return;
  const data = await apiOk(() => api.teacherAttendance(classId, date), '');
  if (!data) return;
  $('#att-hint').textContent = data.saved
    ? `已保存 · 出勤 ${data.summary['出勤']} / 迟到 ${data.summary['迟到']} / 请假 ${data.summary['请假']} / 缺勤 ${data.summary['缺勤']}`
    : '尚未录入，默认按「出勤」预填';
  $('#att-body').innerHTML = data.rows.length ? data.rows.map(s => `
    <tr>
      <td class="td-sub">${esc(s.studentId)}</td>
      <td>${esc(s.studentName)}</td>
      <td>${esc(s.grade || '–')}</td>
      <td>
        <select class="select att-status" data-sid="${s.studentId}" style="width:110px">
          ${ATT_STATUSES.map(st => `<option ${st === s.status ? 'selected' : ''}>${st}</option>`).join('')}
        </select>
      </td>
      <td><input class="input att-note" data-sid="${s.studentId}" value="${esc(s.note || '')}" placeholder="可选备注" style="width:190px"></td>
    </tr>`).join('') : emptyRow(5, '该班级暂无学员');
}

async function saveAttendance() {
  const classId = $('#att-class').value;
  const date = $('#att-date').value;
  const rows = $$('#att-body tr').filter(tr => tr.querySelector('.att-status'));
  if (!rows.length) { showToast('当前没有可保存的考勤名单', 'error'); return; }
  const items = rows.map(tr => ({
    studentId: tr.querySelector('.att-status').dataset.sid,
    status: tr.querySelector('.att-status').value,
    note: tr.querySelector('.att-note').value.trim(),
  }));
  const ok = await apiOk(() => api.saveAttendance({ classId, date, items }), '考勤已保存');
  if (!ok) return;
  await loadAttendance();
}

async function openAttendanceSummary() {
  const classId = $('#att-class')?.value;
  if (!classId) { showToast('请先选择班级', 'error'); return; }
  const month = ($('#att-date')?.value || todayStr()).slice(0, 7);
  const body = `
    <div class="toolbar" style="padding:0 0 12px">
      <span class="td-sub">统计月份</span>
      <input class="input" type="month" id="as-month" value="${month}" style="width:160px">
      <div class="toolbar-spacer"></div>
      <span class="td-sub" id="as-total"></span>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>学号</th><th>学员</th><th>出勤</th><th>迟到</th><th>请假</th><th>缺勤</th><th>出勤率</th></tr></thead>
      <tbody id="as-body"><tr><td colspan="7" class="table-empty">加载中…</td></tr></tbody>
    </table></div>`;
  openPortalModal('班级考勤统计', body, '', async () => true);
  const load = async () => {
    const m = $('#as-month').value;
    const data = await apiOk(() => api.teacherAttendanceSummary(classId, m), '');
    if (!data) return;
    $('#as-total').textContent = `合计 ${data.totals.total} 次 · 出勤率 ${data.totals.rate}%`;
    $('#as-body').innerHTML = data.students.map(s => `
      <tr>
        <td class="td-sub">${esc(s.studentId)}</td>
        <td>${esc(s.studentName)}</td>
        <td>${s['出勤']}</td><td>${s['迟到']}</td><td>${s['请假']}</td><td>${s['缺勤']}</td>
        <td><b style="color:${s.rate >= 80 ? 'var(--success)' : 'var(--warning)'}">${s.rate}%</b></td>
      </tr>`).join('') || emptyRow(7, '本月暂无考勤记录');
  };
  $('#as-month')?.addEventListener('change', load);
  await load();
}

/* ============================================================
 * 学员
 * ============================================================ */

async function initStudent(el) {
  const [assignments, attendance, sessions] = await Promise.all([
    api.studentAssignments(),
    api.studentAttendance(),
    api.studentSessions(...portalRange(14)),
  ]);
  el.insertAdjacentHTML('beforeend', studentStatsHtml());
  el.insertAdjacentHTML('beforeend', studentInfoHtml());
  el.insertAdjacentHTML('beforeend', studentTimetableHtml(sessions));
  el.insertAdjacentHTML('beforeend', `<div id="student-pay" style="margin-top:16px">${payLoadingCard('缴费明细')}</div>`);
  el.insertAdjacentHTML('beforeend', studentAssignmentsHtml(assignments));
  el.insertAdjacentHTML('beforeend', studentAttendanceHtml(attendance));
  $('#student-assignments')?.addEventListener('click', onStudentAssignmentAction);
  window.__studentAssignments = assignments;
  await loadStudentPayments();
}

function studentTimetableHtml(sessions) {
  const rows = sessions.slice(0, 12).map(s => `
    <tr>
      <td class="td-sub" style="white-space:nowrap">${esc(s.date)}</td>
      <td style="white-space:nowrap">${esc(s.startTime)}-${esc(s.endTime)}</td>
      <td>${esc(s.className)}</td>
      <td>${esc(s.topic || '—')}</td>
      <td>${esc(s.teacherName || '—')}</td>
      <td>${badge(s.displayStatus)}</td>
    </tr>`).join('') || emptyRow(6, '近两周暂无课次');
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.calendar} 我的课表</div>
        <div class="td-sub">近两周</div>
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>日期</th><th>时间</th><th>班级</th><th>授课主题</th><th>教师</th><th>状态</th></tr></thead>
        <tbody id="student-timetable">${rows}</tbody>
      </table></div></div>
    </div>`;
}

function studentStatsHtml() {
  const att = CTX.attendance || {};
  return `
    <div class="stat-grid">
      <div class="stat-card reveal" data-d="1"><div class="stat-icon success">${ICONS.coin}</div>
        <div><div class="stat-value">${money(CTX.paidTotal)}</div><div class="stat-label">已缴费用</div></div></div>
      <div class="stat-card reveal" data-d="2"><div class="stat-icon warning">${ICONS.filetext}</div>
        <div><div class="stat-value">${CTX.pendingAssignments || 0}</div><div class="stat-label">待完成作业</div></div></div>
      <div class="stat-card reveal" data-d="3"><div class="stat-icon info">${ICONS.check}</div>
        <div><div class="stat-value">${att['出勤'] || 0}</div><div class="stat-label">出勤次数</div></div></div>
      <div class="stat-card reveal" data-d="4"><div class="stat-icon primary">${ICONS.student}</div>
        <div><div class="stat-value">${esc(CTX.status || '–')}</div><div class="stat-label">学籍状态</div></div></div>
    </div>`;
}

function studentInfoHtml() {
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.idcard} 我的学籍</div></div>
      <div class="card-body">
        <div class="kv-grid">
          <div><span class="kv-k">班级</span><span class="kv-v">${esc(CTX.className || '–')}</span></div>
          <div><span class="kv-k">课程</span><span class="kv-v">${esc(CTX.courseName || '–')}</span></div>
          <div><span class="kv-k">带班教师</span><span class="kv-v">${esc(CTX.teacherName || '–')}</span></div>
          <div><span class="kv-k">上课时间</span><span class="kv-v">${esc(CTX.schedule || '–')}</span></div>
        </div>
      </div>
    </div>`;
}

function studentAssignmentsHtml(assignments) {
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.book} 我的作业</div></div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>作业</th><th>教师</th><th>截止日期</th><th>作业状态</th><th>提交状态</th><th>分数</th><th>操作</th></tr></thead>
        <tbody id="student-assignments">${studentAssignmentRows(assignments)}</tbody>
      </table></div></div>
    </div>`;
}

function studentAssignmentRows(assignments) {
  return assignments.map(a => `
    <tr>
      <td>
        <div class="cell-main">${esc(a.title)}</div>
        <div class="td-sub clamp-2">${esc(a.content || '')}</div>
      </td>
      <td style="white-space:nowrap">${esc(a.teacherName || '–')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(a.dueDate || '–')}</td>
      <td>${badge(a.status)}</td>
      <td>${badge(a.submitStatus)}</td>
      <td>${a.score == null ? '–' : a.score}</td>
      <td class="td-actions">
        ${a.status === '进行中'
          ? `<button class="btn-link" data-act="submit" data-id="${a.id}">${ICONS.edit}${a.submissionId ? '重新提交' : '提交作业'}</button>`
          : ''}
        ${a.submitStatus === '已批改'
          ? `<button class="btn-link success" data-act="view" data-id="${a.id}">${ICONS.eye}查看批改</button>`
          : ''}
      </td>
    </tr>`).join('') || emptyRow(7, '本班暂无作业');
}

function onStudentAssignmentAction(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const list = window.__studentAssignments || [];
  const a = list.find(x => x.id === btn.dataset.id);
  if (!a) return;
  if (btn.dataset.act === 'submit') openSubmitForm(a);
  else if (btn.dataset.act === 'view') openGradeView(a);
}

function openSubmitForm(a) {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>作业要求</label>
        <div class="input" style="height:auto;max-height:160px;overflow:auto;white-space:pre-wrap;background:var(--bg-soft)">${esc(a.content || '（无附加要求）')}</div>
      </div>
      <div class="form-item full">
        <label>我的答案<span class="req">*</span></label>
        <textarea class="input" id="s-content" rows="7" placeholder="可填写思路、代码或作品说明">${esc(a.submittedContent || '')}</textarea>
      </div>
    </div>`;
  openPortalModal(`提交作业 · ${a.title}`, body, '提 交', async () => {
    const content = $('#s-content').value.trim();
    if (!content) { showToast('请填写作业内容', 'error'); return false; }
    const ok = await apiOk(() => api.submitAssignment(a.id, content), '作业已提交');
    if (!ok) return false;
    await refreshStudent();
    return true;
  });
}

function openGradeView(a) {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>我的提交</label>
        <div class="input" style="height:auto;max-height:150px;overflow:auto;white-space:pre-wrap;background:var(--bg-soft)">${esc(a.submittedContent || '（未填写文字内容）')}</div>
      </div>
      <div class="form-item">
        <label>分数</label>
        <div style="font-size:26px;font-weight:600;color:var(--primary)">${a.score == null ? '–' : a.score}<span style="font-size:13px;color:var(--muted);font-weight:400"> / 100</span></div>
      </div>
      <div class="form-item full">
        <label>教师评语</label>
        <div class="input" style="height:auto;min-height:60px;white-space:pre-wrap;background:var(--bg-soft)">${esc(a.comment || '暂无评语')}</div>
      </div>
    </div>`;
  openPortalModal(`批改结果 · ${a.title}`, body, '', async () => true);
}

function studentAttendanceHtml(records) {
  const rows = records.map(r => `
    <tr>
      <td class="td-sub">${esc(r.date || '–')}</td>
      <td>${esc(r.className || '–')}</td>
      <td>${badge(r.status)}</td>
      <td class="td-sub">${esc(r.note || '–')}</td>
    </tr>`).join('') || emptyRow(4, '暂无考勤记录');
  return `
    <div class="card reveal" data-d="4" style="margin-top:16px;margin-bottom:20px">
      <div class="card-head"><div class="card-title">${ICONS.clock} 我的考勤</div></div>
      <div class="card-body">
        ${attSummaryChips(records)}
        <div class="table-wrap" style="margin-top:12px"><table>
          <thead><tr><th>日期</th><th>班级</th><th>考勤状态</th><th>备注</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </div>
    </div>`;
}

async function refreshStudent() {
  const [ctx, assignments] = await Promise.all([api.authContext(), api.studentAssignments()]);
  CTX = ctx;
  window.__studentAssignments = assignments;
  const statGrid = $('#portal-content .stat-grid');
  if (statGrid) statGrid.outerHTML = studentStatsHtml();
  const tbody = $('#student-assignments');
  if (tbody) tbody.innerHTML = studentAssignmentRows(assignments);
}

/* ---------- 学员：缴费详情 ---------- */

async function loadStudentPayments() {
  const box = $('#student-pay');
  if (!box) return;
  try {
    box.innerHTML = paySection(await api.portalStudentPayments(), { title: '缴费明细' });
  } catch (e) {
    box.innerHTML = payErrorCard(e);
  }
}

/* ============================================================
 * 家长
 * ============================================================ */

async function initParent(el) {
  CHILDREN = CTX.children || [];
  [parentAssignments, parentAttendance, parentSessions] = await Promise.all([
    api.parentAssignments(),
    api.parentAttendance(),
    api.parentSessions(null, ...portalRange(14)),
  ]);
  el.insertAdjacentHTML('beforeend', parentStatsHtml());
  el.insertAdjacentHTML('beforeend', parentChildrenHtml());
  el.insertAdjacentHTML('beforeend', parentPaymentsHtml());
  el.insertAdjacentHTML('beforeend', parentTimetableHtml());
  el.insertAdjacentHTML('beforeend', parentAssignmentsHtml());
  el.insertAdjacentHTML('beforeend', parentAttendanceHtml());
  $('#parent-tt-filter')?.addEventListener('change', e => {
    parentTtFilter = e.target.value;
    renderParentTimetable();
  });
  $('#parent-assign-filter')?.addEventListener('change', e => {
    parentChildFilter = e.target.value;
    renderParentAssignments();
  });
  $('#parent-att-filter')?.addEventListener('change', e => {
    parentChildFilter = e.target.value;
    renderParentAttendance();
  });
  initParentPayments();
}

function parentTimetableHtml() {
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.calendar} 孩子课表</div>
        ${childFilterHtml('parent-tt-filter')}
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>学员</th><th>日期</th><th>时间</th><th>班级</th><th>授课主题</th><th>状态</th></tr></thead>
        <tbody id="parent-timetable">${parentTimetableRows()}</tbody>
      </table></div></div>
    </div>`;
}

function parentTimetableRows() {
  const list = parentTtFilter
    ? parentSessions.filter(s => s.studentId === parentTtFilter)
    : parentSessions;
  return list.slice(0, 16).map(s => `
    <tr>
      <td>${esc(s.studentName)}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(s.date)}</td>
      <td style="white-space:nowrap">${esc(s.startTime)}-${esc(s.endTime)}</td>
      <td>${esc(s.className)}</td>
      <td>${esc(s.topic || '—')}</td>
      <td>${badge(s.displayStatus)}</td>
    </tr>`).join('') || emptyRow(6, '近两周暂无课次');
}

function renderParentTimetable() {
  const tbody = $('#parent-timetable');
  if (tbody) tbody.innerHTML = parentTimetableRows();
}

function parentStatsHtml() {
  const pending = parentAssignments.filter(a => a.assignmentStatus === '进行中' && a.submitStatus === '未提交').length;
  const graded = parentAssignments.filter(a => a.submitStatus === '已批改').length;
  return `
    <div class="stat-grid">
      <div class="stat-card reveal" data-d="1"><div class="stat-icon primary">${ICONS.student}</div>
        <div><div class="stat-value">${CTX.childCount || 0}</div><div class="stat-label">关联学员</div></div></div>
      <div class="stat-card reveal" data-d="2"><div class="stat-icon warning">${ICONS.filetext}</div>
        <div><div class="stat-value">${pending}</div><div class="stat-label">待完成作业</div></div></div>
      <div class="stat-card reveal" data-d="3"><div class="stat-icon success">${ICONS.check}</div>
        <div><div class="stat-value">${graded}</div><div class="stat-label">已批改作业</div></div></div>
    </div>`;
}

function parentChildrenHtml() {
  const rows = CHILDREN.map(s => `
    <tr>
      <td>${esc(s.name)}</td><td>${esc(s.grade || '–')}</td>
      <td>${esc(s.className || '–')}</td><td>${esc(s.courseName || '–')}</td>
      <td>${esc(s.teacherName || '–')}</td><td>${badge(s.status)}</td>
    </tr>`).join('') || emptyRow(6, '暂无关联学员');
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.users} 学员动态</div></div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>姓名</th><th>年级</th><th>班级</th><th>课程</th><th>带班教师</th><th>状态</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div></div>
    </div>`;
}

function childFilterHtml(id) {
  return `<select class="select" id="${id}" style="width:180px">
    <option value="">全部学员</option>
    ${CHILDREN.map(c => `<option value="${esc(c.studentId)}">${esc(c.name)}</option>`).join('')}
  </select>`;
}

function parentAssignmentsHtml() {
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.book} 作业与批改</div>
        ${childFilterHtml('parent-assign-filter')}
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>学员</th><th>作业</th><th>截止日期</th><th>提交状态</th><th>分数</th><th>教师评语</th></tr></thead>
        <tbody id="parent-assignments">${parentAssignmentRows()}</tbody>
      </table></div></div>
    </div>`;
}

function parentAssignmentRows() {
  const list = parentChildFilter
    ? parentAssignments.filter(a => a.studentId === parentChildFilter)
    : parentAssignments;
  return list.map(a => `
    <tr>
      <td>${esc(a.studentName)}</td>
      <td>
        <div class="cell-main">${esc(a.title)}</div>
        <div class="td-sub">${badge(a.assignmentStatus)}</div>
      </td>
      <td class="td-sub" style="white-space:nowrap">${esc(a.dueDate || '–')}</td>
      <td>${badge(a.submitStatus)}</td>
      <td>${a.score == null ? '–' : a.score}</td>
      <td class="td-sub">${esc(a.comment || '–')}</td>
    </tr>`).join('') || emptyRow(6, '暂无作业记录');
}

function renderParentAssignments() {
  const tbody = $('#parent-assignments');
  if (tbody) tbody.innerHTML = parentAssignmentRows();
}

function parentAttendanceHtml() {
  return `
    <div class="card reveal" data-d="4" style="margin-top:16px;margin-bottom:20px">
      <div class="card-head">
        <div class="card-title">${ICONS.clock} 考勤情况</div>
        ${childFilterHtml('parent-att-filter')}
      </div>
      <div class="card-body">
        <div id="parent-att-summary">${attSummaryChips(parentAttendanceList())}</div>
        <div class="table-wrap" style="margin-top:12px"><table>
          <thead><tr><th>学员</th><th>日期</th><th>班级</th><th>考勤状态</th><th>备注</th></tr></thead>
          <tbody id="parent-attendance">${parentAttendanceRows()}</tbody>
        </table></div>
      </div>
    </div>`;
}

function parentAttendanceList() {
  return parentChildFilter
    ? parentAttendance.filter(a => a.studentId === parentChildFilter)
    : parentAttendance;
}

function parentAttendanceRows() {
  return parentAttendanceList().map(a => `
    <tr>
      <td>${esc(a.studentName)}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(a.date || '–')}</td>
      <td>${esc(a.className || '–')}</td>
      <td>${badge(a.status)}</td>
      <td class="td-sub">${esc(a.note || '–')}</td>
    </tr>`).join('') || emptyRow(5, '暂无考勤记录');
}

function renderParentAttendance() {
  const tbody = $('#parent-attendance');
  if (tbody) tbody.innerHTML = parentAttendanceRows();
  const summary = $('#parent-att-summary');
  if (summary) summary.innerHTML = attSummaryChips(parentAttendanceList());
}

/* ---------- 家长 / 学员：缴费明细组件 ---------- */

function parentPaymentsHtml() {
  if (!CHILDREN.length) return emptyState('warn', '暂无关联学员', '请联系机构绑定家长账号');
  const tabs = CHILDREN.length > 1 ? `
    <div class="child-tabs reveal" data-d="2" id="child-tabs" style="margin-top:16px">
      ${CHILDREN.map((k, i) => `<button type="button" class="child-tab ${i === 0 ? 'active' : ''}" data-child="${esc(k.studentId)}">${esc(k.name)}</button>`).join('')}
    </div>` : '';
  return tabs + `<div id="parent-pay" style="margin-top:16px">${payLoadingCard('缴费明细')}</div>`;
}

function initParentPayments() {
  if (!CHILDREN.length) return;
  let current = CHILDREN[0].studentId;
  const box = $('#parent-pay');
  if (box) box.dataset.child = current;

  $$('#child-tabs .child-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.child === current) return;
      current = btn.dataset.child;
      $$('#child-tabs .child-tab').forEach(b => b.classList.toggle('active', b === btn));
      loadParentPayments(current);
    });
  });

  loadParentPayments(current);
}

async function loadParentPayments(studentId) {
  const box = $('#parent-pay');
  if (!box) return;
  box.dataset.child = studentId; // 先登记目标，避免快速切换时旧响应覆盖新内容
  box.innerHTML = payLoadingCard('缴费明细');
  try {
    const data = await api.portalParentPayments(studentId);
    if (box.dataset.child !== studentId) return;
    box.innerHTML = paySection(data, { title: '缴费明细' });
  } catch (e) {
    if (box.dataset.child !== studentId) return;
    box.innerHTML = payErrorCard(e);
  }
}

function payLoadingCard(title) {
  return `<div class="card reveal"><div class="card-head"><div class="card-title">${ICONS.wallet} ${esc(title)}</div></div>
    <div class="card-body">${skeleton(3)}</div></div>`;
}

function payErrorCard(e) {
  return `<div class="card reveal"><div class="card-body">${emptyState('warn', '缴费明细加载失败', e.message || '请稍后重试')}</div></div>`;
}

function paySection(data, { title = '缴费明细' } = {}) {
  const s = data.summary || {};
  const bills = data.bills || [];
  const pays = data.payments || [];
  const stu = data.student || {};
  const sub = [stu.className, stu.courseName].filter(Boolean).join(' · ');

  const summary = `
    <div class="pay-summary">
      ${payCell('应缴', money(s.dueTotal))}
      ${payCell('已缴', money(s.paidTotal), 'success')}
      ${payCell('待确认', money(s.pendingTotal), 'warning')}
      ${payCell('欠费', money(s.outstanding), s.outstanding > 0 ? 'danger' : 'success')}
    </div>`;

  const billRows = bills.map(b => `
    <tr>
      <td>${esc(b.period || '–')}</td>
      <td>${esc(b.courseName || '–')}${b.className ? `<div class="pay-sub">${esc(b.className)}</div>` : ''}</td>
      <td style="text-align:right">${money(b.amount)}</td>
      <td style="text-align:right">${money(b.paidAmount)}</td>
      <td>${badge(b.displayStatus || b.status || '–')}</td>
      <td>${esc(b.dueDate || '–')}</td>
      <td>${esc(b.note || '–')}</td>
    </tr>`).join('') || emptyRow(7, '暂无账单');

  const billTable = `
    <div class="section-label">应收账单</div>
    <div class="table-wrap"><table>
      <thead><tr><th>账期</th><th>课程 / 班级</th><th>应缴</th><th>已缴</th><th>状态</th><th>到期日</th><th>备注</th></tr></thead>
      <tbody>${billRows}</tbody>
    </table></div>`;

  const payRows = pays.map(p => `
    <tr>
      <td>${esc(p.date || '–')}</td>
      <td style="text-align:right">${money(p.amount)}</td>
      <td>${esc(p.method || '–')}</td>
      <td>${badge(p.status || '–')}</td>
      <td>${esc(p.billId || '历史流水')}</td>
      <td>${esc(p.note || '–')}</td>
    </tr>`).join('') || emptyRow(6, '暂无缴费记录');

  const payTable = `
    <div class="section-label">缴费流水</div>
    <div class="table-wrap"><table>
      <thead><tr><th>日期</th><th>金额</th><th>方式</th><th>状态</th><th>关联账单</th><th>备注</th></tr></thead>
      <tbody>${payRows}</tbody>
    </table></div>`;

  return `<div class="card reveal">
    <div class="card-head">
      <div class="card-title">${ICONS.wallet} ${esc(title)}</div>
      ${sub ? `<div class="card-sub">${esc(sub)}</div>` : ''}
    </div>
    <div class="card-body">
      ${summary}
      ${bills.length ? '' : `<div class="pay-note">${ICONS.info}<span>暂无应收账单，以下为历史缴费流水；金额以机构账单为准。</span></div>`}
      ${billTable}
      ${payTable}
    </div>
  </div>`;
}

function payCell(label, value, tone = '') {
  return `<div class="pay-cell"><div class="pay-k">${esc(label)}</div>
    <div class="pay-v ${tone}">${esc(value)}</div></div>`;
}

/* ---------- 员工误入门户 ---------- */

function staffHtml() {
  return `<div class="card reveal" data-d="1"><div class="card-body">
    您是后台管理员，请前往 <a class="card-link" href="dashboard.html">工作台</a> 进行日常管理。
  </div></div>`;
}
