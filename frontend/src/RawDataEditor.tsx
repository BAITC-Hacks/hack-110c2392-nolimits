import { useEffect, useMemo, useState } from 'react'
import {
  clearEditorDraft,
  createEditorRow,
  deleteEditorRow,
  editorExportUrl,
  getEditorRows,
  getEditorState,
  saveEditorDraft,
  updateEditorRow,
  type EditorDataset,
  type EditorRow,
} from './api'

type FieldType = 'text' | 'number' | 'date' | 'checkbox'
type Field = { key: string; label: string; type?: FieldType; required?: boolean }

const DATASETS: Array<{ key: EditorDataset; label: string; description: string; fields: Field[] }> = [
  { key: 'products', label: 'Товары', description: 'Справочник SKU для продаж и поставок', fields: [
    { key: 'sku', label: 'SKU', required: true }, { key: 'product_name', label: 'Название товара', required: true }, { key: 'category', label: 'Категория', required: true }, { key: 'unit_price', label: 'Цена', type: 'number' }, { key: 'active', label: 'Активен', type: 'checkbox' },
  ] },
  { key: 'sales', label: 'Продажи', description: 'Фактические продажи по дням', fields: [
    { key: 'date', label: 'Дата', type: 'date', required: true }, { key: 'sku', label: 'SKU', required: true }, { key: 'product_name', label: 'Название товара', required: true }, { key: 'quantity', label: 'Количество', type: 'number', required: true }, { key: 'price', label: 'Цена', type: 'number', required: true }, { key: 'customer_id', label: 'Клиент', required: true }, { key: 'warehouse', label: 'Склад', required: true }, { key: 'category', label: 'Категория', required: true },
  ] },
  { key: 'stock', label: 'Остатки', description: 'Текущий запас по складам', fields: [
    { key: 'sku', label: 'SKU', required: true }, { key: 'warehouse', label: 'Склад', required: true }, { key: 'current_stock', label: 'Остаток', type: 'number', required: true },
  ] },
  { key: 'transit', label: 'В пути', description: 'Ожидаемые поставки', fields: [
    { key: 'sku', label: 'SKU', required: true }, { key: 'warehouse', label: 'Склад', required: true }, { key: 'quantity_in_transit', label: 'Количество', type: 'number', required: true }, { key: 'expected_arrival_date', label: 'Дата поставки', type: 'date', required: true },
  ] },
  { key: 'stockouts', label: 'Дефициты', description: 'Периоды нулевого остатка', fields: [
    { key: 'sku', label: 'SKU', required: true }, { key: 'warehouse', label: 'Склад', required: true }, { key: 'start_date', label: 'Начало', type: 'date', required: true }, { key: 'end_date', label: 'Конец', type: 'date', required: true },
  ] },
  { key: 'suppliers', label: 'Поставщики', description: 'Lead time, MOQ и упаковка', fields: [
    { key: 'supplier_id', label: 'ID поставщика', required: true }, { key: 'supplier_name', label: 'Поставщик', required: true }, { key: 'sku', label: 'SKU', required: true }, { key: 'lead_time_days', label: 'Lead time, дней', type: 'number', required: true }, { key: 'moq', label: 'MOQ', type: 'number' }, { key: 'package_size', label: 'Упаковка', type: 'number' }, { key: 'unit_cost', label: 'Цена закупки', type: 'number' }, { key: 'minimum_order_value', label: 'Мин. сумма заказа', type: 'number' },
  ] },
]

const configFor = (dataset: EditorDataset) => DATASETS.find(item => item.key === dataset) || DATASETS[0]
const today = () => new Date().toISOString().slice(0, 10)

function defaultsFor(dataset: EditorDataset): Record<string, unknown> {
  const defaults: Record<string, unknown> = { active: true, date: today(), start_date: today(), end_date: today(), expected_arrival_date: today(), quantity: 0, price: 0, current_stock: 0, quantity_in_transit: 0, lead_time_days: 7, moq: 0, package_size: 1, unit_cost: 0, unit_price: 0, minimum_order_value: 0 }
  return Object.fromEntries(configFor(dataset).fields.map(field => [field.key, defaults[field.key] ?? '']))
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  return String(value).replace('T00:00:00.000Z', '')
}

export default function DataEditor({ onToast, onRefresh }: { onToast: (message: string) => void; onRefresh: () => void }) {
  const [dataset, setDataset] = useState<EditorDataset>('products')
  const [rows, setRows] = useState<EditorRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [form, setForm] = useState<Record<string, unknown>>(defaultsFor('products'))
  const [editingId, setEditingId] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  const [restored, setRestored] = useState(false)
  const [busy, setBusy] = useState(false)
  const [lookups, setLookups] = useState<Record<string, string[]>>({})
  const currentConfig = configFor(dataset)

  const loadRows = async () => {
    try {
      const response = await getEditorRows(dataset, page * 50, 50, search)
      setRows(response.rows)
      setTotal(response.total)
    } catch (error) {
      onToast(error instanceof Error ? error.message : 'Не удалось загрузить данные')
    }
  }

  useEffect(() => { loadRows() }, [dataset, page, search])

  useEffect(() => {
    Promise.all([getEditorState(), getEditorRows('products', 0, 500), getEditorRows('stock', 0, 500), getEditorRows('suppliers', 0, 500)]).then(([state, products, stock, suppliers]) => {
      if (state.draft) {
        setDataset(state.draft.dataset)
        setEditingId(state.draft.row_id)
        setForm({ ...defaultsFor(state.draft.dataset), ...state.draft.row })
        setRestored(true)
      }
      setLookups({
        sku: [...new Set(products.rows.map(row => String(row.sku || '')).filter(Boolean))],
        warehouse: [...new Set(stock.rows.map(row => String(row.warehouse || '')).filter(Boolean))],
        supplier_id: [...new Set(suppliers.rows.map(row => String(row.supplier_id || '')).filter(Boolean))],
      })
    }).catch(() => onToast('Черновик пока недоступен'))
  }, [])

  useEffect(() => {
    if (!dirty) return
    const timer = window.setTimeout(() => {
      saveEditorDraft(dataset, form, editingId).catch(() => undefined)
    }, 500)
    return () => window.clearTimeout(timer)
  }, [dataset, form, editingId, dirty])

  const visibleFields = useMemo(() => currentConfig.fields.slice(0, 6), [currentConfig])

  const selectDataset = (next: EditorDataset) => {
    setDataset(next); setPage(0); setSearch(''); setEditingId(null); setForm(defaultsFor(next)); setDirty(false); setRestored(false)
  }

  const startNew = () => { setEditingId(null); setForm(defaultsFor(dataset)); setDirty(false); setRestored(false) }
  const editRow = (row: EditorRow) => { const { row_id, ...values } = row; setEditingId(row_id); setForm({ ...defaultsFor(dataset), ...values }); setDirty(false); setRestored(false) }

  const changeField = (field: Field, value: string | boolean) => {
    const converted = field.type === 'number' ? (value === '' ? '' : Number(value)) : value
    setForm(current => ({ ...current, [field.key]: converted })); setDirty(true); setRestored(false)
  }

  const save = async () => {
    setBusy(true)
    try {
      const response = editingId === null ? await createEditorRow(dataset, form) : await updateEditorRow(dataset, editingId, form)
      await clearEditorDraft(); setDirty(false); setRestored(false); setEditingId(null); setForm(defaultsFor(dataset)); await loadRows(); onRefresh()
      onToast(response.warnings?.length ? response.warnings.join(' · ') : 'Изменения сохранены, рекомендации пересчитаны')
    } catch (error) { onToast(error instanceof Error ? error.message : 'Не удалось сохранить строку') } finally { setBusy(false) }
  }

  const remove = async (rowId: number) => {
    if (!window.confirm('Удалить эту строку?')) return
    setBusy(true)
    try { await deleteEditorRow(dataset, rowId); await loadRows(); onRefresh(); onToast('Строка удалена') } catch (error) { onToast(error instanceof Error ? error.message : 'Не удалось удалить строку') } finally { setBusy(false) }
  }

  return <section className="editor-page">
    <div className="page-intro editor-intro"><div><p className="eyebrow">ИСХОДНЫЕ ТАБЛИЦЫ</p><h2>Справочники и данные</h2><p>Точечное редактирование исходных таблиц. Операции с несколькими товарами оформляйте в разделах «Закуп», «Продажа» и «Движения товаров».</p></div><div className="editor-status">{restored ? '↩ Черновик восстановлен' : '● Данные сохраняются в SQLite'}</div></div>
    <div className="editor-tabs">{DATASETS.map(item => <button key={item.key} className={dataset === item.key ? 'editor-tab active' : 'editor-tab'} onClick={() => selectDataset(item.key)}><strong>{item.label}</strong><small>{item.description}</small></button>)}</div>
    <div className="editor-layout">
      <div className="content-card editor-table-card"><div className="card-header"><div><p className="eyebrow">{currentConfig.label.toUpperCase()}</p><h3>Записи <span>{total}</span></h3></div><div className="header-actions"><div className="search editor-search"><span>⌕</span><input value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder="Найти…" /></div><a className="button subtle" href={editorExportUrl(dataset, 'xlsx')}>↓ XLSX</a><a className="button subtle" href={editorExportUrl(dataset, 'csv')}>↓ CSV</a><button className="button primary" onClick={startNew}>＋ Новая строка</button></div></div><div className="table-wrap"><table className="editor-table"><thead><tr>{visibleFields.map(field => <th key={field.key}>{field.label}</th>)}<th>Действия</th></tr></thead><tbody>{rows.map(row => <tr key={row.row_id}>{visibleFields.map(field => <td key={field.key}>{displayValue(row[field.key])}</td>)}<td><button className="table-action" onClick={() => editRow(row)}>Изменить</button><button className="table-action danger" onClick={() => remove(row.row_id)}>Удалить</button></td></tr>)}</tbody></table>{!rows.length && <div className="empty">Пока нет записей. Создайте первую строку.</div>}</div><div className="editor-pagination"><span>{total ? `${page * 50 + 1}–${Math.min((page + 1) * 50, total)} из ${total}` : '0 записей'}</span><div><button className="button subtle" disabled={page === 0} onClick={() => setPage(value => value - 1)}>←</button><button className="button subtle" disabled={(page + 1) * 50 >= total} onClick={() => setPage(value => value + 1)}>→</button></div></div></div>
      <div className="content-card editor-form-card"><div className="card-header"><div><p className="eyebrow">{editingId === null ? 'NEW RECORD' : 'EDIT RECORD'}</p><h3>{editingId === null ? 'Добавить строку' : 'Изменить строку'}</h3></div>{editingId !== null && <button className="close editor-close" onClick={startNew}>×</button>}</div><div className="editor-form">{currentConfig.fields.map(field => <label key={field.key} className="editor-field"><span>{field.label}{field.required && ' *'}</span>{field.type === 'checkbox' ? <input type="checkbox" checked={Boolean(form[field.key])} onChange={event => changeField(field, event.target.checked)} /> : <input type={field.type || 'text'} value={String(form[field.key] ?? '')} list={lookups[field.key] ? `lookup-${field.key}` : undefined} onChange={event => changeField(field, event.target.value)} />}{lookups[field.key] && <datalist id={`lookup-${field.key}`}>{lookups[field.key].map(value => <option key={value} value={value} />)}</datalist>}</label>)}<button className="button primary wide" onClick={save} disabled={busy}>{busy ? 'Сохраняем…' : editingId === null ? 'Сохранить строку' : 'Сохранить изменения'}</button><small className="editor-hint">Последнее состояние формы автоматически сохраняется как черновик каждые несколько секунд.</small></div></div>
    </div>
  </section>
}
