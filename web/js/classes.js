/* ============================================================
 * classes.js —— 班级管理：列表 / 筛选 / 排班 / 报名进度 / 删除
 * 数据来源：/api/v1/classes（boot 后缓存于 DB.classes，在读人数用后端 enrolled）
 * ============================================================ */

let currentEditId = null;
let canWrite = false;   // 写操作仅超管 / 教务（与后端 require_roles 一致）

document.addEventListener('DOMContentLoaded', async () => {
  const user = await boot('classes');
  if (!user) return;

  canWrite = canManageAcademic(user);
  if (!canWrite) $('#btn-add').style.display = 'none';

  fillSelects();

  $('#kw').addEventListener('input', renderTable);
  $('#f-status').addEventListener('change', renderTable);
  $('#btn-add').addEventListener('click', () => openEditor(null));
  $('#btn-submit').addEventListener('click', submitForm);
  $('#tbody').addEventListener('click', onTableClick);
  // 选择课程后自动带出该课程的负责教师（仍可手动改）
  $('#f-course').addEventListener('change', () => fillSelects($('#f-course').value));

  renderTable();
});

/* ---------- 下拉数据（在售课程 / 在职教师） ---------- */
function fillSelects(selectedCourse, selectedTeacher) {
  const courseOpts = DB.courses.filter(c => c.status === '在售')
    .map(c => `<option value="${c.id}">${esc(c.name)} · ${money(c.price)}</option>`).join('');
  const teacherOpts = DB.teachers.filter(t => t.status === '在职')
    .map(t => `<option value="${t.id}">${esc(t.name)}（${esc(t.subject)} · ${esc(t.title)}）</option>`).join('');
  $('#f-course').innerHTML = courseOpts || '<option value="">暂无在售课程</option>';
  $('#f-teacher').innerHTML = teacherOpts || '<option value="">暂无在职教师</option>';
  if (selectedCourse) $('#f-course').value = selectedCourse;
  if (selectedTeacher) {
    $('#f-teacher').value = selectedTeacher;
  } else {
    const course = byId(DB.courses, $('#f-course').value);
    if (course && course.teacherId) $('#f-teacher').value = course.teacherId;
  }
}

/* ---------- 列表 ---------- */
function getFiltered() {
  const kw = $('#kw').value.trim().toLowerCase();
  const st = $('#f-status').value;
  return DB.classes.filter(c =>
    (!kw || c.name.toLowerCase().includes(kw) || c.id.toLowerCase().includes(kw) || (c.classroom || '').toLowerCase().includes(kw)) &&
    (!st || c.status === st)
  );
}

function renderTable() {
  const list = getFiltered();
  $('#count').textContent = list.length;
  $('#tbody').innerHTML = list.length ? list.map(c => {
    const enrolled = c.enrolled;   // 后端口径：该班级全部在册学员数
    const pct = Math.min(100, Math.round(enrolled / (c.capacity || 1) * 100));
    const full = enrolled >= c.capacity;
    return `
    <tr>
      <td class="td-sub">${esc(c.id)}</td>
      <td>
        <div class="cell-main">${esc(c.name)}</div>
        <div class="td-sub">${esc(courseName(c.courseId))}</div>
      </td>
      <td>${esc(teacherName(c.teacherId))}</td>
      <td>${esc(c.classroom)}</td>
      <td>${esc(c.schedule)}</td>
      <td style="min-width:120px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px">
          <span style="font-weight:600;${full ? 'color:var(--danger)' : ''}">${enrolled} / ${c.capacity}</span>
          <span class="td-sub">${pct}%</span>
        </div>
        <div class="progress"><span style="width:${pct}%"></span></div>
      </td>
      <td class="td-sub">${esc(c.startDate)}<br>${esc(c.endDate || '—')}</td>
      <td>${badge(c.status)}</td>
      <td class="td-actions">
        <button class="btn-link" data-act="schedule" data-id="${c.id}">${ICONS.calendar}排课</button>
        ${canWrite ? `
        <button class="btn-link" data-act="edit" data-id="${c.id}">${ICONS.edit}编辑</button>
        <button class="btn-link danger" data-act="del" data-id="${c.id}">${ICONS.trash}删除</button>` : ''}
      </td>
    </tr>`;
  }).join('') : emptyRow(10, '没有符合条件的班级');
}

/* ---------- 行操作 ---------- */
function onTableClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const { act, id } = btn.dataset;
  const c = byId(DB.classes, id);
  if (!c) return;

  if (act === 'edit') {
    openEditor(c);
  } else if (act === 'schedule') {
    openScheduleManager(c, canWrite);
  } else if (act === 'del') {
    // 是否仍有学员等业务校验由后端执行（冲突返回 409 并提示原因）
    askConfirm('删除班级', `确定删除班级「${c.name}」吗？删除后不可恢复。`, async () => {
      if (!await apiOk(() => api.remove('classes', id))) return;
      await hydrate(); renderTable();
      showToast('班级已删除');
    });
  }
}

/* ---------- 新增 / 编辑 ---------- */
function openEditor(c) {
  currentEditId = c ? c.id : null;
  $('#modal-title').textContent = c ? '编辑班级' : '新增班级';
  fillSelects(c && c.courseId, c && c.teacherId);
  $('#f-name').value = c ? c.name : '';
  $('#f-classroom').value = c ? c.classroom : 'A101';
  $('#f-capacity').value = c ? c.capacity : '';
  $('#f-schedule').value = c ? c.schedule : '';
  $('#f-startdate').value = c ? c.startDate : todayStr();
  $('#f-enddate').value = c ? (c.endDate || '') : '';
  $('#f-status-edit').value = c ? c.status : '未开班';
  openModal('editor-modal');
  $('#f-name').focus();
}

async function submitForm() {
  const name = $('#f-name');
  const capacity = $('#f-capacity');
  const schedule = $('#f-schedule');
  const startDate = $('#f-startdate');
  const courseId = $('#f-course').value;
  const teacherId = $('#f-teacher').value;
  if (!valid([[name, '班级名称'], [capacity, '班容上限'], [schedule, '上课时间'], [startDate, '开班日期']])) return;
  if (!courseId) { showToast('请先创建在售课程，再排班', 'error'); return; }
  if (!teacherId) { showToast('请先添加在职教师，再排班', 'error'); return; }
  if (Number(capacity.value) <= 0) { showToast('班容上限必须大于 0', 'error'); return; }

  const isEdit = !!currentEditId;
  const data = {
    name: name.value.trim(),
    courseId, teacherId,
    classroom: $('#f-classroom').value,
    capacity: Number(capacity.value),
    schedule: schedule.value.trim(),
    startDate: startDate.value,
    endDate: $('#f-enddate').value,
    status: $('#f-status-edit').value
  };

  if (!await apiOk(() => isEdit ? api.update('classes', currentEditId, data) : api.create('classes', data))) return;
  await hydrate();
  closeModal('editor-modal');
  renderTable();
  showToast(isEdit ? '班级信息已更新' : `班级「${data.name}」排班成功`);
}
