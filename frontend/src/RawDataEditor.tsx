import { useEffect, useMemo, useRef, useState } from 'react'
import { localDate } from './editorState'
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
import { useI18n } from './i18n'

type FieldType = 'text' | 'number' | 'date' | 'checkbox'
type Field = { key: string; labelKey: string; type?: FieldType; required?: boolean }

const DATASETS: Array<{ key: EditorDataset; label: string; description: string; fields: Field[] }> = [
  { key: 'products', label: 'products', description: 'productsDescription', fields: [
    { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'product_name', labelKey: 'productName', required: true }, { key: 'category', labelKey: 'category', required: true }, { key: 'unit_price', labelKey: 'price', type: 'number' }, { key: 'active', labelKey: 'active', type: 'checkbox' },
  ] },
  { key: 'sales', label: 'sales', description: 'salesDescription', fields: [
    { key: 'date', labelKey: 'date', type: 'date', required: true }, { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'product_name', labelKey: 'productName', required: true }, { key: 'quantity', labelKey: 'quantity', type: 'number', required: true }, { key: 'price', labelKey: 'price', type: 'number', required: true }, { key: 'customer_id', labelKey: 'customerId', required: true }, { key: 'warehouse', labelKey: 'warehouse', required: true }, { key: 'category', labelKey: 'category', required: true },
  ] },
  { key: 'stock', label: 'stock', description: 'stockDescription', fields: [
    { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'warehouse', labelKey: 'warehouse', required: true }, { key: 'current_stock', labelKey: 'currentStock', type: 'number', required: true },
  ] },
  { key: 'transit', label: 'transit', description: 'transitDescription', fields: [
    { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'warehouse', labelKey: 'warehouse', required: true }, { key: 'quantity_in_transit', labelKey: 'quantity', type: 'number', required: true }, { key: 'expected_arrival_date', labelKey: 'arrivalDate', type: 'date', required: true },
  ] },
  { key: 'stockouts', label: 'stockouts', description: 'stockoutsDescription', fields: [
    { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'warehouse', labelKey: 'warehouse', required: true }, { key: 'start_date', labelKey: 'start', type: 'date', required: true }, { key: 'end_date', labelKey: 'end', type: 'date', required: true },
  ] },
  { key: 'suppliers', label: 'suppliers', description: 'suppliersDescription', fields: [
    { key: 'supplier_id', labelKey: 'supplierId', required: true }, { key: 'supplier_name', labelKey: 'supplierName', required: true }, { key: 'sku', labelKey: 'skuProduct', required: true }, { key: 'lead_time_days', labelKey: 'leadTimeDays', type: 'number', required: true }, { key: 'moq', labelKey: 'moq', type: 'number' }, { key: 'package_size', labelKey: 'packageSize', type: 'number' }, { key: 'unit_cost', labelKey: 'purchasePrice', type: 'number' }, { key: 'minimum_order_value', labelKey: 'minimumOrderValue', type: 'number' },
  ] },
]

const configFor = (dataset: EditorDataset) => DATASETS.find(item => item.key === dataset) || DATASETS[0]
const today = localDate

function defaultsFor(dataset: EditorDataset): Record<string, unknown> {
  const defaults: Record<string, unknown> = { active: true, date: today(), start_date: today(), end_date: today(), expected_arrival_date: today(), quantity: 0, price: 0, current_stock: 0, quantity_in_transit: 0, lead_time_days: 7, moq: 0, package_size: 1, unit_cost: 0, unit_price: 0, minimum_order_value: 0 }
  return Object.fromEntries(configFor(dataset).fields.map(field => [field.key, defaults[field.key] ?? '']))
}

function displayValue(value: unknown, yes: string, no: string): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? yes : no
  return String(value).replace('T00:00:00.000Z', '')
}

export default function RawDataEditor({ onToast, onRefresh }: { onToast: (message: string) => void; onRefresh: () => void }) {
  const { t } = useI18n()
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
  const requestVersion = useRef(0)
  const activeQuery = useRef('')
  activeQuery.current = `${dataset}|${page}|${search}`
  const interacted = useRef(false)

  const loadRows = async () => {
    const version = ++requestVersion.current
    const query = `${dataset}|${page}|${search}`
    try {
      const response = await getEditorRows(dataset, page * 50, 50, search)
      if (version !== requestVersion.current || query !== activeQuery.current) return
      setRows(response.rows)
      setTotal(response.total)
    } catch (error) {
      if (version === requestVersion.current && query === activeQuery.current) onToast(error instanceof Error ? error.message : t('couldNotLoad'))
    }
  }

  useEffect(() => { setRows([]); void loadRows(); return () => { requestVersion.current++ } }, [dataset, page, search])

  useEffect(() => {
    Promise.all([getEditorState(), getEditorRows('products', 0, 500), getEditorRows('stock', 0, 500), getEditorRows('suppliers', 0, 500)]).then(([state, products, stock, suppliers]) => {
      if (state.draft && !interacted.current) {
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
    }).catch(() => onToast(t('draftUnavailable')))
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
    if (next === dataset || busy) return
    if (dirty && !window.confirm(t('discardChanges'))) return
    interacted.current = true
    setDataset(next); setPage(0); setSearch(''); setEditingId(null); setForm(defaultsFor(next)); setDirty(false); setRestored(false)
  }

  const startNew = () => { if (dirty && !window.confirm(t('discardChanges'))) return; interacted.current = true; setEditingId(null); setForm(defaultsFor(dataset)); setDirty(false); setRestored(false) }
  const editRow = (row: EditorRow) => { if (dirty && !window.confirm(t('discardChanges'))) return; interacted.current = true; const { row_id, ...values } = row; setEditingId(row_id); setForm({ ...defaultsFor(dataset), ...values }); setDirty(false); setRestored(false) }

  const changeField = (field: Field, value: string | boolean) => {
    interacted.current = true
    const converted = field.type === 'number' ? (value === '' ? '' : Number(value)) : value
    setForm(current => ({ ...current, [field.key]: converted })); setDirty(true); setRestored(false)
  }

  const save = async () => {
    setBusy(true)
    try {
      const response = editingId === null ? await createEditorRow(dataset, form) : await updateEditorRow(dataset, editingId, form)
      await clearEditorDraft(); setDirty(false); setRestored(false); setEditingId(null); setForm(defaultsFor(dataset)); await loadRows(); onRefresh()
      onToast(response.warnings?.length ? response.warnings.join(' · ') : t('changesSaved'))
    } catch (error) { onToast(error instanceof Error ? error.message : t('couldNotSave')) } finally { setBusy(false) }
  }

  const remove = async (rowId: number) => {
    if (!window.confirm(t('confirmDelete'))) return
    setBusy(true)
    try { await deleteEditorRow(dataset, rowId); setEditingId(null); setForm(defaultsFor(dataset)); setDirty(false); setRestored(false); await loadRows(); onRefresh(); onToast(t('rowDeleted')) } catch (error) { onToast(error instanceof Error ? error.message : t('couldNotDelete')) } finally { setBusy(false) }
  }

  return <section className="editor-page">
    <div className="page-intro editor-intro"><div><p className="eyebrow">{t('dataWorkspace')}</p><h2>{t('dataEditorTitle')}</h2><p>{t('dataEditorDescription')}</p></div><div className="editor-status">{restored ? t('draftRestored') : t('savedToSqlite')}</div></div>
    <fieldset disabled={busy} className="operations-workspace"><div className="editor-tabs">{DATASETS.map(item => <button key={item.key} className={dataset === item.key ? 'editor-tab active' : 'editor-tab'} onClick={() => selectDataset(item.key)}><strong>{t(item.label)}</strong><small>{t(item.description)}</small></button>)}</div>
    <div className="editor-layout">
      <div className="content-card editor-table-card"><div className="card-header"><div><p className="eyebrow">{t(currentConfig.label).toUpperCase()}</p><h3>{t('records')} <span>{total}</span></h3></div><div className="header-actions"><div className="search editor-search"><span>⌕</span><input value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder={t('find')} /></div><a className="button subtle" href={editorExportUrl(dataset, 'xlsx')}>XLSX</a><a className="button subtle" href={editorExportUrl(dataset, 'csv')}>CSV</a><button className="button primary" onClick={startNew}>{t('newRow')}</button></div></div><div className="table-wrap"><table className="editor-table"><thead><tr>{visibleFields.map(field => <th key={field.key}>{t(field.labelKey)}</th>)}<th>{t('actions')}</th></tr></thead><tbody>{rows.map(row => <tr key={row.row_id}>{visibleFields.map(field => <td key={field.key} data-label={t(field.labelKey)}>{displayValue(row[field.key], t('yes'), t('no'))}</td>)}<td data-label={t('actions')}><button className="table-action" onClick={() => editRow(row)}>{t('edit')}</button><button className="table-action danger" onClick={() => remove(row.row_id)}>{t('delete')}</button></td></tr>)}</tbody></table>{!rows.length && <div className="empty">{t('noRecords')}</div>}</div><div className="editor-pagination"><span>{total ? t('recordsCount', { from: page * 50 + 1, to: Math.min((page + 1) * 50, total), total }) : t('zeroRecords')}</span><div><button className="button subtle" disabled={page === 0} onClick={() => setPage(value => value - 1)}>←</button><button className="button subtle" disabled={(page + 1) * 50 >= total} onClick={() => setPage(value => value + 1)}>→</button></div></div></div>
      <div className="content-card editor-form-card"><div className="card-header"><div><p className="eyebrow">{editingId === null ? t('newRecord') : t('editRecord')}</p><h3>{editingId === null ? t('addRow') : t('editRow')}</h3></div>{editingId !== null && <button className="close editor-close" onClick={startNew}>×</button>}</div><div className="editor-form">{currentConfig.fields.map(field => <label key={field.key} className="editor-field"><span>{t(field.labelKey)}{field.required && ' *'}</span>{field.type === 'checkbox' ? <input type="checkbox" checked={Boolean(form[field.key])} onChange={event => changeField(field, event.target.checked)} /> : <input type={field.type || 'text'} value={String(form[field.key] ?? '')} list={lookups[field.key] ? `lookup-${field.key}` : undefined} onChange={event => changeField(field, event.target.value)} />}{lookups[field.key] && <datalist id={`lookup-${field.key}`}>{lookups[field.key].map(value => <option key={value} value={value} />)}</datalist>}</label>)}<button className="button primary wide" onClick={save} disabled={busy}>{busy ? t('saving') : editingId === null ? t('saveRow') : t('saveChanges')}</button><small className="editor-hint">{t('editorHint')}</small></div></div>
    </div>
  </fieldset></section>
}
