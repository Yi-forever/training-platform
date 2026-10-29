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
let TEACHER_PROPOSALS = [];
let CHILDREN = [];
let parentAssignments = [];
let parentAttendance = [];
let parentChildFilter = '';
let studentCatalog = [];
let studentEnrollments = [];
let parentCatalog = [];
let parentEnrollments = [];
let parentEnrollChild = '';


/* ---------- 课表状态与日期工具 ---------- */
const TT = { start: null, sessions: [], seq: 0, title: '我的课表' };
const TT_WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function ttDate(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function ttAddDays(d, n) { const x = ttDate(d); x.setDate(x.getDate() + n); return x; }
function ttIso(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function ttMonday(d) { const x = ttDate(d); return ttAddDays(x, -((x.getDay() + 6) % 7)); }
function ttShort(iso) { return iso ? iso.slice(5).replace('-', '/') : ''; }

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
  const [assignments, proposals] = await Promise.all([
    api.teacherAssignments(),
    api.teacherCourseProposals().catch(() => []),
  ]);
  ASSIGNMENTS = assignments;
  TEACHER_PROPOSALS = proposals || [];
  el.insertAdjacentHTML('beforeend', teacherStatsHtml());
  el.insertAdjacentHTML('beforeend', timetableHtml('我的课表'));
  el.insertAdjacentHTML('beforeend', teacherClassesHtml());
  el.insertAdjacentHTML('beforeend', teacherProposalsHtml());
  el.insertAdjacentHTML('beforeend', teacherAssignmentsHtml());
  el.insertAdjacentHTML('beforeend', teacherAttendanceHtml());

  $('#btn-new-proposal')?.addEventListener('click', openProposalForm);
  $('#proposal-list')?.addEventListener('click', onProposalAction);
  $('#btn-new-assignment')?.addEventListener('click', () => openAssignmentEditor(null));
  $('#assignment-list')?.addEventListener('click', onAssignmentAction);
  $('#att-class')?.addEventListener('change', loadAttendance);
  $('#att-date')?.addEventListener('change', loadAttendance);
  $('#att-load')?.addEventListener('click', loadAttendance);
  $('#att-save')?.addEventListener('click', saveAttendance);
  $('#btn-att-summary')?.addEventListener('click', openAttendanceSummary);

  await initTimetable('我的课表');
  if (CLASSES.length) await loadAttendance();
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

function teacherProposalsHtml() {
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.filetext} 开课申请</div>
        <button class="btn btn-sm" id="btn-new-proposal">${ICONS.plus} 申请开课</button>
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>课程名称</th><th>分类 / 级别</th><th>课时 / 学费</th><th>意向时间</th><th>状态</th><th>审核意见</th><th>操作</th></tr></thead>
        <tbody id="proposal-list">${teacherProposalRows()}</tbody>
      </table></div></div>
    </div>`;
}

function teacherProposalRows() {
  return TEACHER_PROPOSALS.map(p => `
    <tr>
      <td>
        <div class="cell-main">${esc(p.name)}</div>
        <div class="td-sub clamp-2">${esc(p.target || p.desc || '')}</div>
      </td>
      <td>${esc(p.category)}<div class="td-sub">${esc(p.level || '')}</div></td>
      <td>${p.hours} 课时<div class="td-sub">${money(p.price)}</div></td>
      <td class="td-sub">${esc(p.preferredSchedule || '待定')}</td>
      <td>${badge(p.status)}${p.courseId ? `<div class="td-sub">${esc(p.courseId)}</div>` : ''}</td>
      <td class="td-sub clamp-2">${esc(p.reviewNote || '—')}</td>
      <td class="td-actions">
        ${p.status === '待审核'
          ? `<button class="btn-link danger" data-act="cancel" data-id="${p.id}">${ICONS.x}撤回</button>` : ''}
      </td>
    </tr>`).join('') || emptyRow(7, '还没有开课申请，可点击右上角「申请开课」');
}

async function reloadTeacherProposals() {
  try {
    TEACHER_PROPOSALS = await api.teacherCourseProposals();
  } catch (e) {
    TEACHER_PROPOSALS = [];
  }
  const tbody = $('#proposal-list');
  if (tbody) tbody.innerHTML = teacherProposalRows();
}

function openProposalForm() {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>课程名称<span class="req">*</span></label>
        <input class="input" id="p-name" maxlength="64" placeholder="如：Web 前端进阶：Vue 3 实战">
      </div>
      <div class="form-item">
        <label>课程分类<span class="req">*</span></label>
        <select class="select" id="p-cat">
          <option>Scratch</option><option>Python</option><option>C++</option>
          <option>人工智能</option><option>Web</option><option>机器人</option><option>Java</option><option>其他</option>
        </select>
      </div>
      <div class="form-item">
        <label>课程级别</label>
        <select class="select" id="p-level">
          <option>启蒙</option><option>入门</option><option selected>进阶</option><option>竞赛</option>
        </select>
      </div>
      <div class="form-item">
        <label>课时数<span class="req">*</span></label>
        <input class="input" id="p-hours" type="number" min="1" max="999" placeholder="如：48">
      </div>
      <div class="form-item">
        <label>建议学费（元）<span class="req">*</span></label>
        <input class="input" id="p-price" type="number" min="0" placeholder="如：5600">
      </div>
      <div class="form-item full">
        <label>适学对象</label>
        <input class="input" id="p-target" maxlength="128" placeholder="如：12 岁以上，已掌握 HTML/CSS/JS">
      </div>
      <div class="form-item full">
        <label>意向上课时间</label>
        <input class="input" id="p-schedule" maxlength="128" placeholder="如：周日 14:00-17:00">
      </div>
      <div class="form-item full">
        <label>课程简介</label>
        <textarea class="input" id="p-desc" rows="4" placeholder="课程内容、教学目标与考核方式"></textarea>
      </div>
      <div class="form-item full">
        <div class="td-sub">提交后由教务 / 超管审核；通过后自动创建课程，您将作为课程负责人。</div>
      </div>
    </div>`;
  openPortalModal('申请开课', body, '提交申请', async () => {
    const payload = {
      name: $('#p-name').value.trim(),
      category: $('#p-cat').value,
      level: $('#p-level').value,
      hours: Number($('#p-hours').value),
      price: Number($('#p-price').value),
      target: $('#p-target').value.trim(),
      preferredSchedule: $('#p-schedule').value.trim(),
      desc: $('#p-desc').value.trim(),
    };
    if (!payload.name) { showToast('请填写课程名称', 'error'); return false; }
    if (!payload.hours || payload.hours <= 0) { showToast('请填写正确的课时数', 'error'); return false; }
    if (Number.isNaN(payload.price) || payload.price < 0) { showToast('请填写正确的学费', 'error'); return false; }
    const data = await apiOk(() => api.applyCourseProposal(payload));
    if (!data) return false;
    showToast('开课申请已提交，等待教务审核');
    await reloadTeacherProposals();
    return true;
  });
}

function onProposalAction(e) {
  const btn = e.target.closest('button[data-act="cancel"]');
  if (!btn) return;
  const p = TEACHER_PROPOSALS.find(x => x.id === btn.dataset.id);
  if (!p) return;
  askConfirm('撤回开课申请', `确定撤回「${p.name}」的开课申请吗？撤回后可重新提交。`, async () => {
    if (!await apiOk(() => api.cancelCourseProposal(p.id), '申请已撤回')) return;
    await reloadTeacherProposals();
  });
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

async function openAssignmentEditor(a) {
  if (!CLASSES.length) { showToast('还没有所带班级，无法布置作业', 'error'); return; }
  const isEdit = !!a;
  const options = CLASSES.map(c =>
    `<option value="${c.id}" ${a && a.classId === c.id ? 'selected' : ''}>${esc(c.name)}</option>`
  ).join('');
  const defaultClass = a ? a.classId : CLASSES[0].id;
  let sessions = [];
  try {
    sessions = await api.teacherSessions(defaultClass, {
      from: todayStr(), to: ttIso(ttAddDays(new Date(), 120)),
    });
  } catch (e) { sessions = []; }
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
      <div class="form-item">
        <label>关联课次（可选）</label>
        <select class="select" id="a-session">${sessionOptions(sessions, a && a.sessionId)}</select>
      </div>
      <div class="form-item">
        <label>迟交设置</label>
        <label class="check-line"><input type="checkbox" id="a-late" ${a && a.allowLate ? 'checked' : ''}> 允许截止后补交</label>
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
      sessionId: $('#a-session').value || null,
      allowLate: $('#a-late').checked,
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
  $('#a-class')?.addEventListener('change', async ev => {
    const sel = $('#a-session');
    if (!sel) return;
    sel.innerHTML = '<option value="">加载中…</option>';
    try {
      const rows = await api.teacherSessions(ev.target.value, {
        from: todayStr(), to: ttIso(ttAddDays(new Date(), 120)),
      });
      sel.innerHTML = sessionOptions(rows, '');
    } catch (e) {
      sel.innerHTML = '<option value="">暂无可关联课次</option>';
    }
  });
}

function sessionOptions(sessions, selected) {
  const opts = (sessions || [])
    .filter(s => s.status !== '已取消')
    .map(s => `<option value="${s.id}" ${s.id === selected ? 'selected' : ''}>${esc(s.sessionDate)} ${esc(s.startTime)} · ${esc(s.className || '')}</option>`)
    .join('');
  return `<option value="">不关联课次</option>${opts}`;
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
      <td>${badge(r.status)}${r.returnReason ? `<div class="td-sub">退回：${esc(r.returnReason)}</div>` : ''}</td>
      <td class="td-sub">${esc(r.submittedAt || '–')}</td>
      <td>${r.score == null ? '–' : r.score}</td>
      <td class="td-sub">${esc(r.comment || '–')}</td>
      <td class="td-actions">
        ${!r.submissionId
          ? '<span class="td-sub">等待提交</span>'
          : r.status === '已退回'
            ? '<span class="td-sub">等待重交</span>'
            : `<button class="btn-link" data-sub="${r.submissionId}">${ICONS.edit}${r.status === '已批改' ? '重新批改' : '批改'}</button>`}
        ${r.submissionId && r.status === '已批改'
          ? `<button class="btn-link danger" data-return="${r.submissionId}">${ICONS.refresh}退回</button>` : ''}
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
    const ret = ev.target.closest('button[data-return]');
    if (ret) {
      const row = data.rows.find(x => x.submissionId === ret.dataset.return);
      if (row) openReturnForm(a, row);
      return;
    }
    const b = ev.target.closest('button[data-sub]');
    if (!b) return;
    const row = data.rows.find(x => x.submissionId === b.dataset.sub);
    if (row) openGradeForm(a, row);
  });
}

function openReturnForm(a, row) {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>${esc(row.studentName)} 的退回理由<span class="req">*</span></label>
        <textarea class="input" id="r-reason" rows="3" maxlength="100"
          placeholder="说明需要修改的地方（学员与家长可见，原成绩将作废）"></textarea>
      </div>
    </div>`;
  openPortalModal(`退回作业 · ${row.studentName}`, body, '确认退回', async () => {
    const reason = $('#r-reason').value.trim();
    if (reason.length < 2) { showToast('请填写退回理由（至少 2 个字）', 'error'); return false; }
    const ok = await apiOk(() => api.returnSubmission(row.submissionId, reason), '已退回，等待学员重交');
    if (!ok) return false;
    await reloadTeacherAssignments();
    await openSubmissions(a);
    return false;
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

/* ---------- 教师：班级考勤统计 ---------- */

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

/* ============================================================
 * 学员
 * ============================================================ */

async function initStudent(el) {
  const [assignments, attendance, catalog, enrollments] = await Promise.all([
    api.studentAssignments(),
    api.studentAttendance(),
    api.catalog(),
    api.myEnrollments(),

  ]);
  studentCatalog = catalog;
  studentEnrollments = enrollments;
  el.insertAdjacentHTML('beforeend', studentStatsHtml());
  el.insertAdjacentHTML('beforeend', studentInfoHtml());
  el.insertAdjacentHTML('beforeend', timetableHtml('我的课表'));
  el.insertAdjacentHTML('beforeend', studentCatalogHtml());
  el.insertAdjacentHTML('beforeend', studentEnrollmentsHtml());

  el.insertAdjacentHTML('beforeend', `<div id="student-pay" style="margin-top:16px">${payLoadingCard('缴费明细')}</div>`);
  el.insertAdjacentHTML('beforeend', studentAssignmentsHtml(assignments));
  el.insertAdjacentHTML('beforeend', studentAttendanceHtml(attendance));
  $('#student-assignments')?.addEventListener('click', onStudentAssignmentAction);
  $('#student-catalog')?.addEventListener('click', onStudentCatalogAction);
  $('#student-enrollments')?.addEventListener('click', onStudentEnrollmentAction);
  $('#catalog-cat')?.addEventListener('change', renderStudentCatalog);
  window.__studentAssignments = assignments;
  await loadStudentPayments();
  await initTimetable('我的课表');
}

/* ---------- 学员：选课中心 / 我的选课 ---------- */

function enrollSeatHtml(c) {
  const pct = c.capacity ? Math.min(100, Math.round(c.enrolled / c.capacity * 100)) : 0;
  return `<div style="min-width:110px">
    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
      <span style="font-weight:600;${c.isFull ? 'color:var(--danger)' : ''}">余 ${c.remaining} 个</span>
      <span class="td-sub">${c.enrolled}/${c.capacity}</span>
    </div>
    <div class="progress"><span style="width:${pct}%"></span></div>
  </div>`;
}

function enrollStatusHtml(c) {
  if (c.myStatus) {
    const wait = c.myStatus === '候补' && c.waitlistNo ? ` <span class="td-sub">第 ${c.waitlistNo} 位</span>` : '';
    return badge(c.myStatus) + wait;
  }
  if (c.conflictClassName) return '<span class="badge badge-warning">时间冲突</span>';
  return '<span class="td-sub">可报名</span>';
}

function studentCatalogRows() {
  const cat = $('#catalog-cat')?.value || '';
  const list = cat ? studentCatalog.filter(c => c.category === cat) : studentCatalog;
  return list.map(c => `
    <tr>
      <td>
        <div class="cell-main">${esc(c.courseName)}</div>
        <div class="td-sub">${esc(c.className)} · ${esc(c.level || '')}</div>
      </td>
      <td style="white-space:nowrap">${esc(c.teacherName || '—')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(c.schedule || '排课待定')}<br>${esc(c.classroom || '')}</td>
      <td>${enrollSeatHtml(c)}</td>
      <td style="white-space:nowrap">${money(c.price)}<div class="td-sub">${c.hours} 课时</div></td>
      <td>${enrollStatusHtml(c)}</td>
      <td class="td-actions">
        ${c.canApply
          ? `<button class="btn-link" data-act="apply" data-id="${esc(c.classId)}">${ICONS.plus}${c.isFull ? '候补' : '选课'}</button>`
          : (c.conflictClassName ? `<span class="td-sub">与「${esc(c.conflictClassName)}」冲突</span>` : '')}
      </td>
    </tr>`).join('') || emptyRow(7, '暂无可选班级');
}

function studentCatalogHtml() {
  const cats = [...new Set(studentCatalog.map(c => c.category).filter(Boolean))];
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.userplus} 选课中心</div>
        <select class="select" id="catalog-cat" style="width:180px">
          <option value="">全部课程方向</option>
          ${cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}
        </select>
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>课程 / 班级</th><th>教师</th><th>上课时间</th><th>剩余名额</th><th>学费</th><th>我的状态</th><th>操作</th></tr></thead>
        <tbody id="student-catalog">${studentCatalogRows()}</tbody>
      </table></div></div>
    </div>`;
}

function studentEnrollmentRows() {
  return studentEnrollments.map(e => `
    <tr>
      <td>
        <div class="cell-main">${esc(e.className || '—')}</div>
        <div class="td-sub">${esc(e.courseName || '')}</div>
      </td>
      <td class="td-sub" style="white-space:nowrap">${esc(e.schedule || '—')}</td>
      <td>${badge(e.status)}${e.status === '候补' && e.waitlistNo ? ` <span class="td-sub">第 ${e.waitlistNo} 位</span>` : ''}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(String(e.createdAt || '').slice(0, 10))}</td>
      <td class="td-sub clamp-2">${esc(e.reviewNote || '—')}</td>
      <td class="td-actions">
        ${['待审核', '候补', '已通过'].includes(e.status)
          ? `<button class="btn-link danger" data-act="withdraw" data-id="${e.id}">${ICONS.x}退课</button>` : ''}
      </td>
    </tr>`).join('') || emptyRow(6, '还没有选课记录，可在上方选课中心申请');
}

function studentEnrollmentsHtml() {
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.filetext} 我的选课</div></div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>班级</th><th>上课时间</th><th>状态</th><th>申请时间</th><th>审核意见</th><th>操作</th></tr></thead>
        <tbody id="student-enrollments">${studentEnrollmentRows()}</tbody>
      </table></div></div>
    </div>`;
}

function renderStudentCatalog() {
  const tbody = $('#student-catalog');
  if (tbody) tbody.innerHTML = studentCatalogRows();
}

function renderStudentEnrollments() {
  const tbody = $('#student-enrollments');
  if (tbody) tbody.innerHTML = studentEnrollmentRows();
}

async function reloadStudentEnrollments() {
  const [catalog, enrollments] = await Promise.all([api.catalog(), api.myEnrollments()]);
  studentCatalog = catalog;
  studentEnrollments = enrollments;
  renderStudentCatalog();
  renderStudentEnrollments();
}

function onStudentCatalogAction(e) {
  const btn = e.target.closest('button[data-act="apply"]');
  if (!btn) return;
  const cls = studentCatalog.find(c => c.classId === btn.dataset.id);
  if (!cls) return;
  openApplyForm(cls, {
    apply: note => api.applyEnrollment({ classId: cls.classId, note }),
    after: reloadStudentEnrollments,
  });
}

function onStudentEnrollmentAction(e) {
  const btn = e.target.closest('button[data-act="withdraw"]');
  if (!btn) return;
  const row = studentEnrollments.find(x => x.id === btn.dataset.id);
  if (!row) return;
  askConfirm('退课确认',
    `确定退出「${row.className}」吗？退课后该班名额将释放给候补学员。`,
    async () => {
      const data = await apiOk(() => api.withdrawEnrollment(row.id), '已退课');
      if (!data) return;
      await reloadStudentEnrollments();
    });
}

/* 选课申请弹窗（学员 / 家长共用；payload 由调用方给出） */
function openApplyForm(cls, extra) {
  const body = `
    <div class="form-grid">
      <div class="form-item full">
        <label>选课班级</label>
        <div class="input" style="height:auto;background:var(--bg-soft)">
          <b>${esc(cls.className)}</b>
          <div class="td-sub">${esc(cls.courseName)} · ${esc(cls.teacherName || '教师待定')} · ${esc(cls.schedule || '排课待定')}</div>
        </div>
      </div>
      <div class="form-item">
        <label>学费</label>
        <div style="font-size:20px;font-weight:600">${money(cls.price)}</div>
      </div>
      <div class="form-item">
        <label>剩余名额</label>
        <div style="font-size:20px;font-weight:600;${cls.isFull ? 'color:var(--danger)' : ''}">${cls.remaining} / ${cls.capacity}</div>
      </div>
      <div class="form-item full">
        <label>备注（选填）</label>
        <input class="input" id="en-note" maxlength="100" placeholder="如：希望老师多关注基础部分">
      </div>
      ${cls.isFull ? `<div class="form-item full"><div class="td-sub">该班名额已满，提交后将进入候补，名额释放时按顺位自动转正。</div></div>` : ''}
    </div>`;
  openPortalModal('提交选课申请', body, cls.isFull ? '加入候补' : '提交申请', async () => {
    const note = $('#en-note').value.trim();
    const data = await apiOk(() => extra.apply(note));
    if (!data) return false;
    showToast(data.message || '选课申请已提交');
    if (extra.after) await extra.after();
    return true;
  });
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
          <div><span class="kv-k">班级</span><span class="kv-v">${esc(CTX.className || '待分班')}</span></div>
          <div><span class="kv-k">课程</span><span class="kv-v">${esc(CTX.courseName || '–')}</span></div>
          <div><span class="kv-k">带班教师</span><span class="kv-v">${esc(CTX.teacherName || '–')}</span></div>
          <div><span class="kv-k">上课时间</span><span class="kv-v">${esc(CTX.schedule || '–')}</span></div>
          ${(CTX.classNames || []).length > 1
            ? `<div><span class="kv-k">兼报班级</span><span class="kv-v">${esc(CTX.classNames.slice(1).join('、'))}</span></div>`
            : ''}
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
  return assignments.map(a => {
    const overdue = !!a.dueDate && todayStr() > a.dueDate && !a.allowLate;
    const canSubmit = a.status === '进行中' && a.submitStatus !== '已批改' && !overdue;
    return `
    <tr>
      <td>
        <div class="cell-main">${esc(a.title)}</div>
        <div class="td-sub clamp-2">${esc(a.content || '')}</div>
      </td>
      <td style="white-space:nowrap">${esc(a.teacherName || '–')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(a.dueDate || '–')}${a.allowLate ? '<div class="td-sub">允许迟交</div>' : ''}</td>
      <td>${badge(a.status)}</td>
      <td>${badge(a.submitStatus)}${a.returnReason ? `<div class="td-sub">退回：${esc(a.returnReason)}</div>` : ''}</td>
      <td>${a.score == null ? '–' : a.score}</td>
      <td class="td-actions">
        ${canSubmit
          ? `<button class="btn-link" data-act="submit" data-id="${a.id}">${ICONS.edit}${a.submissionId ? '重新提交' : '提交作业'}</button>`
          : (overdue && a.submitStatus !== '已批改' ? '<span class="td-sub">已截止</span>' : '')}
        ${a.submitStatus === '已批改'
          ? `<button class="btn-link success" data-act="view" data-id="${a.id}">${ICONS.eye}查看批改</button>`
          : ''}
      </td>
    </tr>`;
  }).join('') || emptyRow(7, '本班暂无作业');
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
      ${a.returnReason ? `
      <div class="form-item full">
        <label>教师退回理由</label>
        <div class="input" style="height:auto;white-space:pre-wrap;background:var(--danger-bg);color:var(--danger)">${esc(a.returnReason)}</div>
      </div>` : ''}
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
  parentEnrollChild = CHILDREN.length ? CHILDREN[0].studentId : '';
  [parentAssignments, parentAttendance, parentEnrollments, parentCatalog] = await Promise.all([
    api.parentAssignments(),
    api.parentAttendance(),
    api.parentEnrollments(),
    parentEnrollChild ? api.catalog(parentEnrollChild) : Promise.resolve([]),
  ]);
  el.insertAdjacentHTML('beforeend', parentStatsHtml());
  el.insertAdjacentHTML('beforeend', parentChildrenHtml());
  el.insertAdjacentHTML('beforeend', parentEnrollCatalogHtml());
  el.insertAdjacentHTML('beforeend', parentEnrollmentsHtml());
  el.insertAdjacentHTML('beforeend', timetableHtml('孩子课表'));

  el.insertAdjacentHTML('beforeend', parentPaymentsHtml());
  el.insertAdjacentHTML('beforeend', parentAssignmentsHtml());
  el.insertAdjacentHTML('beforeend', parentAttendanceHtml());
  $('#parent-assign-filter')?.addEventListener('change', e => {
    parentChildFilter = e.target.value;
    renderParentAssignments();
  });
  $('#parent-att-filter')?.addEventListener('change', e => {
    parentChildFilter = e.target.value;
    renderParentAttendance();
  });
  $('#parent-enroll-filter')?.addEventListener('change', async e => {
    parentEnrollChild = e.target.value;
    await loadParentCatalog();
  });
  $('#parent-catalog')?.addEventListener('click', onParentCatalogAction);
  $('#parent-enrollments')?.addEventListener('click', onParentEnrollmentAction);
  initParentPayments();

  await initTimetable('孩子课表');

}

/* ---------- 家长：孩子选课 ---------- */

function parentEnrollCatalogRows() {
  return parentCatalog.map(c => `
    <tr>
      <td>
        <div class="cell-main">${esc(c.courseName)}</div>
        <div class="td-sub">${esc(c.className)} · ${esc(c.level || '')}</div>
      </td>
      <td style="white-space:nowrap">${esc(c.teacherName || '—')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(c.schedule || '排课待定')}<br>${esc(c.classroom || '')}</td>
      <td>${enrollSeatHtml(c)}</td>
      <td style="white-space:nowrap">${money(c.price)}<div class="td-sub">${c.hours} 课时</div></td>
      <td>${enrollStatusHtml(c)}</td>
      <td class="td-actions">
        ${c.canApply
          ? `<button class="btn-link" data-act="apply" data-id="${esc(c.classId)}">${ICONS.plus}${c.isFull ? '候补' : '为TA报名'}</button>`
          : (c.conflictClassName ? `<span class="td-sub">与「${esc(c.conflictClassName)}」冲突</span>` : '')}
      </td>
    </tr>`).join('') || emptyRow(7, '暂无可选班级');
}

function parentEnrollCatalogHtml() {
  const options = CHILDREN.map(c =>
    `<option value="${esc(c.studentId)}" ${c.studentId === parentEnrollChild ? 'selected' : ''}>${esc(c.name)}</option>`
  ).join('');
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">${ICONS.userplus} 孩子选课</div>
        ${CHILDREN.length > 1
          ? `<select class="select" id="parent-enroll-filter" style="width:180px">${options}</select>`
          : `<div class="td-sub">${esc((CHILDREN[0] || {}).name || '')}</div>`}
      </div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>课程 / 班级</th><th>教师</th><th>上课时间</th><th>剩余名额</th><th>学费</th><th>选课状态</th><th>操作</th></tr></thead>
        <tbody id="parent-catalog">${parentEnrollCatalogRows()}</tbody>
      </table></div></div>
    </div>`;
}

function parentEnrollmentRows() {
  return parentEnrollments.map(e => `
    <tr>
      <td>${esc(e.studentName || e.studentId)}</td>
      <td>
        <div class="cell-main">${esc(e.className || '—')}</div>
        <div class="td-sub">${esc(e.courseName || '')}</div>
      </td>
      <td class="td-sub" style="white-space:nowrap">${esc(e.schedule || '—')}</td>
      <td>${badge(e.status)}${e.status === '候补' && e.waitlistNo ? ` <span class="td-sub">第 ${e.waitlistNo} 位</span>` : ''}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(String(e.createdAt || '').slice(0, 10))}</td>
      <td class="td-sub clamp-2">${esc(e.reviewNote || '—')}</td>
      <td class="td-actions">
        ${['待审核', '候补', '已通过'].includes(e.status)
          ? `<button class="btn-link danger" data-act="withdraw" data-id="${e.id}">${ICONS.x}退课</button>` : ''}
      </td>
    </tr>`).join('') || emptyRow(7, '暂无选课记录');
}

function parentEnrollmentsHtml() {
  return `
    <div class="card reveal" data-d="3" style="margin-top:16px">
      <div class="card-head"><div class="card-title">${ICONS.filetext} 选课记录</div></div>
      <div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>学员</th><th>班级</th><th>上课时间</th><th>状态</th><th>申请时间</th><th>审核意见</th><th>操作</th></tr></thead>
        <tbody id="parent-enrollments">${parentEnrollmentRows()}</tbody>
      </table></div></div>
    </div>`;
}

function renderParentCatalog() {
  const tbody = $('#parent-catalog');
  if (tbody) tbody.innerHTML = parentEnrollCatalogRows();
}

function renderParentEnrollments() {
  const tbody = $('#parent-enrollments');
  if (tbody) tbody.innerHTML = parentEnrollmentRows();
}

async function loadParentCatalog() {
  const tbody = $('#parent-catalog');
  if (tbody) tbody.innerHTML = emptyRow(7, '加载中…');
  try {
    parentCatalog = parentEnrollChild ? await api.catalog(parentEnrollChild) : [];
  } catch (e) {
    showToast(e.message, 'error');
    parentCatalog = [];
  }
  renderParentCatalog();
}

async function reloadParentEnrollments() {
  const [enrollments, catalog] = await Promise.all([
    api.parentEnrollments(),
    parentEnrollChild ? api.catalog(parentEnrollChild) : Promise.resolve([]),
  ]);
  parentEnrollments = enrollments;
  parentCatalog = catalog;
  renderParentCatalog();
  renderParentEnrollments();
}

function onParentCatalogAction(e) {
  const btn = e.target.closest('button[data-act="apply"]');
  if (!btn) return;
  if (!parentEnrollChild) { showToast('请先选择学员', 'error'); return; }
  const cls = parentCatalog.find(c => c.classId === btn.dataset.id);
  if (!cls) return;
  openApplyForm(cls, {
    apply: note => api.parentApplyEnrollment({
      studentId: parentEnrollChild,
      classId: cls.classId,
      note,
    }),
    after: reloadParentEnrollments,
  });
}

function onParentEnrollmentAction(e) {
  const btn = e.target.closest('button[data-act="withdraw"]');
  if (!btn) return;
  const row = parentEnrollments.find(x => x.id === btn.dataset.id);
  if (!row) return;
  askConfirm('退课确认',
    `确定为「${row.studentName}」退出「${row.className}」吗？名额将释放给候补学员。`,
    async () => {
      const data = await apiOk(() => api.parentWithdrawEnrollment(row.id), '已退课');
      if (!data) return;
      await reloadParentEnrollments();
    });
}


function parentStatsHtml() {
  const pending = parentAssignments.filter(a => a.assignmentStatus === '进行中'
    && (a.submitStatus === '未提交' || a.submitStatus === '已退回')).length;
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
      <td>${badge(a.submitStatus)}${a.returnReason ? `<div class="td-sub">退回：${esc(a.returnReason)}</div>` : ''}</td>
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
        ${attSummaryChips(parentAttendance)}
        <div class="table-wrap" style="margin-top:12px"><table>
          <thead><tr><th>学员</th><th>日期</th><th>班级</th><th>考勤状态</th><th>备注</th></tr></thead>
          <tbody id="parent-attendance">${parentAttendanceRows()}</tbody>
        </table></div>
      </div>
    </div>`;
}

function parentAttendanceRows() {
  const list = parentChildFilter
    ? parentAttendance.filter(a => a.studentId === parentChildFilter)
    : parentAttendance;
  return list.map(a => `
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

/* ============================================================
 * 课表（教师 / 学员 / 家长共用周视图）
 * ============================================================ */

function timetableHtml(title) {
  return `
    <div class="card reveal" data-d="2" style="margin-top:16px" id="timetable-card">
      <div class="card-head">
        <div class="card-title">${ICONS.calendar} ${esc(title)}</div>
        <div class="tt-nav">
          <button class="btn btn-ghost btn-sm" id="tt-prev" type="button">‹ 上一周</button>
          <span class="tt-range" id="tt-range">–</span>
          <button class="btn btn-ghost btn-sm" id="tt-next" type="button">下一周 ›</button>
          <button class="btn btn-outline btn-sm" id="tt-today" type="button">本周</button>
        </div>
      </div>
      <div class="card-body"><div class="timetable" id="tt-grid">${skeleton(3)}</div></div>
    </div>`;
}

async function initTimetable(title) {
  const card = $('#timetable-card');
  if (!card) return;
  TT.title = title || '我的课表';
  TT.start = ttMonday(new Date());
  $('#tt-prev').addEventListener('click', () => ttShift(-7));
  $('#tt-next').addEventListener('click', () => ttShift(7));
  $('#tt-today').addEventListener('click', () => { TT.start = ttMonday(new Date()); loadTimetable(); });
  $('#tt-grid').addEventListener('click', e => {
    const el = e.target.closest('.tt-session');
    if (el) openSessionDetail(el.dataset.id);
  });
  await loadTimetable();
}

function ttShift(days) {
  TT.start = ttAddDays(TT.start, days);
  loadTimetable();
}

async function loadTimetable() {
  const from = ttIso(TT.start);
  const to = ttIso(ttAddDays(TT.start, 6));
  const rangeEl = $('#tt-range');
  if (rangeEl) rangeEl.textContent = `${from} ~ ${to}`;
  const seq = ++TT.seq;
  const identity = CTX.identity || USER.identity;
  let sessions = [];
  try {
    if (identity === 'teacher') {
      sessions = (await api.teacherTimetable({ from, to })).sessions || [];
    } else if (identity === 'student') {
      sessions = (await api.studentTimetable({ from, to })).sessions || [];
    } else if (identity === 'parent') {
      const groups = await Promise.all(CHILDREN.map(async c => {
        try {
          const data = await api.parentTimetable(c.studentId, { from, to });
          return (data.sessions || []).map(s => ({ ...s, studentName: c.name }));
        } catch (e) { return []; }
      }));
      sessions = groups.flat();
    }
  } catch (e) {
    if (seq === TT.seq && $('#tt-grid')) {
      $('#tt-grid').innerHTML = emptyState('warn', '课表加载失败', e.message);
    }
    return;
  }
  if (seq !== TT.seq) return;
  TT.sessions = sessions;
  renderTimetable();
}

function renderTimetable() {
  const grid = $('#tt-grid');
  if (!grid) return;
  const today = todayStr();
  grid.innerHTML = TT_WEEKDAYS.map((label, i) => {
    const iso = ttIso(ttAddDays(TT.start, i));
    const list = TT.sessions
      .filter(s => s.sessionDate === iso)
      .sort((a, b) => (a.startTime || '').localeCompare(b.startTime || ''));
    return `
      <div class="tt-day ${iso === today ? 'today' : ''}">
        <div class="tt-day-head"><span>${label}</span><b>${ttShort(iso)}</b></div>
        <div class="tt-day-body">${list.length ? list.map(ttSessionCard).join('') : '<div class="tt-empty">无课</div>'}</div>
      </div>`;
  }).join('');
}

function ttSessionCard(s) {
  const status = s.status || '待上课';
  const cls = status === '已取消' ? 'cancelled'
    : status === '已调课' ? 'rescheduled'
      : status === '已上课' ? 'done' : '';
  return `
    <div class="tt-session ${cls}" data-id="${esc(s.id)}" title="点击查看详情">
      <div class="tt-time">${esc(s.startTime || '')}-${esc(s.endTime || '')}</div>
      <div class="tt-name">${esc(s.className || '')}</div>
      <div class="tt-sub">${esc(s.classroom || '教室待定')} · ${esc(s.teacherName || '')}</div>
      <div class="tt-foot">${badge(status)}${s.homeworkCount ? `<span class="tt-hw">作业 ${s.homeworkCount}</span>` : ''}</div>
      ${s.originalDate ? `<div class="tt-sub">原 ${esc(s.originalDate)} ${esc(s.originalStartTime || '')}</div>` : ''}
      ${s.studentName ? `<div class="tt-student">${esc(s.studentName)}</div>` : ''}
    </div>`;
}

function openSessionDetail(id) {
  const s = TT.sessions.find(x => x.id === id);
  if (!s) return;
  const body = `
    <div class="tt-detail">
      <div><div class="k">班级</div><div class="v">${esc(s.className || '–')}</div></div>
      <div><div class="k">课程</div><div class="v">${esc(s.courseName || '–')}</div></div>
      <div><div class="k">日期</div><div class="v">${esc(s.sessionDate)} ${esc(s.weekdayLabel || '')}</div></div>
      <div><div class="k">时间</div><div class="v">${esc(s.startTime)}-${esc(s.endTime)}</div></div>
      <div><div class="k">教师</div><div class="v">${esc(s.teacherName || '–')}</div></div>
      <div><div class="k">教室</div><div class="v">${esc(s.classroom || '–')}</div></div>
      <div><div class="k">状态</div><div class="v">${badge(s.status)}</div></div>
      <div><div class="k">关联作业</div><div class="v">${s.homeworkCount ? s.homeworkCount + ' 项' : '暂无'}</div></div>
      ${s.studentName ? `<div><div class="k">学员</div><div class="v">${esc(s.studentName)}</div></div>` : ''}
      ${s.originalDate ? `<div><div class="k">原时间</div><div class="v">${esc(s.originalDate)} ${esc(s.originalStartTime || '')}</div></div>` : ''}
    </div>
    ${(CTX.identity || USER.identity) === 'teacher' && s.status !== '已取消'
      ? '<div style="margin-top:14px"><button class="btn btn-outline" id="tt-go-att">去考勤</button></div>' : ''}`;
  openPortalModal('课次详情', body, '', async () => true);
  $('#tt-go-att')?.addEventListener('click', () => {
    const classSelect = $('#att-class');
    const dateInput = $('#att-date');
    if (classSelect) classSelect.value = s.classId;
    if (dateInput) dateInput.value = s.sessionDate;
    closeModal('portal-modal');
    loadAttendance();
    $('#att-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

/* ---------- 员工误入门户 ---------- */

function staffHtml() {
  return `<div class="card reveal" data-d="1"><div class="card-body">
    您是后台管理员，请前往 <a class="card-link" href="dashboard.html">工作台</a> 进行日常管理。
  </div></div>`;
}
