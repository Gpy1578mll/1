const $ = id => document.getElementById(id);
const names = {persons:'Человек', organizations:'Организация', entrepreneurs:'ИП', communications:'Коммуникация'};
const personFields = ['фамилия','имя','отчество','дата_рождения','место_рождения'];
const sourceFields = ['фио','дата_рождения','место_рождения'];
let token = '', text = '', entities = [], selected = -1, timer;
async function api(url, options = {}) {
  const r = await fetch(url, options); const data = await r.json();
  if (!r.ok) throw Error(data.detail || 'Ошибка запроса');
  return data;
}
function message(value) { $('status').textContent = value; }
const chars = () => Array.from(text);
const snippet = span => chars().slice(span.start, span.end).join('');
function initPerson(entity) {
  entity.person = Object.fromEntries(personFields.map(field => [field, null]));
  entity.source_spans = {фио:{start:entity.start, end:entity.end}, дата_рождения:null, место_рождения:null};
}
function updatePerson(entity) {
  const anchor = Object.values(entity.source_spans).find(Boolean);
  if (anchor) { entity.start = anchor.start; entity.end = anchor.end; }
  const name = personFields.slice(0, 3).map(field => entity.person[field]).filter(Boolean).join(' ');
  entity.normalized_value = name || entity.person.дата_рождения || entity.person.место_рождения || (anchor ? snippet(anchor) : 'Человек');
}
function highlights() {
  return entities.flatMap((entity, index) => entity.kind === 'persons'
    ? Object.entries(entity.source_spans).filter(([,span]) => span).map(([field, span]) => ({...span, kind:entity.kind, value:field + ': ' + snippet(span), index}))
    : [{start:entity.start, end:entity.end, kind:entity.kind, value:entity.normalized_value, index}]);
}
function render() {
  const c = chars(), pane = $('text'); pane.replaceChildren();
  const valid = highlights().filter(span => Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end <= c.length && span.start < span.end);
  const boundaries = [...new Set([0, c.length, ...valid.flatMap(span => [span.start,span.end])])].sort((a,b) => a-b);
  for (let i = 0; i < boundaries.length - 1; i++) {
    const matching = valid.filter(span => span.start <= boundaries[i] && span.end >= boundaries[i+1]);
    const el = document.createElement(matching.length ? 'mark' : 'span');
    el.textContent = c.slice(boundaries[i],boundaries[i+1]).join('');
    if (matching.length) {
      el.className = matching[0].kind;
      el.title = matching.map(span => names[span.kind] + ': ' + span.value).join(' | ');
      el.onclick = () => { selected = matching[0].index; renderRows(); $('row-'+selected).scrollIntoView({block:'nearest'}); };
    }
    pane.append(el);
  }
  renderRows();
}
function inputControl(labelText, value, onChange, numeric = false) {
  const label = document.createElement('label'); label.className = 'field-control';
  const caption = document.createElement('span'); caption.textContent = labelText;
  const input = document.createElement('input'); input.value = value ?? ''; input.placeholder = numeric ? '' : 'null — не указано';
  input.setAttribute('aria-label', labelText);
  if (numeric) input.type = 'number';
  input.onchange = () => { onChange(numeric ? Number(input.value) : input.value); render(); };
  label.append(caption, input); return label;
}
function selectedSpan() {
  const selection = window.getSelection();
  if (!selection.rangeCount || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  if (!$('text').contains(range.commonAncestorContainer)) return null;
  const before = range.cloneRange(); before.selectNodeContents($('text'));
  before.setEnd(range.startContainer,range.startOffset);
  const start = Array.from(before.toString()).length;
  return {start, end:start + Array.from(range.toString()).length};
}
function personSourceControls(entity) {
  const container = document.createElement('div');
  for (const field of sourceFields) {
    const box = document.createElement('div'); box.className = 'source-control';
    const title = document.createElement('strong'); title.textContent = field.replaceAll('_',' '); box.append(title);
    const span = entity.source_spans[field];
    const original = document.createElement('p'); original.textContent = span ? snippet(span) : 'null — фрагмент отсутствует'; box.append(original);
    if (span) {
      for (const key of ['start','end']) box.append(inputControl(key === 'start' ? 'Начало' : 'Конец', span[key], value => { span[key] = value; updatePerson(entity); }, true));
      const clear = document.createElement('button'); clear.textContent = 'Убрать фрагмент';
      clear.onclick = () => {
        entity.source_spans[field] = null;
        if (field === 'фио') personFields.slice(0,3).forEach(key => entity.person[key] = null);
        else entity.person[field] = null;
        updatePerson(entity); render();
      }; box.append(clear);
    }
    const choose = document.createElement('button'); choose.textContent = 'Привязать выделенный текст';
    choose.onmousedown = event => event.preventDefault();
    choose.onclick = () => {
      const span = selectedSpan();
      if (!span) return message('Выделите фрагмент исходного текста, затем нажмите кнопку привязки.');
      entity.source_spans[field] = span;
      if (field === 'место_рождения') entity.person[field] = snippet(span);
      updatePerson(entity); window.getSelection().removeAllRanges(); render();
    }; box.append(choose); container.append(box);
  }
  return container;
}
function renderRows() {
  $('rows').replaceChildren();
  entities.forEach((entity,index) => {
    const row = document.createElement('tr'); row.id = 'row-'+index;
    if (index === selected) row.className = 'active';
    const cell = node => { const td = document.createElement('td'); td.append(node); row.append(td); };
    const category = document.createElement('select');
    Object.entries(names).forEach(([key,value]) => category.add(new Option(value,key)));
    category.value = entity.kind;
    category.onchange = () => {
      entity.kind = category.value;
      if (entity.kind === 'persons') { initPerson(entity); updatePerson(entity); }
      else { delete entity.person; delete entity.source_spans; }
      render();
    }; cell(category);
    if (entity.kind === 'persons') {
      cell(personSourceControls(entity));
      const fields = document.createElement('div');
      personFields.forEach(field => fields.append(inputControl(field.replaceAll('_',' '), entity.person[field], value => {
        entity.person[field] = value.trim() || null; updatePerson(entity);
      })));
      const hint = document.createElement('small'); hint.textContent = 'Пустое поле сохраняется как NULL. Полная дата: ДД.ММ.ГГГГ; неполная — как в тексте.'; fields.append(hint); cell(fields);
      for (let i=0;i<2;i++) { const hint = document.createElement('span'); hint.textContent = 'Границы каждого поля — слева'; cell(hint); }
    } else {
      const original = document.createElement('span'); original.textContent = snippet(entity); cell(original);
      cell(inputControl('Нормализованное значение',entity.normalized_value,value => entity.normalized_value=value));
      for (const key of ['start','end']) cell(inputControl(key === 'start' ? 'Начало' : 'Конец',entity[key],value => entity[key]=value,true));
    }
    cell(inputControl('Замечание',entity.note,value => entity.note=value));
    const remove = document.createElement('button'); remove.textContent = 'Удалить';
    remove.onclick = () => { entities.splice(index,1); render(); }; cell(remove); $('rows').append(row);
  });
}
$('upload').onsubmit = async event => {
  event.preventDefault(); clearTimeout(timer); $('review').hidden = true;
  const form = new FormData(); form.append('file',$('file').files[0]);
  try { message('Загрузка…'); ({token} = await api('/api/upload',{method:'POST',body:form})); poll(); }
  catch (error) { message(error.message); }
};
async function poll() {
  try {
    const job = await api('/api/review/'+token);
    if (job.status === 'processing') { message('Модель обрабатывает документ…'); timer = setTimeout(poll,1500); return; }
    if (job.status === 'error') throw Error(job.error);
    text = job.text; entities = structuredClone(job.entities);
    $('review').hidden = false; $('confirm').disabled = false;
    message('Проверьте исходные фрагменты, сведения о людях и нормализованные значения.'); render();
  } catch (error) { message(error.message); }
}
$('add').onmousedown = event => event.preventDefault();
$('add').onclick = () => {
  const span = selectedSpan();
  if (!span) return message('Сначала выделите фрагмент исходного текста.');
  const entity = {kind:'persons', ...span, original_text:snippet(span), normalized_value:snippet(span), note:'Добавлено оператором'};
  initPerson(entity); entities.push(entity); window.getSelection().removeAllRanges(); render();
};
$('confirm').onclick = async () => {
  if (!confirm('Сохранить документ и проверенные сущности в SQLite?')) return;
  $('confirm').disabled = true;
  try {
    const result = await api('/api/review/'+token+'/confirm',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({entities})});
    message('Документ сохранён. ID: '+result.document_id); $('review').hidden = true;
  } catch (error) { message(error.message); $('confirm').disabled = false; }
};
$('cancel').onclick = async () => {
  try { await api('/api/review/'+token,{method:'DELETE'}); $('review').hidden=true; entities=[]; text=''; message('Обработка отменена. Данные не записаны.'); }
  catch (error) { message(error.message); }
};

api('/api/config').then(config => { $('provider-notice').textContent = config.notice || ''; })
  .catch(() => { $('provider-notice').textContent = 'Не удалось прочитать настройки распознавания.'; });
