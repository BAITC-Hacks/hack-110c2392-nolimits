import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, ReferenceArea, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { adjustOrder, approveOrder, calculate, exportUrl, getAnalytics, getOutliers, getRecommendations, loadAnomalies, loadDemo, loadEkt, uploadFile, uploadWorkbook } from './api'
import type { Point, Recommendation, Summary, Urgency } from './types'

const nav = [{ key: 'overview', label: 'Закупки', icon: '◒' }, { key: 'imports', label: 'Данные', icon: '↥' }, { key: 'anomalies', label: 'Аномалии', icon: '⌁' }]
const urgencyOrder: Record<Urgency, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
const urgencyLabels: Record<Urgency, string> = { CRITICAL: 'Критический', HIGH: 'Высокий', MEDIUM: 'Средний', LOW: 'Низкий' }
const warehouseLabels: Record<string, string> = { 'WH-CENTRAL': 'Центральный склад', 'WH-NORTH': 'Северный склад', 'WH-SOUTH': 'Южный склад' }
const money = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)

export default function App() {
  const [page, setPage] = useState('overview')
  const [rows, setRows] = useState<Recommendation[]>([])
  const [summary, setSummary] = useState<Summary>({ skus_requiring_replenishment: 0, critical_risks: 0, total_recommended_units: 0, total_budget_kzt: 0, suppliers_involved: 0, detected_anomalies: 0, estimated_lost_demand: 0 })
  const [selected, setSelected] = useState<Recommendation | null>(null)
  const [analytics, setAnalytics] = useState<{ points: Point[]; outliers: unknown[] } | null>(null)
  const [search, setSearch] = useState('')
  const [urgency, setUrgency] = useState('ALL')
  const [warehouse, setWarehouse] = useState('ALL')
  const [supplier, setSupplier] = useState('ALL')
  const [category, setCategory] = useState('ALL')
  const [sort, setSort] = useState<'urgency' | 'recommended_quantity' | 'days_of_cover'>('urgency')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const warehouses = useMemo(() => [...new Set(rows.map(row => row.warehouse))], [rows])

  const refresh = async () => { setBusy(true); try { const result = await getRecommendations(); setRows(result.recommendations); setSummary(result.summary) } catch (error) { showToast(error instanceof Error ? error.message : 'Could not load recommendations') } finally { setBusy(false) } }
  const showToast = (message: string) => { setToast(message); window.setTimeout(() => setToast(''), 3500) }
  useEffect(() => { refresh() }, [])

  const demo = async () => { setBusy(true); try { await loadDemo(); await calculate(); await refresh(); showToast('Demo scenario loaded and recalculated') } catch (error) { showToast(error instanceof Error ? error.message : 'Could not load demo') } finally { setBusy(false) } }
  const ekt = async () => { setBusy(true); try { await loadEkt(); await refresh(); showToast('⚡️ ТОО «Электрокомплект» (ekt.kz) data loaded & calculated!') } catch (error) { showToast(error instanceof Error ? error.message : 'Could not load ekt.kz data') } finally { setBusy(false) } }
  const anomalies = async () => { setBusy(true); try { const res = await loadAnomalies(); await refresh(); showToast(`💥 Датасет аномалий загружен! Выявлено ${res.outliers} аномалий, пересчитано ${res.recommendations} заказов!`) } catch (error) { showToast(error instanceof Error ? error.message : 'Could not load anomalies data') } finally { setBusy(false) } }
  const openSku = async (row: Recommendation) => { setSelected(row); try { setAnalytics(await getAnalytics(row.sku, row.warehouse)) } catch { showToast('Could not load SKU analytics') } }
  const visibleRows = useMemo(() => rows.filter(row => (urgency === 'ALL' || row.urgency === urgency) && (warehouse === 'ALL' || row.warehouse === warehouse) && (supplier === 'ALL' || row.supplier_id === supplier) && (category === 'ALL' || row.category === category) && (!search || `${row.sku} ${row.product_name}`.toLowerCase().includes(search.toLowerCase()))).sort((a, b) => sort === 'urgency' ? urgencyOrder[a.urgency] - urgencyOrder[b.urgency] : b[sort] - a[sort]), [rows, urgency, warehouse, supplier, category, search, sort])

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">S</div><div><strong>stockpilot</strong><span>Планирование закупок</span></div></div>
      <div className="side-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav aria-label="Main navigation">{nav.map(item => <button key={item.key} aria-label={item.label} aria-current={page === item.key ? 'page' : undefined} className={page === item.key ? 'nav-item active' : 'nav-item'} onClick={() => { setPage(item.key); setSelected(null) }}><span aria-hidden="true">{item.icon}</span><b className="nav-label">{item.label}</b></button>)}</nav>
      <div className="sidebar-bottom"><div className="live-dot"><i /> StockPilot</div><small>v1.2 · ekt.kz + anomalies</small></div>
    </aside>
    <main className="main"><header className="topbar"><div><p className="eyebrow">УПРАВЛЕНИЕ ЗАПАСАМИ</p><h1>{page === 'overview' ? 'План закупок' : nav.find(item => item.key === page)?.label}</h1></div><div className="top-actions"><button className="button subtle" onClick={() => setPage('imports')}>Источники данных</button><button className="button primary" onClick={refresh} disabled={busy}>{busy ? 'Обновляем…' : 'Обновить'}</button></div></header>
      {page === 'overview' && <Overview rows={visibleRows} allRows={rows} summary={summary} search={search} setSearch={setSearch} urgency={urgency} setUrgency={setUrgency} warehouse={warehouse} setWarehouse={setWarehouse} supplier={supplier} setSupplier={setSupplier} category={category} setCategory={setCategory} warehouses={warehouses} sort={sort} setSort={setSort} onOpen={openSku} onRefresh={refresh} onToast={showToast} />}
      {page === 'imports' && <Imports onToast={showToast} onRefresh={refresh} onEkt={ekt} onAnomalies={anomalies} />}
      {page === 'anomalies' && <Anomalies onOpen={openSku} />}
    </main>
    {selected && <Detail row={selected} analytics={analytics} onClose={() => setSelected(null)} onChanged={async row => { setRows(current => current.map(item => item.id === row.id ? row : item)); setSelected(row); showToast(row.status === 'APPROVED' ? 'Order approved' : 'Quantity adjusted') }} />}
    {toast && <div className="toast">{toast}</div>}
  </div>
}

function Overview({ rows, allRows, summary, search, setSearch, urgency, setUrgency, warehouse, setWarehouse, supplier, setSupplier, category, setCategory, warehouses, sort, setSort, onOpen, onRefresh, onToast }: any) {
  const [filtersExpanded, setFiltersExpanded] = useState(false)
  const activeFilters = [warehouse, supplier, category, urgency].filter(value => value !== 'ALL').length
  const cards = [
    { label: 'К закупке', value: summary.skus_requiring_replenishment, note: 'позиции по складам', icon: '↗', tone: 'lime' },
    { label: 'Критический риск', value: summary.critical_risks, note: 'риск нехватки до поставки', icon: '!', tone: 'red' },
    { label: 'Объём заказа', value: money(summary.total_recommended_units), note: 'с учётом округления', icon: '⌁', tone: 'blue' },
    { label: 'Бюджет заказа', value: summary.total_budget_kzt ? `${money(summary.total_budget_kzt)} ₸` : '—', note: 'расчётная стоимость', icon: '₸', tone: 'cyan' },
    { label: 'Поставщики', value: summary.suppliers_involved, note: 'в текущем расчёте', icon: '◌', tone: 'violet' },
    { label: 'Выбросы спроса', value: summary.detected_anomalies, note: 'сохранены для проверки', icon: '∿', tone: 'amber' },
    { label: 'Восстановленный спрос', value: money(summary.estimated_lost_demand), note: 'поправка на дефицит', icon: '＋', tone: 'cyan' }
  ]
  const suppliers: Array<[string, string]> = [...new Map<string, string>(allRows.map((row: Recommendation) => [row.supplier_id, row.supplier_name] as [string, string])).entries()]
  const categories: string[] = [...new Set<string>(allRows.map((row: Recommendation) => row.category))]
  return <>
    <section className="hero-row"><p>Проверьте приоритетные позиции, уточните количество и подготовьте заказы поставщикам.</p></section>
    <section className="kpi-grid">{cards.map(card => <div className={`kpi-card ${card.tone}`} key={card.label}><div className="kpi-top"><span>{card.icon}</span><small>{card.label}</small></div><strong>{card.value}</strong><p>{card.note}</p></div>)}</section>
    <section className="content-card"><div className="card-header"><div><p className="eyebrow">ПЛАН ПОПОЛНЕНИЯ</p><h3>Рекомендуемые заказы <span>{rows.length} / {allRows.length}</span></h3></div><div className="header-actions"><a href={exportUrl('csv')} className="button subtle">↓ CSV</a><a href={exportUrl('xlsx')} className="button subtle">↓ XLSX</a></div></div>
      <div className="filter-heading"><div className="search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Название или артикул…" aria-label="Поиск по названию или артикулу" /></div><button className="button subtle filter-toggle" aria-expanded={filtersExpanded} aria-controls="order-filters" onClick={() => setFiltersExpanded(!filtersExpanded)}>Фильтры{activeFilters ? ` · ${activeFilters}` : ''} <span aria-hidden="true">{filtersExpanded ? '−' : '+'}</span></button></div><div id="order-filters" className={`filters ${filtersExpanded ? 'expanded' : ''}`}><select aria-label="Склад" value={warehouse} onChange={event => setWarehouse(event.target.value)}><option value="ALL">Все склады</option>{warehouses.map((item: string) => <option key={item} value={item}>{warehouseLabels[item] || item}</option>)}</select><select aria-label="Поставщик" value={supplier} onChange={event => setSupplier(event.target.value)}><option value="ALL">Все поставщики</option>{suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><select aria-label="Категория" value={category} onChange={event => setCategory(event.target.value)}><option value="ALL">Все категории</option>{categories.map((item: string) => <option key={item}>{item}</option>)}</select><select aria-label="Приоритет" value={urgency} onChange={event => setUrgency(event.target.value)}><option value="ALL">Любой приоритет</option><option value="CRITICAL">{urgencyLabels.CRITICAL}</option><option value="HIGH">{urgencyLabels.HIGH}</option><option value="MEDIUM">{urgencyLabels.MEDIUM}</option><option value="LOW">{urgencyLabels.LOW}</option></select><select aria-label="Сортировка" value={sort} onChange={event => setSort(event.target.value)}><option value="urgency">Сначала срочные</option><option value="recommended_quantity">По объёму заказа</option><option value="days_of_cover">По покрытию запаса</option></select><button className="icon-button" aria-label="Refresh recommendations" onClick={onRefresh}>↻</button></div>
      <div className="table-wrap"><table className="orders-table" role="table" aria-label="Recommended orders"><thead role="rowgroup"><tr role="row"><th scope="col" role="columnheader">Приоритет</th><th scope="col" role="columnheader">Артикул / товар</th><th scope="col" role="columnheader">Поставщик</th><th scope="col" role="columnheader">Запас</th><th scope="col" role="columnheader">Спрос / срок</th><th scope="col" role="columnheader">Заказ / бюджет</th><th scope="col" role="columnheader">Покрытие</th><th scope="col" role="columnheader">Действие</th></tr></thead><tbody role="rowgroup">{rows.map((row: Recommendation) => <tr role="row" key={row.id} onClick={() => onOpen(row)}><td role="cell" data-label="Приоритет"><span className={`urgency ${row.urgency.toLowerCase()}`}><i />{urgencyLabels[row.urgency]}</span></td><td role="cell" data-label="Товар"><strong className="sku">{row.sku}</strong><span className="cell-muted">{row.product_name}</span></td><td role="cell" data-label="Поставщик / склад"><strong>{row.supplier_name}</strong><span className="cell-muted">{row.warehouse}</span></td><td role="cell" data-label="Остаток и в пути"><strong>{money(row.current_stock + row.in_transit)}</strong><span className="cell-muted">{money(row.current_stock)} + {money(row.in_transit)} в пути</span></td><td role="cell" data-label="Спрос / срок поставки"><strong>{money(row.forecast_lead_time)} ед.</strong><span className="cell-muted">{row.lead_time_days} дн. поставки</span></td><td role="cell" data-label="К заказу / бюджет"><strong className="order-number">{money(row.final_quantity)} ед.</strong><span className="cell-muted">{row.total_cost_kzt ? `${money(row.total_cost_kzt)} ₸` : ({ DRAFT: 'Черновик', ADJUSTED: 'Изменено', APPROVED: 'Утверждено' }[row.status])}</span></td><td role="cell" data-label="Покрытие запаса"><div className="cover"><strong>{row.days_of_cover} дн.</strong><div><i style={{ width: `${Math.min(row.days_of_cover / Math.max(row.lead_time_days, 1) * 100, 100)}%` }} /></div></div></td><td role="cell" data-label="Details"><button aria-label={`Open ${row.sku}, ${row.warehouse}`} className="row-arrow" onClick={event => { event.stopPropagation(); onOpen(row) }}>→</button></td></tr>)}</tbody></table>{!rows.length && <div className="empty">По этим фильтрам позиций нет.</div>}</div>
    </section>
    <SupplierGroups rows={rows} onOpen={onOpen} />
  </>
}

function SupplierGroups({ rows, onOpen }: { rows: Recommendation[]; onOpen: (row: Recommendation) => void }) {
  const grouped = rows.reduce<Record<string, Recommendation[]>>((result, row) => { (result[row.supplier_id] ||= []).push(row); return result }, {})
  const groups = Object.entries(grouped)
  if (!groups.length) return null
  return <section className="supplier-grid"><div className="supplier-section-title"><div><p className="eyebrow">ПОСТАВЩИКИ</p><h3>Заказы по поставщикам</h3></div><span>Проверьте перед утверждением</span></div>{groups.slice(0, 6).map(([id, items]) => {
    const totalUnits = items.reduce((sum, item) => sum + item.final_quantity, 0)
    const totalCost = items.reduce((sum, item) => sum + (item.total_cost_kzt || 0), 0)
    return <div className="supplier-card" key={id}><div className="supplier-card-head"><div><strong>{items[0].supplier_name}</strong><small>{items.length} SKU{items.length === 1 ? '' : 's'} · {items[0].lead_time_days} day lead</small></div><div style={{ textAlign: 'right' }}><b>{money(totalUnits)} u</b>{totalCost > 0 && <small style={{ display: 'block', color: 'var(--text-muted)' }}>{money(totalCost)} ₸</small>}</div></div>{items.filter(item => item.final_quantity > 0).slice(0, 4).map(item => <button className="supplier-row" key={item.id} onClick={() => onOpen(item)}><span><strong>{item.sku}</strong><small>{item.product_name}</small></span><em className={item.urgency.toLowerCase()}>{money(item.final_quantity)} u {item.total_cost_kzt ? `· ${money(item.total_cost_kzt)} ₸` : ''}</em></button>)}</div>
  })}</section>
}

function Detail({ row, analytics, onClose, onChanged }: { row: Recommendation; analytics: { points: Point[]; outliers: unknown[] } | null; onClose: () => void; onChanged: (row: Recommendation) => void }) {
  const [quantity, setQuantity] = useState(row.final_quantity)
  const [saving, setSaving] = useState(false)
  const points = analytics?.points || []
  const chartPoints = compactChartPoints(points)
  const forecastStart = chartPoints.find(point => point.forecast !== undefined)?.date
  const forecastEnd = chartPoints[chartPoints.length - 1]?.date
  const save = async () => { setSaving(true); try { onChanged(await adjustOrder(row.id, quantity)) } finally { setSaving(false) } }
  const approve = async () => { setSaving(true); try { onChanged(await approveOrder(row.id)) } finally { setSaving(false) } }
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={event => event.stopPropagation()}><div className="drawer-head"><div><span className={`urgency ${row.urgency.toLowerCase()}`}><i />{urgencyLabels[row.urgency]}</span><h2>{row.sku}</h2><p>{row.product_name} · {row.warehouse}</p></div><button className="close" aria-label="Закрыть карточку" onClick={onClose}>×</button></div><div className="drawer-body"><div className="mini-grid"><div><span>Поставщик</span><strong>{row.supplier_name}</strong></div><div><span>Срок поставки</span><strong>{row.lead_time_days} days</strong></div><div><span>Остаток и транзит</span><strong>{money(row.inventory_position)} ед.</strong></div><div><span>Тренд</span><strong className={row.trend_direction === 'growing' ? 'text-green' : ''}>{row.trend_direction} {row.trend_percent > 0 ? `+${row.trend_percent}%` : `${row.trend_percent}%`}</strong></div></div><div className="mini-grid"><div><span>Средний спрос в день</span><strong>{money(row.average_daily_demand)} u/day</strong></div><div><span>Колебания спроса</span><strong>{money(Number(row.metadata?.demand_std || 0))} σ</strong></div><div><span>Сезонность</span><strong>{row.seasonality_detected ? 'Выявлена' : 'Не выявлена'}</strong></div><div><span>Корректировки</span><strong>{row.outliers_removed} anomalies · {money(row.estimated_lost_demand)} lost demand</strong></div></div><div className="chart-card"><div className="chart-title"><span>Динамика спроса</span><small>недельные средние · 90 дней и прогноз</small></div><ResponsiveContainer width="100%" height={210}><ComposedChart data={chartPoints} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}><defs><linearGradient id="adjusted" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#b8e986" stopOpacity={.5}/><stop offset="100%" stopColor="#b8e986" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#e6eaf0" vertical={false}/>{forecastStart && forecastEnd && <ReferenceArea x1={forecastStart} x2={forecastEnd} fill="#edf2fd" fillOpacity={.8} />}{chartPoints.filter(point => point.is_stockout).map(point => <ReferenceArea key={`stockout-${point.date}`} x1={point.date} x2={point.date} fill="#f2b2aa" fillOpacity={.24} />)}<XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={value => value.slice(5)} minTickGap={35}/><YAxis tick={{ fontSize: 9 }} width={28}/><Tooltip/><Area type="monotone" dataKey="actual_sales" stroke="#90a0b5" fill="none" strokeWidth={1.5} dot={false}/><Area type="monotone" dataKey="adjusted_demand" stroke="#70ad45" fill="url(#adjusted)" strokeWidth={2} dot={false}/><Area type="monotone" dataKey="forecast" stroke="#3f6ed8" fill="none" strokeWidth={2} strokeDasharray="5 4" dot={false}/><Scatter data={chartPoints.filter(point => point.is_outlier)} dataKey="actual_sales" fill="#d96c66" name="Anomaly" /></ComposedChart></ResponsiveContainer><div className="chart-legend"><span><i className="legend-dot actual" />actual</span><span><i className="legend-dot adjusted" />adjusted</span><span><i className="legend-dot forecast" />forecast</span><span><i className="legend-dot stockout" />stockout</span><span><i className="legend-dot anomaly" />anomaly</span></div></div><div className="calc-card"><p className="eyebrow">РАСЧЁТ КОЛИЧЕСТВА</p><div className="calc-line"><span>Спрос за срок поставки</span><strong>{money(row.forecast_lead_time)}</strong></div><div className="calc-line"><span>+ Страховой запас</span><strong>{money(row.safety_stock)}</strong></div><div className="calc-line minus"><span>− Остаток и транзит</span><strong>− {money(row.inventory_position)}</strong></div><div className="calc-total"><span>Рекомендовано</span><strong>{money(row.recommended_quantity)} u {row.total_cost_kzt ? `(${money(row.total_cost_kzt)} ₸)` : ''}</strong></div></div><div className="reason"><div className="reason-icon">✦</div><div><strong>Почему такое количество?</strong><p>{row.explanation}</p></div></div><div className="adjust"><label htmlFor="final-quantity">Итоговое количество</label><div><input id="final-quantity" type="number" min="0" value={quantity} onChange={event => setQuantity(Number(event.target.value))}/><button className="button subtle" onClick={save} disabled={saving}>Сохранить</button></div></div><div className="drawer-actions"><button className="button primary wide" onClick={approve} disabled={saving || row.status === 'APPROVED'}>{row.status === 'APPROVED' ? '✓ Утверждено' : 'Утвердить заказ'}</button><small>Перед действиями с поставщиком требуется утверждение.</small></div></div></aside></div>
}

function compactChartPoints(points: Point[]): Point[] {
  const history = points.filter(point => point.forecast === undefined)
  const forecast = points.filter(point => point.forecast !== undefined)
  if (history.length <= 120) return points
  const latestDate = Date.parse(history[history.length - 1].date)
  const cutoff = latestDate - 90 * 24 * 60 * 60 * 1000
  const recent = history.filter(point => Date.parse(point.date) >= cutoff)
  const compacted: Point[] = []
  for (let index = 0; index < recent.length; index += 7) {
    const bucket = recent.slice(index, index + 7)
    const actual = bucket.map(point => point.actual_sales).filter((value): value is number => value !== null)
    const adjusted = bucket.map(point => point.adjusted_demand).filter((value): value is number => value !== null)
    compacted.push({
      date: bucket[0].date,
      actual_sales: actual.length ? actual.reduce((sum, value) => sum + value, 0) / actual.length : null,
      adjusted_demand: adjusted.length ? adjusted.reduce((sum, value) => sum + value, 0) / adjusted.length : null,
      is_outlier: bucket.some(point => point.is_outlier),
      is_stockout: bucket.some(point => point.is_stockout),
    })
  }
  return [...compacted, ...forecast]
}

function Imports({ onToast, onRefresh, onEkt, onAnomalies }: { onToast: (message: string) => void; onRefresh: () => void; onEkt: () => void; onAnomalies: () => void }) {
  const [results, setResults] = useState<Record<string, string>>({})
  const datasets = [{ key: 'sales', title: 'История продаж', detail: 'ежедневные продажи · CSV / XLSX' }, { key: 'stock', title: 'Остатки', detail: 'остатки товаров по складам' }, { key: 'transit', title: 'Товары в пути', detail: 'ожидаемые поставки' }, { key: 'stockouts', title: 'Периоды отсутствия', detail: 'корректировка потерянного спроса' }, { key: 'suppliers', title: 'Поставщики', detail: 'сроки · минимальный заказ · упаковка' }]
  const handle = async (key: string, file?: File) => { if (!file) return; try { const response = await uploadFile(key, file); setResults(current => ({ ...current, [key]: `${response.rows_loaded} rows loaded · ${response.recommendations} recommendations` })); const messages = [...response.errors, ...response.warnings]; onToast(messages.length ? messages.join(' · ') : `${file.name} loaded and recalculated`); onRefresh() } catch (error) { onToast(error instanceof Error ? error.message : 'Upload failed') } }
  const handleWorkbook = async (file?: File) => { if (!file) return; try { const response = await uploadWorkbook(file); const messages = [...response.errors, ...response.warnings]; onToast(messages.length ? messages.join(' · ') : `Excel workbook loaded: ${response.recommendations} recommendations calculated!`); onRefresh() } catch (error) { onToast(error instanceof Error ? error.message : 'Workbook upload failed') } }

  return <section className="import-page"><div className="page-intro"><div><p className="eyebrow">ИСТОЧНИКИ</p><h2>Данные для планирования</h2><p>Загрузите отдельные таблицы или книгу из пяти листов. Поддерживаются русские и английские заголовки.</p></div><div className="import-actions"><button className="button subtle" onClick={async () => { await loadDemo(); await calculate(); onRefresh(); onToast('Demo dataset loaded') }}>Демо-набор</button><button className="button primary" onClick={onEkt}>Отраслевой демо-набор</button><button className="button subtle" onClick={onAnomalies}>Стрессовый набор</button></div></div>
    <div style={{ marginBottom: '24px' }}>
      <label className="dropzone" style={{ border: '2px dashed #70ad45', padding: '24px', background: 'rgba(112, 173, 69, 0.05)' }}>
        <input type="file" accept=".xlsx,.xls" onChange={event => handleWorkbook(event.target.files?.[0])} />
        <div className="drop-icon" style={{ color: '#70ad45', fontSize: '28px' }}>📑</div>
        <strong style={{ fontSize: '16px' }}>Загрузить книгу Excel · 5 листов</strong>
        <span>Продажи, остатки, транзит, поставщики и периоды отсутствия товара</span>
        <small>Выберите файл .xlsx или .xls</small>
      </label>
    </div>
    <div className="import-grid">{datasets.map(item => <label className="dropzone" key={item.key}><input type="file" accept=".csv,.xlsx,.xls" onChange={event => handle(item.key, event.target.files?.[0])}/><div className="drop-icon">↥</div><strong>{item.title}</strong><span>{results[item.key] || item.detail}</span><small>Выбрать файл</small></label>)}</div><div className="privacy-note"><span>◉</span><div><strong>Контроль остаётся у вас</strong><p>Заказы не отправляются автоматически. Идентификаторы клиентов используются как обезличенные ссылки.</p></div></div></section>
}

function Anomalies({ onOpen }: { onOpen: (row: Recommendation) => void }) {
  const [items, setItems] = useState<any[]>([])
  useEffect(() => { getOutliers().then(result => setItems(result.outliers as any[])) }, [])
  return <section className="content-card anomaly-page"><div className="card-header"><div><p className="eyebrow">ПРОВЕРКА СПРОСА</p><h3>Обнаруженные аномалии <span>{items.length}</span></h3><p className="subcopy">Крупные разовые продажи исключаются из регулярного спроса. Исходные данные сохраняются.</p></div></div><div className="table-wrap"><table className="anomaly-table" role="table" aria-label="Detected anomalies"><thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">Дата</th><th role="columnheader" scope="col">Артикул / склад</th><th role="columnheader" scope="col">Клиент</th><th role="columnheader" scope="col">Количество</th><th role="columnheader" scope="col">Обычный уровень</th><th role="columnheader" scope="col">В прогнозе</th><th role="columnheader" scope="col">Причина</th></tr></thead><tbody role="rowgroup">{items.map((item, index) => <tr key={index} role="row"><td role="cell" data-label="Дата">{item.date}</td><td role="cell" data-label="Артикул / склад"><strong>{item.sku}</strong><span className="cell-muted">{item.warehouse}</span></td><td role="cell" data-label="Клиент">{item.customer_id}</td><td role="cell" data-label="Количество"><strong className="danger-text">{money(item.quantity)}</strong></td><td role="cell" data-label="Обычный уровень">{money(item.typical_quantity)}</td><td role="cell" data-label="В прогнозе"><span className="reason-pill">{item.used_in_forecast ? 'Учтено' : 'Исключено'}</span></td><td role="cell" data-label="Причина"><span className="reason-pill">{item.reason}</span></td></tr>)}</tbody></table>{!items.length && <div className="empty">Аномалии пока не обнаружены. Загрузите данные и выполните расчёт.</div>}</div></section>
}
