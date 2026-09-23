import { useEffect, useRef, useState } from 'react'
import { calculate, exportUrl, getAnalytics, getEditorState, getRecommendations } from './api'
import DataEditor from './DataEditor'
import Settings from './Settings'
import { useI18n, translateText } from './i18n'
import OrderHistory from './OrderHistory'
import { Anomalies, Imports } from './DataPages'
import ItemDetail from './ItemDetail'
import Procurement from './Procurement'
import type { Point, Recommendation, Summary } from './types'
import { Badge, Icon, Modal, number, warehouseName } from './ui'

const nav = [{ key: 'overview', label: 'План закупок', icon: 'plan', description: 'Проверьте рекомендации и подготовьте заказы поставщикам.' }, { key: 'data', label: 'Данные', icon: 'data', description: 'Загрузка файлов и управление исходными данными.' }, { key: 'exceptions', label: 'Исключения', icon: 'alert', description: 'Аномальные продажи и их влияние на прогноз.' }, { key: 'history', label: 'История', icon: 'history', description: 'Результаты работы с текущими рекомендациями.' }, { key: 'settings', label: 'Настройки', icon: 'settings', description: 'Параметры интерфейса и рабочего процесса.' }, { key: 'policies', label: 'Политики', icon: 'settings', description: 'Сроки поставки и ограничения заказа.' }]
const initialSummary: Summary = { skus_requiring_replenishment: 0, critical_risks: 0, total_recommended_units: 0, suppliers_involved: 0, detected_anomalies: 0, estimated_lost_demand: 0 }
export default function App() {
  const { t, settings, formatDate } = useI18n()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('stockpilot.sidebar-collapsed') === 'true')
  useEffect(() => { localStorage.setItem('stockpilot.sidebar-collapsed', String(collapsed)) }, [collapsed])
  const [page, setPage] = useState('overview')
  const [dataTab, setDataTab] = useState('editor')
  const [restoreDraft, setRestoreDraft] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [rows, setRows] = useState<Recommendation[]>([])
  const [summary, setSummary] = useState(initialSummary)
  const [selected, setSelected] = useState<Recommendation | null>(null)
  const [points, setPoints] = useState<Point[]>([])
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [analyticsError, setAnalyticsError] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const requestId = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  const showToast = (message: string) => { clearTimeout(timer.current); setToast(message); timer.current = window.setTimeout(() => setToast(''), 7000) }
  const refresh = async () => { setBusy(true); try { const r = await getRecommendations(); setRows(r.recommendations); setSummary(r.summary); setError('') } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось загрузить рекомендации') } finally { setBusy(false) } }
  useEffect(() => { void refresh(); getEditorState().then(r => { if (r.draft && settings.autoOpenDraft) { setRestoreDraft(true); setPage('data') } }).catch(() => undefined); return () => clearTimeout(timer.current) }, [])
  const run = async (action: () => Promise<unknown>) => { setBusy(true); try { await action(); await refresh(); showToast('Данные обновлены') } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось выполнить действие') } finally { setBusy(false) } }
  const open = async (row: Recommendation) => { const id = ++requestId.current; setSelected(row); setPoints([]); setAnalyticsLoading(true); setAnalyticsError(''); try { const r = await getAnalytics(row.sku, row.warehouse); if (requestId.current === id) setPoints(r.points) } catch (e) { if (requestId.current === id) setAnalyticsError(e instanceof Error ? e.message : 'Аналитика недоступна') } finally { if (requestId.current === id) setAnalyticsLoading(false) } }
  const navigation = <nav aria-label={translateText("Основная навигация")}>{nav.map(item => <button title={translateText(item.label)} key={item.key} className={`nav-item ${page === item.key ? 'active' : ''}`} aria-current={page === item.key ? 'page' : undefined} onClick={() => { setPage(item.key); setMobileNav(false) }}><Icon name={item.icon}/><span>{translateText(item.label)}</span></button>)}</nav>
  const current = nav.find(n => n.key === page)!
  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
    <aside className="sidebar"><div className="brand"><span className="brand-mark">B</span><span>basqar<small>{translateText("Управление закупками")}</small></span></div>{navigation}<button className="nav-item sidebar-collapse" aria-label={collapsed ? t('sidebarShow') : t('sidebarHide')} onClick={() => setCollapsed(v => !v)}><Icon name="menu"/><span>{collapsed ? t('sidebarShow') : t('sidebarHide')}</span></button><div className="sidebar-bottom">{translateText("Рабочее пространство")}<small>{translateText("Запасы и пополнение")}</small></div></aside>
    <main className="main"><header className="topbar"><div className="heading"><button className="icon-button mobile-menu" aria-label={translateText("Открыть меню")} onClick={() => setMobileNav(true)}><Icon name="menu"/></button><div><h1>{translateText(current.label)}</h1><p>{current.description}</p></div></div><div className="actions"><button className="button primary" disabled={busy} onClick={() => run(calculate)}><Icon name="refresh"/>{busy ? 'Загрузка…' : 'Пересчитать'}</button><button className="button subtle" disabled={!rows.length} onClick={() => setExportOpen(true)}><Icon name="export"/>{translateText("Экспорт")}</button></div></header>
      <div className="context-line">Все склады · данные на {summary.data_as_of ? formatDate(summary.data_as_of) : 'дату источника'}</div>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button className="button subtle" disabled={busy} onClick={refresh}>{translateText("Повторить")}</button></div>}
      {page === 'overview' && <Procurement rows={rows} summary={summary} selectedId={selected?.id} onOpen={open} busy={busy}/>}
      {page === 'data' && <><div className="page-tabs"><button aria-pressed={dataTab === 'editor'} onClick={() => setDataTab('editor')}>{translateText("Редактор данных")}</button><button aria-pressed={dataTab === 'import'} onClick={() => setDataTab('import')}>{translateText("Загрузка файлов")}</button></div>{dataTab === 'editor' ? <DataEditor onToast={showToast} onRefresh={refresh} recommendations={rows} initialReference={restoreDraft}/> : <Imports onToast={showToast} onRefresh={refresh}/>}</>}
      {page === 'exceptions' && <Anomalies/>}
      {page === 'history' && <section className="content-card"><div className="card-header"><div><h2>{translateText("Изменённые и утверждённые позиции")}</h2><p>{translateText("Позиции текущего расчёта. Предыдущие версии доступны в архиве ниже.")}</p></div></div><div className="supplier-list">{rows.filter(r => r.status !== 'DRAFT').map(r => <button className="supplier-item" key={r.id} onClick={() => open(r)}><span>{r.product_name}<small>{r.sku} · {warehouseName(r.warehouse)}</small></span><strong>{number(r.final_quantity)} ед.</strong><Badge value={r.status}/></button>)}{!rows.some(r => r.status !== 'DRAFT') && <p className="empty">{translateText("Изменений в текущем расчёте нет.")}</p>}</div></section>}
      {page === 'history' && <OrderHistory/>}
      {page === 'settings' && <Settings/>}
      {page === 'policies' && <section className="content-card panel-body"><h2>{translateText("Параметры закупок")}</h2><p>{translateText("Сроки поставки, минимальные партии и кратность упаковки задаются в исходных данных поставщиков. Расчёт использует существующие правила backend.")}</p><button className="button subtle" onClick={() => { setDataTab('editor'); setPage('data') }}>{translateText("Открыть редактор данных")}</button><p className="caption">{translateText("Для изменения параметров выберите «Справочники» → «Поставщики».")}</p></section>}
    </main>
    {mobileNav && <Modal title="basqar" className="navigation-drawer" onClose={() => setMobileNav(false)}>{navigation}</Modal>}
    {selected && <ItemDetail key={selected.id} row={selected} points={points} loading={analyticsLoading} analyticsError={analyticsError} onClose={() => { setSelected(null); requestId.current++ }} onChanged={r => { setSelected(r); setRows(old => old.map(item => item.id === r.id ? r : item)); void refresh(); showToast(r.status === 'APPROVED' ? 'Позиция утверждена' : 'Количество сохранено') }}/>}
    {exportOpen && <Modal title={translateText("Экспорт заказов")} onClose={() => setExportOpen(false)}><div className="panel-body"><p>Экспортируются все {rows.length} рекомендаций текущего расчёта. Фильтры таблицы не применяются.</p><div className="actions"><a className="button primary" href={exportUrl('xlsx')}>{translateText("Скачать XLSX")}</a><a className="button subtle" href={exportUrl('csv')}>{translateText("Скачать CSV")}</a></div></div></Modal>}
    {toast && <div className="toast" role="status"><span>{toast}</span><button className="icon-button" aria-label={translateText("Закрыть уведомление")} onClick={() => setToast('')}><Icon name="close"/></button></div>}
  </div>
}
