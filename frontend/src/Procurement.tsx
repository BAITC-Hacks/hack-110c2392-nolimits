import { translateText } from './i18n'
import { useMemo, useState } from 'react'
import type { Recommendation, Status, Summary, Urgency } from './types'
import { Badge, Icon, money, number, riskLabels, statusLabels, warehouseName } from './ui'

const hasKnownCost = (row: Recommendation) => row.metadata.cost_unknown !== true && (row.unit_cost ?? 0) > 0
const confirmedCost = (items: Recommendation[]) => items.filter(hasKnownCost).reduce((sum, row) => sum + (row.total_cost_kzt ?? 0), 0)
const priority: Record<Urgency, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
export default function Procurement({ rows, summary, selectedId, onOpen, busy }: { rows: Recommendation[]; summary: Summary; selectedId?: string; onOpen: (row: Recommendation) => void; busy: boolean }) {
  const [search, setSearch] = useState('')
  const [warehouse, setWarehouse] = useState('ALL')
  const [supplier, setSupplier] = useState('ALL')
  const [category, setCategory] = useState('ALL')
  const [risk, setRisk] = useState('ALL')
  const [status, setStatus] = useState('ALL')
  const [sort, setSort] = useState('urgency')
  const [page, setPage] = useState(0)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [grouped, setGrouped] = useState(false)
  const [positiveOnly, setPositiveOnly] = useState(true)
  const visible = useMemo(() => rows.filter(r =>
    (!positiveOnly || r.final_quantity > 0) &&
    (warehouse === 'ALL' || r.warehouse === warehouse) && (supplier === 'ALL' || r.supplier_id === supplier) &&
    (category === 'ALL' || r.category === category) && (risk === 'ALL' || r.urgency === risk) && (status === 'ALL' || r.status === status) &&
    `${r.product_name} ${r.sku}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
  ).sort((a, b) => (sort === 'urgency' ? priority[a.urgency] - priority[b.urgency] : sort === 'days_of_cover' ? a.days_of_cover - b.days_of_cover : b.recommended_quantity - a.recommended_quantity) || a.sku.localeCompare(b.sku) || a.warehouse.localeCompare(b.warehouse)), [rows, warehouse, supplier, category, risk, status, search, sort, positiveOnly])
  const activeFilters = [warehouse, supplier, category, risk, status].filter(v => v !== 'ALL').length
  const currentPage = Math.min(page, Math.max(0, Math.ceil(visible.length / 25) - 1))
  const pageRows = visible.slice(currentPage * 25, currentPage * 25 + 25)
  const suppliers = [...new Map(rows.map(r => [r.supplier_id, r.supplier_name])).entries()]
  const reset = () => { setSearch(''); setWarehouse('ALL'); setSupplier('ALL'); setCategory('ALL'); setRisk('ALL'); setStatus('ALL'); setSort('urgency'); setPage(0) }
  const change = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLSelectElement>) => { setter(event.target.value); setPage(0) }
  const groups = Object.entries(visible.reduce<Record<string, Recommendation[]>>((result, r) => { (result[r.supplier_id] ||= []).push(r); return result }, {}))
  const toPurchase = rows.filter(r => r.final_quantity > 0)
  const hasPrices = toPurchase.some(hasKnownCost)
  const incompleteBudget = toPurchase.some(r => !hasKnownCost(r))
  return <>
    <section className="kpi-grid" aria-label={translateText("Показатели всего расчёта")}>
      <article className="kpi"><span>{translateText("К закупке")}</span><strong>{number(summary.skus_requiring_replenishment)}</strong><small>{translateText("позиций по всем складам")}</small></article>
      <article className="kpi"><span>{translateText("Критические")}</span><strong className="danger-text">{number(summary.critical_risks)}</strong><small>{translateText("риск дефицита до поставки")}</small></article>
      <article className="kpi"><span>{translateText("Бюджет")}</span><strong>{toPurchase.length && !hasPrices ? translateText('Цены не заданы') : summary.total_budget_kzt == null ? translateText('Не рассчитан') : money(confirmedCost(toPurchase))}</strong><small>{translateText(incompleteBudget ? 'неполный · есть позиции без цены' : 'расчётная стоимость закупки')}</small></article>
      <article className="kpi"><span>{translateText("Поставщики")}</span><strong>{number(summary.suppliers_involved)}</strong><small>{translateText("в текущем расчёте")}</small></article>
    </section>
    <section className="content-card" aria-label={translateText("План закупок")} aria-busy={busy}>
      <div className="card-header"><div><h2>{translateText("Рекомендации")}<span className="count">{visible.length}</span></h2><p>{translateText("Проверьте количество и статус перед утверждением")}</p></div><div className="view-switch" aria-label={translateText("Вид рекомендаций")}><button aria-pressed={!grouped} onClick={() => setGrouped(false)}>{translateText("По позициям")}</button><button aria-pressed={grouped} onClick={() => setGrouped(true)}>{translateText("По поставщикам")}</button></div></div>
      <div className="search-row"><label className="search"><Icon name="search"/><input aria-label={translateText("Поиск по названию или SKU")} type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} placeholder={translateText("Поиск по названию или SKU")}/></label><button className="button subtle mobile-filter" aria-expanded={filtersOpen} aria-controls="filters" onClick={() => setFiltersOpen(v => !v)}><Icon name="settings"/>{translateText("Фильтры")}{activeFilters ? ` · ${activeFilters}` : ''}</button></div>
      <div id="filters" className={`filters ${filtersOpen ? 'expanded' : ''}`}>
        <label>{translateText('Показать')}<select value={positiveOnly ? 'positive' : 'all'} onChange={event => { setPositiveOnly(event.target.value === 'positive'); setPage(0) }}><option value="positive">{translateText('Только к закупке')}</option><option value="all">{translateText('Все позиции')}</option></select></label>
        <label>{translateText("Склад")}<select value={warehouse} onChange={change(setWarehouse)}><option value="ALL">{translateText("Все склады")}</option>{[...new Set(rows.map(r => r.warehouse))].map(v => <option key={v} value={v}>{warehouseName(v)}</option>)}</select></label>
        <label>{translateText("Поставщик")}<select value={supplier} onChange={change(setSupplier)}><option value="ALL">{translateText("Все поставщики")}</option>{suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>{translateText("Приоритет")}<select value={risk} onChange={change(setRisk)}><option value="ALL">{translateText("Все приоритеты")}</option>{Object.entries(riskLabels).map(([value, label]) => <option key={value} value={value}>{translateText(label)}</option>)}</select></label>
        <label>{translateText("Статус")}<select value={status} onChange={change(setStatus)}><option value="ALL">{translateText("Все статусы")}</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{translateText(label)}</option>)}</select></label>
        <label>{translateText("Категория")}<select value={category} onChange={change(setCategory)}><option value="ALL">{translateText("Все категории")}</option>{[...new Set(rows.map(r => r.category))].map(v => <option key={v}>{v}</option>)}</select></label>
        <label>{translateText("Сортировка")}<select value={sort} onChange={change(setSort)}><option value="urgency">{translateText("Сначала срочные")}</option><option value="recommended_quantity">{translateText("Объём заказа ↓")}</option><option value="days_of_cover">{translateText("Покрытие запаса ↑")}</option></select></label>
        <button className="button subtle reset" onClick={reset}>{translateText("Сбросить")}</button>
      </div>
      {grouped ? <div className="supplier-list">{groups.map(([id, items]) => <details key={id}><summary>{items[0].supplier_name}<span>{items.length} {translateText("позиций")} · {items.some(r => r.final_quantity > 0) && !items.some(hasKnownCost) ? translateText('Цены не заданы') : money(confirmedCost(items))}{items.some(r => r.final_quantity > 0 && !hasKnownCost(r)) ? ` (${translateText('неполная сумма')})` : ''}</span></summary>{items.map(r => <button className="supplier-item" key={r.id} onClick={() => onOpen(r)}><span>{r.product_name}<small>{r.sku} · {warehouseName(r.warehouse)}</small></span><strong>{number(r.final_quantity)} {translateText("ед.")}</strong><Badge value={r.status}/></button>)}</details>)}</div> : <div className="table-wrap orders-wrap" tabIndex={0} role="region" aria-label={translateText("Таблица рекомендаций")}><table className="orders-table" role="table"><thead role="rowgroup"><tr role="row">{['Позиция / SKU', 'Приоритет', 'Поставщик', 'Остаток', 'В пути', 'К заказу', 'Стоимость', 'Статус', ''].map((label, i) => <th scope="col" role="columnheader" className={i >= 3 && i <= 6 ? 'numeric' : ''} key={i}>{translateText(label) || <span className="sr-only">{translateText("Действия")}</span>}</th>)}</tr></thead><tbody role="rowgroup">{pageRows.map(r => <tr role="row" key={r.id} className={selectedId === r.id ? 'selected' : ''}>
        <td role="cell" className="product-cell"><button className="product-link" onClick={() => onOpen(r)}>{r.product_name}</button><small>{r.sku} · {warehouseName(r.warehouse)}</small></td><td role="cell" className="risk-cell"><Badge value={r.urgency}/></td><td role="cell" className="supplier-cell">{r.supplier_name}<small>{r.lead_time_days} {translateText("дн. поставки")}</small></td>
        <td role="cell" className="numeric" data-label={translateText("Остаток")}>{number(r.current_stock)}</td><td role="cell" className="numeric" data-label={translateText("В пути")}>{number(r.in_transit)}</td><td role="cell" className="numeric order-cell" data-label={translateText("К заказу")}><strong>{number(r.final_quantity)}</strong></td><td role="cell" className="numeric" data-label={translateText("Стоимость")}>{money(r.final_quantity > 0 && !hasKnownCost(r) ? null : r.total_cost_kzt)}</td><td role="cell" className="status-cell"><Badge value={r.status as Status}/></td><td role="cell" className="action-cell"><button className="icon-button" aria-label={`${translateText("Открыть")} ${r.sku}, ${r.warehouse}`} onClick={() => onOpen(r)}><Icon name="arrow"/></button></td>
      </tr>)}</tbody></table></div>}
      {!visible.length && <div className="empty"><h3>{translateText(busy ? 'Загружаем рекомендации…' : rows.length ? 'Ничего не найдено' : 'Рекомендаций пока нет')}</h3><p>{translateText(rows.length ? 'Измените условия поиска или сбросьте фильтры.' : 'Загрузите данные и выполните расчёт.')}</p>{!!rows.length && <button className="button subtle" onClick={reset}>{translateText("Сбросить фильтры")}</button>}</div>}
      {!grouped && <div className="pagination"><span>{visible.length ? `${currentPage * 25 + 1}–${Math.min((currentPage + 1) * 25, visible.length)} ${translateText('из')} ${visible.length}` : `0 ${translateText('позиций')}`}<small>{translateText("Количество — в единицах исходных данных")}</small></span><div><button className="button subtle" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{translateText("Назад")}</button><button className="button subtle" disabled={(currentPage + 1) * 25 >= visible.length} onClick={() => setPage(currentPage + 1)}>{translateText("Далее")}</button></div></div>}
    </section>
    <details className="processing-note"><summary>{translateText("Дополнительная аналитика расчёта")}</summary><p>{translateText("Выбросов обработано")}: {summary.detected_anomalies}. {translateText("Восстановленный спрос")}: {number(summary.estimated_lost_demand)}. {translateText("Объём заказа из сводки API")}: {number(summary.total_recommended_units)}. {translateText("Эти показатели относятся ко всему расчёту, независимо от фильтров.")}</p></details>
  </>
}
