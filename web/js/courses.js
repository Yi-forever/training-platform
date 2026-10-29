/* ============================================================
 * courses.js —— 课程管理：列表 / 搜索筛选 / 新增编辑 / 上下架 / 删除
 *               + 教师开课申请审核（超管 / 教务）
 * 数据来源：/api/v1/courses、/api/v1/course-proposals（boot 后缓存于 DB.courses）
 * ============================================================ */

let currentEditId = null;
let canWrite = false;     // 课程写操作：超管 / 教务
let canReview = false;    // 开课申请审核：超管 / 教务
let PROPOSALS = [];
let rejectId = null;

document.addEventListener('DOMContentLoaded', async () => {
  const user = await boot('courses');
  if (!user) return;

  canWrite = canManageAcademic(user);
  canReview = hasRole(user, '超级管理员', '教务管理员');
  if (!canWrite) $('#btn-add').style.display = 'none';
  if (canReview) $('#proposal-card').style.display = '';

  $('#kw').addEventListener('input', renderTable);
  $('#f-category').addEventListener('change', renderTable);
  $('#f-status').addEventListener('change', renderTable);
  $('#btn-add').addEventListener('click', () => openEditor(null));
  $('#btn-submit').addEventListener('click', submitForm);
  $('#tbody').addEventListener('click', onTableClick);
  $('#p-status')?.addEventListener('change', renderProposals);
  $('#proposal-body')?.addEventListener('click', onProposalAction);
  $('#btn-reject')?.addEventListener('click', submitReject);

  renderTable();
  if (canReview) await loadProposals();
});

/* ---------- 课程列表 ---------- */
function getFiltered() {
  const kw = $('#kw').value.trim().toLowerCase();
  const cat = $('#f-category').value;
  const st = $('#f-status').value;
  return DB.courses.filter(c =>
    (!kw || c.name.toLowerCase().includes(kw) || c.id.toLowerCase().includes(kw)
      || String(c.teacherName || '').toLowerCase().includes(kw)) &&
    (!cat || c.category === cat) &&
    (!st || c.status === st)
  );
}

function renderTable() {
  const list = getFiltered();
  $('#count').textContent = list.length;
  $('#tbody').innerHTML = list.length ? list.map(c => `
    <tr>
      <td class="td-sub">${esc(c.id)}</td>
      <td>
        <div class="cell-main">${esc(c.name)}</div>
        <div class="td-sub">${esc(c.target || '')}</div>
      </td>
      <td>${c.teacherName ? esc(c.teacherName) : '<span class="td-sub">未指定</span>'}</td>
      <td>${esc(c.category)}</td>
      <td>${esc(c.level)}</td>
      <td>${c.hours} 课时</td>
      <td style="font-weight:600;color:var(--primary)">${money(c.price)}</td>
      <td>${badge(c.status)}</td>
      <td class="td-actions">
        ${canWrite ? `
        <button class="btn-link" data-act="edit" data-id="${c.id}">${ICONS.edit}编辑</button>
        <button class="btn-link ${c.status === '在售' ? 'danger' : 'success'}" data-act="toggle" data-id="${c.id}">
          ${c.status === '在售' ? '停售' : '上架'}
        </button>
        <button class="btn-link danger" data-act="del" data-id="${c.id}">${ICONS.trash}删除</button>` : ''}
      </td>
    </tr>`).join('') : emptyRow(9, '没有符合条件的课程');
}

/* ---------- 行操作 ---------- */
async function onTableClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const { act, id } = btn.dataset;
  const c = byId(DB.courses, id);
  if (!c) return;

  if (act === 'edit') {
    openEditor(c);
  } else if (act === 'toggle') {
    const next = c.status === '在售' ? '停售' : '在售';
    if (!await apiOk(() => api.update('courses', id, { status: next }))) return;
    await hydrate(); renderTable();
    showToast(next === '在售' ? `课程「${c.name}」已上架` : `课程「${c.name}」已停售`);
  } else if (act === 'del') {
    // 是否被班级使用等业务校验由后端执行（冲突返回 409 并提示原因）
    askConfirm('删除课程', `确定删除课程「${c.name}」吗？删除后不可恢复。`, async () => {
      if (!await apiOk(() => api.remove('courses', id))) return;
      await hydrate(); renderTable();
      showToast('课程已删除');
    });
  }
}

/* ---------- 新增 / 编辑 ---------- */
function fillTeacherSelect(selected) {
  const options = DB.teachers
    .filter(t => t.status === '在职')
    .map(t => `<option value="${t.id}">${esc(t.name)}（${esc(t.subject)} · ${esc(t.title)}）</option>`)
    .join('');
  $('#f-teacher').innerHTML = `<option value="">暂不指定</option>${options}`;
  $('#f-teacher').value = selected || '';
}

function openEditor(c) {
  currentEditId = c ? c.id : null;
  $('#modal-title').textContent = c ? '编辑课程' : '新增课程';
  $('#f-name').value = c ? c.name : '';
  $('#f-cat').value = c ? c.category : 'Scratch';
  $('#f-level').value = c ? c.level : '入门';
  $('#f-hours').value = c ? c.hours : '';
  $('#f-price').value = c ? c.price : '';
  $('#f-target').value = c ? (c.target || '') : '';
  $('#f-status-edit').value = c ? c.status : '在售';
  $('#f-desc').value = c ? (c.desc || '') : '';
  fillTeacherSelect(c ? (c.teacherId || '') : '');
  openModal('editor-modal');
  $('#f-name').focus();
}

async function submitForm() {
  const name = $('#f-name');
  const hours = $('#f-hours');
  const price = $('#f-price');
  if (!valid([[name, '课程名称'], [hours, '课时数'], [price, '学费']])) return;
  if (Number(hours.value) <= 0 || Number(price.value) < 0) { showToast('请输入正确的课时与学费', 'error'); return; }

  const isEdit = !!currentEditId;
  const data = {
    name: name.value.trim(),
    category: $('#f-cat').value,
    level: $('#f-level').value,
    hours: Number(hours.value),
    price: Number(price.value),
    target: $('#f-target').value.trim(),
    status: $('#f-status-edit').value,
    desc: $('#f-desc').value.trim(),
    teacherId: $('#f-teacher').value || null
  };

  if (!await apiOk(() => isEdit ? api.update('courses', currentEditId, data) : api.create('courses', data))) return;
  await hydrate();
  closeModal('editor-modal');
  renderTable();
  showToast(isEdit ? '课程信息已更新' : `课程「${data.name}」创建成功`);
}

/* ---------- 开课申请 ---------- */
async function loadProposals() {
  try {
    // 一次取回全部申请，状态筛选在前端完成（切换筛选无需重新请求）
    const data = await api.courseProposals();
    PROPOSALS = (data && data.list) || [];
  } catch (e) {
    showToast(e.message, 'error');
    PROPOSALS = [];
  }
  renderProposals();
}

function renderProposals() {
  const status = $('#p-status')?.value || '';
  const list = status ? PROPOSALS.filter(p => p.status === status) : PROPOSALS;
  const pending = PROPOSALS.filter(p => p.status === '待审核').length;
  const counter = $('#proposal-pending');
  if (counter) counter.textContent = pending;

  $('#proposal-body').innerHTML = list.length ? list.map(p => `
    <tr>
      <td>
        <div class="cell-main">${esc(p.teacherName || p.teacherId)}</div>
        <div class="td-sub">${esc(p.teacherSubject || '')}</div>
      </td>
      <td>
        <div class="cell-main">${esc(p.name)}</div>
        <div class="td-sub clamp-2">${esc(p.target || p.desc || '')}</div>
      </td>
      <td>${esc(p.category)}<div class="td-sub">${esc(p.level || '')}</div></td>
      <td>${p.hours} 课时<div class="td-sub">${money(p.price)}</div></td>
      <td class="td-sub">${esc(p.preferredSchedule || '待定')}</td>
      <td class="td-sub" style="white-space:nowrap">${esc(String(p.createdAt || '').slice(0, 10))}</td>
      <td>${badge(p.status)}${p.courseId ? `<div class="td-sub">${esc(p.courseId)}</div>` : ''}</td>
      <td class="td-sub clamp-2">${esc(p.reviewNote || '—')}</td>
      <td class="td-actions">
        ${p.status === '待审核' ? `
          <button class="btn-link success" data-act="approve" data-id="${p.id}">${ICONS.check}通过</button>
          <button class="btn-link danger" data-act="reject" data-id="${p.id}">${ICONS.x}驳回</button>` : ''}
        ${p.status === '已通过' && p.courseId
          ? `<button class="btn-link" data-act="view" data-id="${p.id}">${ICONS.eye}查看课程</button>` : ''}
      </td>
    </tr>`).join('') : emptyRow(9, '暂无开课申请');
}

function onProposalAction(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const p = PROPOSALS.find(x => x.id === btn.dataset.id);
  if (!p) return;

  if (btn.dataset.act === 'approve') {
    askConfirm('通过开课申请',
      `确认通过「${p.teacherName}」的「${p.name}」申请？通过后将自动创建课程，负责人为申请教师。`,
      async () => {
        const ok = await apiOk(() => api.reviewCourseProposal(p.id, 'approve', ''), '已通过并创建课程');
        if (!ok) return;
        await hydrate();
        renderTable();
        await loadProposals();
      });
  } else if (btn.dataset.act === 'reject') {
    rejectId = p.id;
    $('#p-note').value = '';
    openModal('reject-modal');
  } else if (btn.dataset.act === 'view') {
    const course = byId(DB.courses, p.courseId);
    showToast(course ? `已创建课程：${course.name}（${course.id}）` : `已创建课程 ${p.courseId}`, 'info');
  }
}

async function submitReject() {
  if (!rejectId) return;
  const note = $('#p-note').value.trim();
  if (!note) { showToast('请填写驳回原因', 'error'); return; }
  const ok = await apiOk(() => api.reviewCourseProposal(rejectId, 'reject', note), '已驳回开课申请');
  if (!ok) return;
  closeModal('reject-modal');
  rejectId = null;
  await loadProposals();
}
