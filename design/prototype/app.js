'use strict';
const $ = id => document.getElementById(id);
const fmt = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits:2}).format(value);
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const riskLabels = {critical:'Критический',high:'Высокий',normal:'Плановый'};
const riskTone = {critical:'red',high:'amber',normal:'blue'};
let selection = new Set();
let activeRow = null;
const details = $('detail');
const pageTitles = {
  procurement:['План закупок','Проверьте приоритетные позиции и подготовьте заказы поставщикам.'],
  data:['Источники данных','Понятная проверка качества до расчёта рекомендаций.'],
  exceptions:['Исключения','События и пропуски, которые требуют внимания закупщика.'],
  history:['История решений','Концепция хранения расчётов и изменений · этап 2.'],
  policies:['Политики закупок','Концепция прозрачных правил планирования · этап 2.']
};
function visibleRows(){
  const query = $('search').value.trim().toLocaleLowerCase('ru');
  const risk = $('risk').value;
  return demoRows.filter(r=>(`${r.name} ${r.sku}`.toLocaleLowerCase('ru').includes(query)) && (risk==='all' || (risk==='missing'?r.price===null:r.risk===risk)));
}
function cost(r){return r.price===null?null:r.qty*r.price;}
function render(){
  const rows=visibleRows();
  const total=rows.reduce((sum,r)=>sum+(cost(r)??0),0);
  const missing=rows.filter(r=>r.price===null).length;
  const metrics=[['К закупке',rows.filter(r=>r.qty>0).length,'позиций в текущем списке',''],['Критический риск',rows.filter(r=>r.risk==='critical').length,'позиций требуют внимания','danger'],['Бюджет',`${fmt(total)} ₸`,missing?'неполный · есть позиции без цены':'цены известны для всех позиций',''],['Поставщики',new Set(rows.map(r=>r.supplier)).size,'в текущем списке','']];
  $('metrics').innerHTML=metrics.map(([label,value,note,tone])=>`<article class="metric"><label>${label}</label><strong class="${tone}">${value}</strong><small>${note}</small></article>`).join('');
  $('rows').innerHTML=rows.map(r=>`<tr class="${selection.has(r.id)?'selected':''}" role="row"><td role="cell"><input type="checkbox" data-select="${r.id}" aria-label="Выбрать ${r.sku}, Алматы" ${selection.has(r.id)?'checked':''}></td><td role="cell"><button class="product" data-open="${r.id}">${escapeHtml(r.name)}</button><small>${r.sku} · Алматы</small></td><td role="cell"><span class="badge ${riskTone[r.risk]}">${riskLabels[r.risk]}</span></td><td role="cell">${fmt(r.stock)} ${r.unit}<small>В пути: ${fmt(r.transit)} ${r.unit}</small></td><td role="cell" class="numeric"><span class="mobile-label">К заказу</span><strong class="order-value">${fmt(r.qty)} <small style="display:inline">${r.unit}</small></strong></td><td role="cell" class="numeric"><span class="mobile-label">Стоимость</span>${cost(r)===null?'<span class="badge amber">Нет цены</span>':`${fmt(cost(r))} ₸`}</td><td role="cell"><span class="badge ${r.status==='Изменено'?'blue':''}">${r.status}</span></td></tr>`).join('');
  $('empty').hidden=rows.length>0;
  $('row-count').textContent=`${rows.length} позиций`;
  $('range').textContent=rows.length?`Показаны все ${rows.length} позиций демо-набора`:'Нет результатов';
  $('selection').textContent=selection.size?`Выбрано ${selection.size}. Экспорт будет проверен только для этих позиций.`:'Выберите позиции для проверки экспорта.';
  $('selection').classList.toggle('active',selection.size>0);
  $('select-all').checked=rows.length>0&&rows.every(r=>selection.has(r.id));
  $('select-all').indeterminate=selection.size>0&&!$('select-all').checked;
  $('select-all').disabled=!rows.length;
}
function route(){
  const candidate=location.hash.slice(1);
  const page=Object.hasOwn(pageTitles,candidate)?candidate:'procurement';
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==page);
  document.querySelectorAll('nav a').forEach(el=>el.dataset.page===page?el.setAttribute('aria-current','page'):el.removeAttribute('aria-current'));
  $('title').textContent=pageTitles[page][0];$('description').textContent=pageTitles[page][1];
  $('page-actions').hidden=page!=='procurement';
}
function openDetail(id){
  activeRow=demoRows.find(r=>r.id===Number(id));if(!activeRow)return;
  const r=activeRow;
  const raw=r.demand+r.safety-r.stock-r.transit;
  const recommended=raw<=0?0:Math.ceil(Math.max(raw,r.moq)/r.pack)*r.pack;
  $('detail-title').textContent=r.name;
  $('detail-subtitle').textContent=`${r.sku} · Алматы · ${r.supplier}`;
  $('detail-content').innerHTML=`<span class="badge ${riskTone[r.risk]}">${riskLabels[r.risk]} приоритет</span><h3>От потребности к заказу</h3><dl class="calculation"><div><dt>Спрос на срок поставки</dt><dd>${fmt(r.demand)} ${r.unit}</dd></div><div><dt>+ Страховой запас</dt><dd>${fmt(r.safety)} ${r.unit}</dd></div><div><dt>− Текущий остаток</dt><dd>${fmt(r.stock)} ${r.unit}</dd></div><div><dt>− Учитываемый транзит</dt><dd>${fmt(r.transit)} ${r.unit}</dd></div><div><dt>Чистая потребность</dt><dd>${fmt(raw)} ${r.unit}</dd></div></dl><div class="result"><span>Рекомендовано</span><strong>${fmt(recommended)} ${r.unit}</strong></div><p class="muted">Минимальный заказ: ${r.moq} ${r.unit}. Кратность: ${r.pack} ${r.unit}. ${raw<=0?'Потребность покрыта, заказ не требуется.':'Потребность округлена вверх с учётом ограничений.'}</p><h3>Сигнал спроса · иллюстрация</h3><svg class="spark" viewBox="0 0 480 110" role="img" aria-label="Вымышленный пример тренда спроса: фактический ряд и пунктирный прогноз. Не используется в расчёте."><path d="M20 84 L75 66 L130 74 L185 45 L240 54 L295 34 L350 40" fill="none" stroke="#0F766E" stroke-width="3"/><path d="M350 40 L405 31 L460 20" fill="none" stroke="#376B31" stroke-width="3" stroke-dasharray="6 5"/><line x1="350" y1="12" x2="350" y2="98" stroke="#7D9073" stroke-dasharray="3 4"/></svg><p class="chart-note">Схематичный график для композиции, без измерительной шкалы. Production-график должен использовать реальные точки API, даты, единицы и табличную альтернативу.</p>`;
  $('quantity-unit').textContent=`· ${r.unit}`;$('quantity').value=String(r.qty);$('quantity').step=String(r.pack);
  $('save-feedback').textContent='Изменения сохраняются только до перезагрузки страницы.';$('discard').hidden=true;
  details.showModal();
}
function requestClose(){
  if(activeRow&&$('quantity').value!==String(activeRow.qty)){$('discard').hidden=false;$('keep-editing').focus();}else details.close();
}
document.addEventListener('click',event=>{
  const open=event.target.closest('[data-open]');if(open)openDetail(open.dataset.open);
});
$('rows').addEventListener('change',event=>{
  const input=event.target.closest('[data-select]');if(!input)return;
  const id=Number(input.dataset.select);input.checked?selection.add(id):selection.delete(id);render();
  document.querySelector(`[data-select="${id}"]`)?.focus();
});
$('select-all').addEventListener('change',event=>{selection=event.target.checked?new Set(visibleRows().map(r=>r.id)):new Set();render();});
function filterChanged(){selection.clear();render();}
$('search').addEventListener('input',filterChanged);$('risk').addEventListener('change',filterChanged);
$('reset').addEventListener('click',()=>{$('search').value='';$('risk').value='all';filterChanged();});
$('show-missing').addEventListener('click',()=>{$('search').value='';$('risk').value='missing';filterChanged();$('risk').focus();});
$('close-detail').addEventListener('click',requestClose);
details.addEventListener('cancel',event=>{event.preventDefault();requestClose();});
$('keep-editing').addEventListener('click',()=>{$('discard').hidden=true;$('quantity').focus();});
$('discard-edit').addEventListener('click',()=>details.close());
$('adjust-form').addEventListener('submit',event=>{
  event.preventDefault();const qty=Number($('quantity').value);
  if(!Number.isFinite(qty)||qty<0||qty>100000000||qty%activeRow.pack!==0||(qty>0&&qty<activeRow.moq)){
    $('save-feedback').textContent=`Укажите 0 либо количество не меньше ${activeRow.moq}, кратное ${activeRow.pack}, не больше 100 000 000.`;return;
  }
  activeRow.qty=qty;activeRow.status='Изменено';render();$('discard').hidden=true;$('save-feedback').textContent=`В макете сохранено: ${fmt(qty)} ${activeRow.unit}. В рабочий проект изменения не отправлены.`;
});
$('export').addEventListener('click',()=>{
  const rows=selection.size?demoRows.filter(r=>selection.has(r.id)):visibleRows();
  const total=rows.reduce((sum,r)=>sum+(cost(r)??0),0);
  $('export-summary').innerHTML=`<p><strong>${selection.size?'Выбранные позиции':'Все позиции текущего фильтра'}: ${rows.length}</strong></p><p>Поставщиков: ${new Set(rows.map(r=>r.supplier)).size}</p><p>Бюджет известных цен: <strong>${fmt(total)} ₸</strong></p><p>Без цены: ${rows.filter(r=>r.price===null).length}. Все решения — демонстрационные черновики.</p>`;
  $('export-dialog').showModal();
});
$('close-export').addEventListener('click',()=>$('export-dialog').close());
$('validate').addEventListener('click',()=>{$('validation').hidden=false;});
$('sources').innerHTML=[['Продажи','1 240 строк · 12 месяцев'],['Остатки','6 позиций · Алматы'],['Транзит','3 входящие поставки'],['Периоды отсутствия','Один учебный интервал'],['Поставщики','3 учебных поставщика']].map(([title,note])=>`<article><span class="badge blue">Пример источника</span><h3>${title}</h3><p>${note}</p><p>Синтетические данные</p></article>`).join('');
window.addEventListener('hashchange',route);
render();route();
