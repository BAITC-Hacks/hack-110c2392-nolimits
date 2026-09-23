import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, ReferenceArea, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { adjustOrder, approveOrder, calculate, exportUrl, getAnalytics, getOutliers, getRecommendations, loadDemo, loadEkt, loadEktExtreme, uploadFile, uploadWorkbook } from './api'
import type { Point, Recommendation, Summary, Urgency } from './types'

const nav = [{ key: 'overview', label: 'Overview', icon: '◒' }, { key: 'imports', label: 'Data intake', icon: '↥' }, { key: 'anomalies', label: 'Anomalies', icon: '⌁' }]
const urgencyOrder: Record<Urgency, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
const money = (value: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value)

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
  const openSku = async (row: Recommendation) => { setSelected(row); try { setAnalytics(await getAnalytics(row.sku, row.warehouse)) } catch { showToast('Could not load SKU analytics') } }
  const visibleRows = useMemo(() => rows.filter(row => (urgency === 'ALL' || row.urgency === urgency) && (warehouse === 'ALL' || row.warehouse === warehouse) && (supplier === 'ALL' || row.supplier_id === supplier) && (category === 'ALL' || row.category === category) && (!search || `${row.sku} ${row.product_name}`.toLowerCase().includes(search.toLowerCase()))).sort((a, b) => sort === 'urgency' ? urgencyOrder[a.urgency] - urgencyOrder[b.urgency] : b[sort] - a[sort]), [rows, urgency, warehouse, supplier, category, search, sort])

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">S</div><div><strong>stockpilot</strong><span>replenishment OS</span></div></div>
      <div className="side-label">CONTROL ROOM</div>
      <nav>{nav.map(item => <button key={item.key} className={page === item.key ? 'nav-item active' : 'nav-item'} onClick={() => { setPage(item.key); setSelected(null) }}><span>{item.icon}</span>{item.label}</button>)}</nav>
      <div className="sidebar-bottom"><div className="live-dot"><i /> Engine online</div><small>v1.1 · ekt.kz ready</small></div>
    </aside>
    <main className="main"><header className="topbar"><div><p className="eyebrow">PURCHASING / WAREHOUSE CONTROL</p><h1>{page === 'overview' ? 'Replenishment Cockpit' : nav.find(item => item.key === page)?.label}</h1></div><div className="top-actions"><span className="date-chip">● Live data · {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span><button className="button subtle" onClick={demo} disabled={busy}>↻ Synthetic demo</button><button className="button primary" onClick={ekt} disabled={busy}>⚡️ ekt.kz Dataset (Казахстан)</button></div></header>
      {page === 'overview' && <Overview rows={visibleRows} allRows={rows} summary={summary} search={search} setSearch={setSearch} urgency={urgency} setUrgency={setUrgency} warehouse={warehouse} setWarehouse={setWarehouse} supplier={supplier} setSupplier={setSupplier} category={category} setCategory={setCategory} warehouses={warehouses} sort={sort} setSort={setSort} onOpen={openSku} onRefresh={refresh} onToast={showToast} />}
      {page === 'imports' && <Imports onToast={showToast} onRefresh={refresh} onEkt={ekt} onExtreme={async () => { setBusy(true); try { const response = await loadEktExtreme(); await refresh(); showToast(`Stress dataset loaded: ${response.outliers} anomalies detected`) } catch (error) { showToast(error instanceof Error ? error.message : 'Could not load stress dataset') } finally { setBusy(false) } }} />}
      {page === 'anomalies' && <Anomalies onOpen={openSku} />}
    </main>
    {selected && <Detail row={selected} analytics={analytics} onClose={() => setSelected(null)} onChanged={async row => { setRows(current => current.map(item => item.id === row.id ? row : item)); setSelected(row); showToast(row.status === 'APPROVED' ? 'Order approved' : 'Quantity adjusted') }} />}
    {toast && <div className="toast">{toast}</div>}
  </div>
}

function Overview({ rows, allRows, summary, search, setSearch, urgency, setUrgency, warehouse, setWarehouse, supplier, setSupplier, category, setCategory, warehouses, sort, setSort, onOpen, onRefresh, onToast }: any) {
  const cards = [
    { label: 'Need replenishment', value: summary.skus_requiring_replenishment, note: 'SKU / warehouse pairs', icon: '↗', tone: 'lime' },
    { label: 'Critical risk', value: summary.critical_risks, note: 'stockout before arrival', icon: '!', tone: 'red' },
    { label: 'Units to order', value: money(summary.total_recommended_units), note: 'after package rounding', icon: '⌁', tone: 'blue' },
    { label: 'Order budget', value: summary.total_budget_kzt ? `${money(summary.total_budget_kzt)} ₸` : '—', note: 'estimated procurement cost', icon: '₸', tone: 'cyan' },
    { label: 'Suppliers involved', value: summary.suppliers_involved, note: 'ready to review', icon: '◌', tone: 'violet' },
    { label: 'Anomalies removed', value: summary.detected_anomalies, note: 'preserved for audit', icon: '∿', tone: 'amber' },
    { label: 'Lost demand added', value: money(summary.estimated_lost_demand), note: 'stockout correction', icon: '＋', tone: 'cyan' }
  ]
  const suppliers: Array<[string, string]> = [...new Map<string, string>(allRows.map((row: Recommendation) => [row.supplier_id, row.supplier_name] as [string, string])).entries()]
  const categories: string[] = [...new Set<string>(allRows.map((row: Recommendation) => row.category))]
  return <>
    <section className="hero-row"><div><h2>What should we order<br /><em>right now?</em></h2><p>Recommendations balance demand, stock, incoming goods and supplier constraints — with a reason for every number.</p></div><div className="hero-visual"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="hero-core">{summary.critical_risks}<small>critical<br />risks</small></div></div></section>
    <section className="kpi-grid">{cards.map(card => <div className={`kpi-card ${card.tone}`} key={card.label}><div className="kpi-top"><span>{card.icon}</span><small>{card.label}</small></div><strong>{card.value}</strong><p>{card.note}</p></div>)}</section>
    <section className="content-card"><div className="card-header"><div><p className="eyebrow">ACTION QUEUE</p><h3>Recommended orders <span>{allRows.length}</span></h3></div><div className="header-actions"><a href={exportUrl('csv')} className="button subtle">↓ CSV</a><a href={exportUrl('xlsx')} className="button subtle">↓ XLSX</a></div></div>
      <div className="filters"><div className="search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search SKU or product…" /></div><select value={warehouse} onChange={event => setWarehouse(event.target.value)}><option value="ALL">All warehouses</option>{warehouses.map((item: string) => <option key={item}>{item}</option>)}</select><select value={supplier} onChange={event => setSupplier(event.target.value)}><option value="ALL">All suppliers</option>{suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><select value={category} onChange={event => setCategory(event.target.value)}><option value="ALL">All categories</option>{categories.map((item: string) => <option key={item}>{item}</option>)}</select><select value={urgency} onChange={event => setUrgency(event.target.value)}><option value="ALL">All urgency</option><option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select><select value={sort} onChange={event => setSort(event.target.value)}><option value="urgency">Sort by urgency</option><option value="recommended_quantity">Largest order</option><option value="days_of_cover">Lowest cover</option></select><button className="icon-button" onClick={onRefresh}>↻</button></div>
      <div className="table-wrap"><table><thead><tr><th>Urgency</th><th>SKU / product</th><th>Supplier</th><th>Stock position</th><th>Demand / lead time</th><th>Order & Budget</th><th>Cover</th><th>Action</th></tr></thead><tbody>{rows.map((row: Recommendation) => <tr key={row.id} onClick={() => onOpen(row)}><td><span className={`urgency ${row.urgency.toLowerCase()}`}><i />{row.urgency}</span></td><td><strong className="sku">{row.sku}</strong><span className="cell-muted">{row.product_name}</span></td><td><strong>{row.supplier_name}</strong><span className="cell-muted">{row.warehouse}</span></td><td><strong>{money(row.current_stock + row.in_transit)}</strong><span className="cell-muted">{money(row.current_stock)} + {money(row.in_transit)} in</span></td><td><strong>{money(row.forecast_lead_time)} u</strong><span className="cell-muted">{row.lead_time_days} day lead</span></td><td><strong className="order-number">{money(row.final_quantity)} u</strong><span className="cell-muted">{row.total_cost_kzt ? `${money(row.total_cost_kzt)} ₸` : row.status.toLowerCase()}</span></td><td><div className="cover"><strong>{row.days_of_cover}d</strong><div><i style={{ width: `${Math.min(row.days_of_cover / Math.max(row.lead_time_days, 1) * 100, 100)}%` }} /></div></div></td><td><button className="row-arrow" onClick={event => { event.stopPropagation(); onOpen(row) }}>→</button></td></tr>)}</tbody></table>{!rows.length && <div className="empty">No recommendations match these filters.</div>}</div>
    </section>
    <SupplierGroups rows={rows} onOpen={onOpen} />
  </>
}

function SupplierGroups({ rows, onOpen }: { rows: Recommendation[]; onOpen: (row: Recommendation) => void }) {
  const grouped = rows.reduce<Record<string, Recommendation[]>>((result, row) => { (result[row.supplier_id] ||= []).push(row); return result }, {})
  const groups = Object.entries(grouped)
  if (!groups.length) return null
  return <section className="supplier-grid"><div className="supplier-section-title"><div><p className="eyebrow">ORDER PACKETS</p><h3>Grouped by supplier</h3></div><span>Review before approval</span></div>{groups.slice(0, 6).map(([id, items]) => {
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
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={event => event.stopPropagation()}><div className="drawer-head"><div><span className={`urgency ${row.urgency.toLowerCase()}`}><i />{row.urgency}</span><h2>{row.sku}</h2><p>{row.product_name} · {row.warehouse}</p></div><button className="close" onClick={onClose}>×</button></div><div className="drawer-body"><div className="mini-grid"><div><span>Supplier</span><strong>{row.supplier_name}</strong></div><div><span>Lead time</span><strong>{row.lead_time_days} days</strong></div><div><span>Stock + incoming</span><strong>{money(row.inventory_position)} u</strong></div><div><span>Trend</span><strong className={row.trend_direction === 'growing' ? 'text-green' : ''}>{row.trend_direction} {row.trend_percent > 0 ? `+${row.trend_percent}%` : `${row.trend_percent}%`}</strong></div></div><div className="mini-grid"><div><span>Recent daily demand</span><strong>{money(row.average_daily_demand)} u/day</strong></div><div><span>Demand volatility</span><strong>{money(Number(row.metadata?.demand_std || 0))} σ</strong></div><div><span>Seasonality</span><strong>{row.seasonality_detected ? 'Detected' : 'Not detected'}</strong></div><div><span>Audit adjustments</span><strong>{row.outliers_removed} anomalies · {money(row.estimated_lost_demand)} lost demand</strong></div></div><div className="chart-card"><div className="chart-title"><span>Demand signal</span><small>weekly averages · recent 90d + forecast</small></div><ResponsiveContainer width="100%" height={210}><ComposedChart data={chartPoints} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}><defs><linearGradient id="adjusted" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#b8e986" stopOpacity={.5}/><stop offset="100%" stopColor="#b8e986" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#e6eaf0" vertical={false}/>{forecastStart && forecastEnd && <ReferenceArea x1={forecastStart} x2={forecastEnd} fill="#edf2fd" fillOpacity={.8} />}{chartPoints.filter(point => point.is_stockout).map(point => <ReferenceArea key={`stockout-${point.date}`} x1={point.date} x2={point.date} fill="#f2b2aa" fillOpacity={.24} />)}<XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={value => value.slice(5)} minTickGap={35}/><YAxis tick={{ fontSize: 9 }} width={28}/><Tooltip/><Area type="monotone" dataKey="actual_sales" stroke="#90a0b5" fill="none" strokeWidth={1.5} dot={false}/><Area type="monotone" dataKey="adjusted_demand" stroke="#70ad45" fill="url(#adjusted)" strokeWidth={2} dot={false}/><Area type="monotone" dataKey="forecast" stroke="#3f6ed8" fill="none" strokeWidth={2} strokeDasharray="5 4" dot={false}/><Scatter data={chartPoints.filter(point => point.is_outlier)} dataKey="actual_sales" fill="#d96c66" name="Anomaly" /></ComposedChart></ResponsiveContainer><div className="chart-legend"><span><i className="legend-dot actual" />actual</span><span><i className="legend-dot adjusted" />adjusted</span><span><i className="legend-dot forecast" />forecast</span><span><i className="legend-dot stockout" />stockout</span><span><i className="legend-dot anomaly" />anomaly</span></div></div><div className="calc-card"><p className="eyebrow">CALCULATION TRACE</p><div className="calc-line"><span>Forecast during lead time</span><strong>{money(row.forecast_lead_time)}</strong></div><div className="calc-line"><span>+ Safety stock</span><strong>{money(row.safety_stock)}</strong></div><div className="calc-line minus"><span>− Current stock / incoming</span><strong>− {money(row.inventory_position)}</strong></div><div className="calc-total"><span>Recommended quantity</span><strong>{money(row.recommended_quantity)} u {row.total_cost_kzt ? `(${money(row.total_cost_kzt)} ₸)` : ''}</strong></div></div><div className="reason"><div className="reason-icon">✦</div><div><strong>Why this number?</strong><p>{row.explanation}</p></div></div><div className="adjust"><label>Final quantity</label><div><input type="number" min="0" value={quantity} onChange={event => setQuantity(Number(event.target.value))}/><button className="button subtle" onClick={save} disabled={saving}>Save adjustment</button></div></div><div className="drawer-actions"><button className="button primary wide" onClick={approve} disabled={saving || row.status === 'APPROVED'}>{row.status === 'APPROVED' ? '✓ Approved' : 'Approve order'}</button><small>Approval is required before any supplier action.</small></div></div></aside></div>
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

function Imports({ onToast, onRefresh, onEkt, onExtreme }: { onToast: (message: string) => void; onRefresh: () => void; onEkt: () => void; onExtreme: () => void }) {
  const [results, setResults] = useState<Record<string, string>>({})
  const datasets = [{ key: 'sales', title: 'Sales history', detail: 'daily transactions · CSV / XLSX' }, { key: 'stock', title: 'Current stock', detail: 'SKU inventory by warehouse' }, { key: 'transit', title: 'Goods in transit', detail: 'expected arrivals' }, { key: 'stockouts', title: 'Stockout windows', detail: 'lost demand correction' }, { key: 'suppliers', title: 'Supplier catalog', detail: 'lead times · MOQ · packages' }]
  const handle = async (key: string, file?: File) => { if (!file) return; try { const response = await uploadFile(key, file); setResults(current => ({ ...current, [key]: `${response.rows_loaded} rows loaded · ${response.recommendations} recommendations` })); const messages = [...response.errors, ...response.warnings]; onToast(messages.length ? messages.join(' · ') : `${file.name} loaded and recalculated`); onRefresh() } catch (error) { onToast(error instanceof Error ? error.message : 'Upload failed') } }
  const handleWorkbook = async (file?: File) => { if (!file) return; try { const response = await uploadWorkbook(file); const messages = [...response.errors, ...response.warnings]; onToast(messages.length ? messages.join(' · ') : `Excel workbook loaded: ${response.recommendations} recommendations calculated!`); onRefresh() } catch (error) { onToast(error instanceof Error ? error.message : 'Workbook upload failed') } }

  return <section className="import-page"><div className="page-intro"><div><p className="eyebrow">DATA FOUNDATION</p><h2>Bring your signals together.</h2><p>Upload clean operational data or full ekt.kz multi-sheet workbook. Supports both Russian and English headers.</p></div><div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}><button className="button subtle" onClick={async () => { await loadDemo(); await calculate(); onRefresh(); onToast('Demo dataset loaded') }}>✦ Load synthetic demo</button><button className="button subtle" onClick={onExtreme}>⚠️ Stress anomalies</button><button className="button primary" onClick={onEkt}>⚡️ Load ekt.kz Dataset (ТОО «Электрокомплект»)</button></div></div>
    <div style={{ marginBottom: '24px' }}>
      <label className="dropzone" style={{ border: '2px dashed #70ad45', padding: '24px', background: 'rgba(112, 173, 69, 0.05)' }}>
        <input type="file" accept=".xlsx,.xls" onChange={event => handleWorkbook(event.target.files?.[0])} />
        <div className="drop-icon" style={{ color: '#70ad45', fontSize: '28px' }}>📑</div>
        <strong style={{ fontSize: '16px' }}>Upload full ekt.kz Excel workbook (5 sheets in 1 file)</strong>
        <span>Automatically parses sales, stock, transit, suppliers, and stockouts with column alias normalization</span>
        <small>Drop `ekt_sales_and_stock_history.xlsx` or browse</small>
      </label>
    </div>
    <div className="import-grid">{datasets.map(item => <label className="dropzone" key={item.key}><input type="file" accept=".csv,.xlsx,.xls" onChange={event => handle(item.key, event.target.files?.[0])}/><div className="drop-icon">↥</div><strong>{item.title}</strong><span>{results[item.key] || item.detail}</span><small>Drop file or browse</small></label>)}</div><div className="privacy-note"><span>◉</span><div><strong>Designed for safe operations</strong><p>Customer IDs are treated as anonymized references only. No PII is required, and no order is sent automatically.</p></div></div></section>
}

function Anomalies({ onOpen }: { onOpen: (row: Recommendation) => void }) {
  const [items, setItems] = useState<any[]>([])
  useEffect(() => { getOutliers().then(result => setItems(result.outliers as any[])) }, [])
  return <section className="content-card anomaly-page"><div className="card-header"><div><p className="eyebrow">AUDIT TRAIL</p><h3>Detected anomalies <span>{items.length}</span></h3><p className="subcopy">Large one-off transactions are excluded from regular demand, never deleted.</p></div></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>SKU / warehouse</th><th>Customer</th><th>Quantity</th><th>Typical</th><th>Forecast use</th><th>Reason</th></tr></thead><tbody>{items.map((item, index) => <tr key={index}><td>{item.date}</td><td><strong>{item.sku}</strong><span className="cell-muted">{item.warehouse}</span></td><td>{item.customer_id}</td><td><strong className="danger-text">{money(item.quantity)}</strong></td><td>{money(item.typical_quantity)}</td><td><span className="reason-pill">{item.used_in_forecast ? 'Included' : 'Excluded'}</span></td><td><span className="reason-pill">{item.reason}</span></td></tr>)}</tbody></table>{!items.length && <div className="empty">No anomalies detected yet. Run the demo scenario to populate the audit trail.</div>}</div></section>
}
