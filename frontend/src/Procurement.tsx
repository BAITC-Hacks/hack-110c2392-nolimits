import { useMemo, useState } from 'react'
import type { Recommendation, Status, Summary, Urgency } from './types'
import { Badge, Icon, money, number, riskLabels, statusLabels, warehouseName } from './ui'

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
  const visible = useMemo(() => rows.filter(r =>
    (warehouse === 'ALL' || r.warehouse === warehouse) && (supplier === 'ALL' || r.supplier_id === supplier) &&
    (category === 'ALL' || r.category === category) && (risk === 'ALL' || r.urgency === risk) && (status === 'ALL' || r.status === status) &&
    `${r.product_name} ${r.sku}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
  ).sort((a, b) => (sort === 'urgency' ? priority[a.urgency] - priority[b.urgency] : sort === 'days_of_cover' ? a.days_of_cover - b.days_of_cover : b.recommended_quantity - a.recommended_quantity) || a.sku.localeCompare(b.sku) || a.warehouse.localeCompare(b.warehouse)), [rows, warehouse, supplier, category, risk, status, search, sort])
  const activeFilters = [warehouse, supplier, category, risk, status].filter(v => v !== 'ALL').length
  const currentPage = Math.min(page, Math.max(0, Math.ceil(visible.length / 25) - 1))
  const pageRows = visible.slice(currentPage * 25, currentPage * 25 + 25)
  const suppliers = [...new Map(rows.map(r => [r.supplier_id, r.supplier_name])).entries()]
  const reset = () => { setSearch(''); setWarehouse('ALL'); setSupplier('ALL'); setCategory('ALL'); setRisk('ALL'); setStatus('ALL'); setSort('urgency'); setPage(0) }
  const change = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLSelectElement>) => { setter(event.target.value); setPage(0) }
  const groups = Object.entries(visible.reduce<Record<string, Recommendation[]>>((result, r) => { (result[r.supplier_id] ||= []).push(r); return result }, {}))
  return <>
    <section className="kpi-grid" aria-label="Показатели всего расчёта">
      <article className="kpi"><span>К закупке</span><strong>{number(summary.skus_requiring_replenishment)}</strong><small>позиций по всем складам</small></article>
      <article className="kpi"><span>Критические</span><strong className="danger-text">{number(summary.critical_risks)}</strong><small>риск дефицита до поставки</small></article>
      <article className="kpi"><span>Бюджет</span><strong>{summary.total_budget_kzt == null ? 'Не рассчитан' : money(summary.total_budget_kzt)}</strong><small>{rows.some(r => r.final_quantity > 0 && r.total_cost_kzt == null) ? 'неполный · есть позиции без цены' : 'расчётная стоимость закупки'}</small></article>
      <article className="kpi"><span>Поставщики</span><strong>{number(summary.suppliers_involved)}</strong><small>в текущем расчёте</small></article>
    </section>
    <section className="content-card" aria-label="План закупок" aria-busy={busy}>
      <div className="card-header"><div><h2>Рекомендации <span className="count">{visible.length}</span></h2><p>Проверьте количество и статус перед утверждением</p></div><div className="view-switch" aria-label="Вид рекомендаций"><button aria-pressed={!grouped} onClick={() => setGrouped(false)}>По позициям</button><button aria-pressed={grouped} onClick={() => setGrouped(true)}>По поставщикам</button></div></div>
      <div className="search-row"><label className="search"><Icon name="search"/><input aria-label="Поиск по названию или SKU" type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} placeholder="Поиск по названию или SKU"/></label><button className="button subtle mobile-filter" aria-expanded={filtersOpen} aria-controls="filters" onClick={() => setFiltersOpen(v => !v)}><Icon name="settings"/>Фильтры{activeFilters ? ` · ${activeFilters}` : ''}</button></div>
      <div id="filters" className={`filters ${filtersOpen ? 'expanded' : ''}`}>
        <label>Склад<select value={warehouse} onChange={change(setWarehouse)}><option value="ALL">Все склады</option>{[...new Set(rows.map(r => r.warehouse))].map(v => <option key={v} value={v}>{warehouseName(v)}</option>)}</select></label>
        <label>Поставщик<select value={supplier} onChange={change(setSupplier)}><option value="ALL">Все поставщики</option>{suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>Приоритет<select value={risk} onChange={change(setRisk)}><option value="ALL">Все приоритеты</option>{Object.entries(riskLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Статус<select value={status} onChange={change(setStatus)}><option value="ALL">Все статусы</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Категория<select value={category} onChange={change(setCategory)}><option value="ALL">Все категории</option>{[...new Set(rows.map(r => r.category))].map(v => <option key={v}>{v}</option>)}</select></label>
        <label>Сортировка<select value={sort} onChange={change(setSort)}><option value="urgency">Сначала срочные</option><option value="recommended_quantity">Объём заказа ↓</option><option value="days_of_cover">Покрытие запаса ↑</option></select></label>
        <button className="button subtle reset" onClick={reset}>Сбросить</button>
      </div>
      {grouped ? <div className="supplier-list">{groups.map(([id, items]) => <details key={id}><summary>{items[0].supplier_name}<span>{items.length} позиций · {money(items.reduce((sum, r) => sum + (r.total_cost_kzt ?? 0), 0))}{items.some(r => r.total_cost_kzt == null) ? ' (неполная сумма)' : ''}</span></summary>{items.map(r => <button className="supplier-item" key={r.id} onClick={() => onOpen(r)}><span>{r.product_name}<small>{r.sku} · {warehouseName(r.warehouse)}</small></span><strong>{number(r.final_quantity)} ед.</strong><Badge value={r.status}/></button>)}</details>)}</div> : <div className="table-wrap orders-wrap" tabIndex={0} role="region" aria-label="Таблица рекомендаций"><table className="orders-table" role="table"><thead role="rowgroup"><tr role="row">{['Позиция / SKU', 'Приоритет', 'Поставщик', 'Остаток', 'В пути', 'К заказу', 'Стоимость', 'Статус', ''].map((label, i) => <th scope="col" role="columnheader" className={i >= 3 && i <= 6 ? 'numeric' : ''} key={i}>{label || <span className="sr-only">Действия</span>}</th>)}</tr></thead><tbody role="rowgroup">{pageRows.map(r => <tr role="row" key={r.id} className={selectedId === r.id ? 'selected' : ''}>
        <td role="cell" className="product-cell"><button className="product-link" onClick={() => onOpen(r)}>{r.product_name}</button><small>{r.sku} · {warehouseName(r.warehouse)}</small></td><td role="cell" className="risk-cell"><Badge value={r.urgency}/></td><td role="cell" className="supplier-cell">{r.supplier_name}<small>{r.lead_time_days} дн. поставки</small></td>
        <td role="cell" className="numeric" data-label="Остаток">{number(r.current_stock)}</td><td role="cell" className="numeric" data-label="В пути">{number(r.in_transit)}</td><td role="cell" className="numeric order-cell" data-label="К заказу"><strong>{number(r.final_quantity)}</strong></td><td role="cell" className="numeric" data-label="Стоимость">{money(r.total_cost_kzt)}</td><td role="cell" className="status-cell"><Badge value={r.status as Status}/></td><td role="cell" className="action-cell"><button className="icon-button" aria-label={`Открыть ${r.sku}, ${r.warehouse}`} onClick={() => onOpen(r)}><Icon name="arrow"/></button></td>
      </tr>)}</tbody></table></div>}
      {!visible.length && <div className="empty"><h3>{busy ? 'Загружаем рекомендации…' : rows.length ? 'Ничего не найдено' : 'Рекомендаций пока нет'}</h3><p>{rows.length ? 'Измените условия поиска или сбросьте фильтры.' : 'Загрузите данные и выполните расчёт.'}</p>{!!rows.length && <button className="button subtle" onClick={reset}>Сбросить фильтры</button>}</div>}
      {!grouped && <div className="pagination"><span>{visible.length ? `${currentPage * 25 + 1}–${Math.min((currentPage + 1) * 25, visible.length)} из ${visible.length}` : '0 позиций'}<small>Количество — в единицах исходных данных</small></span><div><button className="button subtle" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Назад</button><button className="button subtle" disabled={(currentPage + 1) * 25 >= visible.length} onClick={() => setPage(currentPage + 1)}>Далее</button></div></div>}
    </section>
    <details className="processing-note"><summary>Дополнительная аналитика расчёта</summary><p>Выбросов обработано: {summary.detected_anomalies}. Восстановленный спрос: {number(summary.estimated_lost_demand)}. Объём заказа из сводки API: {number(summary.total_recommended_units)}. Эти показатели относятся ко всему расчёту, независимо от фильтров.</p></details>
  </>
}
