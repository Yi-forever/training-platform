/* ============================================================
 * teachers.js —— 教师管理：列表 / 搜索筛选 / 新增编辑 / 删除
 * 数据来源：/api/v1/teachers（boot 后缓存于 DB.teachers）
 * ============================================================ */

let currentEditId = null;
let canWrite = false;   // 写操作仅超管 / 教务（与后端 require_roles 一致）

document.addEventListener('DOMContentLoaded', async () => {
  const user = await boot('teachers');
  if (!user) return;

  canWrite = canManageAcademic(user);
  if (!canWrite) $('#btn-add').style.display = 'none';

  $('#kw').addEventListener('input', renderTable);
  $('#f-subject').addEventListener('change', renderTable);
  $('#f-status').addEventListener('change', renderTable);
  $('#btn-add').addEventListener('click', () => openEditor(null));
  $('#btn-submit').addEventListener('click', submitForm);
  $('#tbody').addEventListener('click', onTableClick);

  renderTable();
});

/* ---------- 列表 ---------- */
function getFiltered() {
  const kw = $('#kw').value.trim().toLowerCase();
  const sub = $('#f-subject').value;
  const st = $('#f-status').value;
  return DB.teachers.filter(t =>
    (!kw || t.name.toLowerCase().includes(kw) || t.id.toLowerCase().includes(kw) || (t.phone || '').includes(kw)) &&
    (!sub || t.subject === sub) &&
    (!st || t.status === st)
  );
}

function renderTable() {
  const list = getFiltered();
  $('#count').textContent = list.length;
  $('#tbody').innerHTML = list.length ? list.map(t => `
    <tr>
      <td>
        <div class="cell-user">
          ${avatarHtml(t.name)}
          <div>
            <div class="cell-main">${esc(t.name)}</div>
            <div class="td-sub">${esc(t.id)}</div>
          </div>
        </div>
      </td>
      <td>${esc(t.gender)}</td>
      <td>${esc(t.phone)}</td>
      <td class="td-sub">${esc(t.email || '—')}</td>
      <td>${esc(t.subject)}</td>
      <td class="td-sub">${t.courseCount
        ? `<span title="${esc((t.courseNames || []).join('、'))}">${esc((t.courseNames || [])[0])}${t.courseCount > 1 ? ` 等 ${t.courseCount} 门` : ''}</span>`
        : '—'}</td>
      <td>${esc(t.title)}</td>
      <td class="td-sub">${esc(t.hireDate)}</td>
      <td>${badge(t.status)}</td>
      <td class="td-actions">
        ${canWrite ? `
        <button class="btn-link" data-act="edit" data-id="${t.id}">${ICONS.edit}编辑</button>
        <button class="btn-link danger" data-act="del" data-id="${t.id}">${ICONS.trash}删除</button>` : ''}
      </td>
    </tr>`).join('') : emptyRow(10, '没有符合条件的教师');
}

/* ---------- 行操作 ---------- */
function onTableClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const { act, id } = btn.dataset;
  const t = byId(DB.teachers, id);
  if (!t) return;

  if (act === 'edit') {
    openEditor(t);
  } else if (act === 'del') {
    // 是否仍负责班级等业务校验由后端执行（冲突返回 409 并提示原因）
    askConfirm('删除教师', `确定删除教师「${t.name}」吗？删除后不可恢复。`, async () => {
      if (!await apiOk(() => api.remove('teachers', id))) return;
      await hydrate(); renderTable();
      showToast('教师已删除');
    });
  }
}

/* ---------- 新增 / 编辑 ---------- */
function openEditor(t) {
  currentEditId = t ? t.id : null;
  $('#modal-title').textContent = t ? '编辑教师' : '新增教师';
  $('#f-name').value = t ? t.name : '';
  $('#f-gender').value = t ? t.gender : '女';
  $('#f-phone').value = t ? t.phone : '';
  $('#f-email').value = t ? (t.email || '') : '';
  $('#f-subject-edit').value = t ? t.subject : 'Scratch';
  $('#f-title').value = t ? t.title : '讲师';
  $('#f-hiredate').value = t ? t.hireDate : todayStr();
  $('#f-status-edit').value = t ? t.status : '在职';
  openModal('editor-modal');
  $('#f-name').focus();
}

async function submitForm() {
  const name = $('#f-name');
  const phone = $('#f-phone');
  const hireDate = $('#f-hiredate');
  if (!valid([[name, '教师姓名'], [phone, '联系电话'], [hireDate, '入职日期']])) return;
  if (!/^\d{11}$/.test(phone.value.trim())) { showToast('请输入 11 位手机号', 'error'); phone.focus(); return; }

  const isEdit = !!currentEditId;
  const data = {
    name: name.value.trim(),
    gender: $('#f-gender').value,
    phone: phone.value.trim(),
    email: $('#f-email').value.trim(),
    subject: $('#f-subject-edit').value,
    title: $('#f-title').value,
    hireDate: hireDate.value,
    status: $('#f-status-edit').value
  };

  if (!await apiOk(() => isEdit ? api.update('teachers', currentEditId, data) : api.create('teachers', data))) return;
  await hydrate();
  closeModal('editor-modal');
  renderTable();
  showToast(isEdit ? '教师信息已更新' : `教师「${data.name}」创建成功`);
}
