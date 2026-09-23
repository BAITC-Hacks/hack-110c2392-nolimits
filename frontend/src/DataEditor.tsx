import { useEffect, useMemo, useState } from 'react'
import RawDataEditor from './RawDataEditor'
import { getInventoryCatalog, getInventoryMovements, getInventoryStock, inventoryExportUrl, postInventoryMovement, type CatalogProduct, type Movement, type MovementInput, type MovementKind, type MovementLine, type StockRow } from './api'
import type { Recommendation } from './types'

type Section = 'purchase' | 'sale' | 'movements' | 'warehouse' | 'reference'
const sections: Array<{ key: Section; label: string; help: string }> = [
  { key: 'purchase', label: 'Закуп', help: 'Заказы поставщикам' },
  { key: 'sale', label: 'Продажа', help: 'Отгрузка товаров' },
  { key: 'movements', label: 'Движения товаров', help: 'Приход, перемещение, возврат' },
  { key: 'warehouse', label: 'Склад', help: 'Все товары и остатки' },
  { key: 'reference', label: 'Справочники', help: 'Исходные таблицы' },
]
const movementKinds: Array<{ key: MovementKind | 'HISTORY'; label: string }> = [
  { key: 'RECEIPT', label: 'Поступление' }, { key: 'TRANSFER', label: 'Перемещение' },
  { key: 'ADJUSTMENT', label: 'Корректировка' }, { key: 'RETURN', label: 'Возврат' },
  { key: 'HISTORY', label: 'Журнал' },
]
const kindLabel: Record<MovementKind, string> = { PURCHASE: 'Закуп', RECEIPT: 'Поступление', SALE: 'Продажа', TRANSFER: 'Перемещение', ADJUSTMENT: 'Корректировка', RETURN: 'Возврат' }
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }
const newLine = (): MovementLine => ({ sku: '', product_name: '', category: '', quantity: 1, unit_price: 0 })
const fmt = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)

export default function DataEditor({ onToast, onRefresh, recommendations, initialReference = false }: { onToast: (message: string) => void; onRefresh: () => void; recommendations: Recommendation[]; initialReference?: boolean }) {
  const [section, setSection] = useState<Section>(initialReference ? 'reference' : 'purchase')
  const [movementTab, setMovementTab] = useState<MovementKind | 'HISTORY'>('RECEIPT')
  const [catalog, setCatalog] = useState<CatalogProduct[]>([])
  const [stock, setStock] = useState<StockRow[]>([])
  const [history, setHistory] = useState<Movement[]>([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [date, setDate] = useState(localDate())
  const [warehouse, setWarehouse] = useState('')
  const [destination, setDestination] = useState('')
  const [partner, setPartner] = useState('')
  const [reference, setReference] = useState('')
  const [arrival, setArrival] = useState(localDate())
  const [entry, setEntry] = useState<MovementLine>(newLine())
  const [lines, setLines] = useState<MovementLine[]>([])
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())

  const kind: MovementKind = section === 'purchase' ? 'PURCHASE' : section === 'sale' ? 'SALE' : movementTab === 'HISTORY' ? 'RECEIPT' : movementTab
  const warehouses = useMemo(() => [...new Set(stock.map(row => row.warehouse).filter(Boolean))].sort(), [stock])
  const approved = useMemo(() => recommendations.filter(row => row.status === 'APPROVED' && row.final_quantity > 0), [recommendations])
  const visibleStock = useMemo(() => stock.filter(row => `${row.sku} ${row.product_name} ${row.warehouse}`.toLowerCase().includes(search.toLowerCase())), [stock, search])
  const total = lines.reduce((sum, line) => sum + Math.abs(line.quantity) * line.unit_price, 0)

  const reload = async () => {
    try {
      const [products, balances, movements] = await Promise.all([getInventoryCatalog(), getInventoryStock(), getInventoryMovements()])
      setCatalog(products.products); setStock(balances.rows); setHistory(movements.movements)
    } catch (error) { onToast(error instanceof Error ? error.message : 'Не удалось загрузить операции') }
  }
  useEffect(() => { reload() }, [])

  const selectSku = (sku: string) => {
    const product = catalog.find(item => item.sku === sku)
    setEntry(current => ({ ...current, sku, product_name: product?.product_name || '',
      category: product?.category || '', unit_price: Number(product?.unit_price || 0) }))
  }
  const addLine = () => {
    if (!entry.sku.trim() || !entry.product_name.trim()) { onToast('Укажите артикул и название товара'); return }
    if (!Number.isFinite(entry.quantity) || entry.quantity === 0 || (entry.quantity < 0 && kind !== 'ADJUSTMENT')) { onToast('Проверьте количество'); return }
    if (!Number.isFinite(entry.unit_price) || entry.unit_price < 0) { onToast('Проверьте цену'); return }
    setLines(current => [...current, { ...entry, sku: entry.sku.trim(), product_name: entry.product_name.trim() }])
    setEntry(newLine())
  }
  const addRecommendation = (row: Recommendation) => {
    if (lines.some(line => line.recommendation_id === row.id)) { onToast('Эта рекомендация уже добавлена'); return }
    if (lines.length && (warehouse !== row.warehouse || partner !== row.supplier_name)) { onToast('В одном заказе должен быть один поставщик и склад'); return }
    setWarehouse(row.warehouse); setPartner(row.supplier_name)
    setLines(current => [...current, { sku: row.sku, product_name: row.product_name,
      category: row.category, quantity: row.final_quantity, unit_price: row.unit_cost || 0,
      recommendation_id: row.id }])
  }
  const submit = async () => {
    if (!lines.length) { onToast('Добавьте товары в операцию'); return }
    const input: MovementInput = { kind, date, warehouse: warehouse.trim(), destination_warehouse: destination.trim() || undefined,
      partner: partner.trim(), reference: reference.trim(), expected_arrival_date: kind === 'PURCHASE' ? arrival : undefined,
      client_request_id: requestId, lines }
    setBusy(true)
    try {
      const result = await postInventoryMovement(input)
      setLines([]); setEntry(newLine()); setReference(''); setRequestId(crypto.randomUUID())
      await reload(); onRefresh()
      onToast(`${kindLabel[kind]} сохранён${kind === 'SALE' ? 'а' : ''}: ${result.movement.lines.length} позиций. Excel обновлён.`)
    } catch (error) { onToast(error instanceof Error ? error.message : 'Не удалось сохранить операцию') }
    finally { setBusy(false) }
  }

  return <section className="operations-page">
    <div className="page-intro operations-intro"><div><p className="eyebrow">ТОВАРНЫЙ УЧЁТ</p><h2>Управление товарами</h2><p>Оформляйте несколько товаров как один документ. Остатки, товары в пути, история продаж и рекомендации обновятся автоматически.</p></div><a className="button primary" href={inventoryExportUrl()}>↓ Скачать обновлённый Excel</a></div>
    <div className="operations-sections">{sections.map(item => <button key={item.key} aria-pressed={section === item.key} className={section === item.key ? 'operations-section active' : 'operations-section'} onClick={() => { if (item.key !== section) { if (lines.length && !window.confirm('Несохранённые позиции документа будут очищены. Продолжить?')) return; setLines([]); setEntry(newLine()); setPartner(''); setDestination(''); setRequestId(crypto.randomUUID()) }; setSection(item.key) }}><strong>{item.label}</strong><small>{item.help}</small></button>)}</div>

    {section === 'warehouse' && <div className="content-card"><div className="card-header"><div><p className="eyebrow">СКЛАД / КАТАЛОГ</p><h3>Все товары в истории проекта <span>{catalog.length}</span></h3></div><div className="search editor-search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} aria-label="Поиск по складу" placeholder="Артикул, название, склад" /></div></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>Артикул</th><th>Товар</th><th>Категория</th><th>Склад</th><th>В наличии</th><th>В пути</th></tr></thead><tbody>{visibleStock.map((row, index) => <tr key={`${row.sku}-${row.warehouse}-${index}`}><td data-label="Артикул"><strong className="sku">{row.sku}</strong></td><td data-label="Товар">{row.product_name}</td><td data-label="Категория">{row.category}</td><td data-label="Склад">{row.warehouse || 'Пока не размещён'}</td><td data-label="В наличии"><strong>{fmt(row.current_stock)}</strong></td><td data-label="В пути">{fmt(row.in_transit)}</td></tr>)}</tbody></table>{!visibleStock.length && <div className="empty">Товары не найдены.</div>}</div></div>}

    {section === 'reference' && <RawDataEditor onToast={onToast} onRefresh={() => { reload(); onRefresh() }} />}

    {section === 'movements' && <div className="movement-subtabs">{movementKinds.map(item => <button key={item.key} aria-pressed={movementTab === item.key} className={movementTab === item.key ? 'active' : ''} onClick={() => { if (item.key !== movementTab && lines.length && !window.confirm('Несохранённые позиции документа будут очищены. Продолжить?')) return; setMovementTab(item.key); setLines([]); setRequestId(crypto.randomUUID()) }}>{item.label}</button>)}</div>}
    {section === 'movements' && movementTab === 'HISTORY' && <div className="content-card"><div className="card-header"><div><p className="eyebrow">ЖУРНАЛ</p><h3>Движения товаров <span>{history.length}</span></h3></div><a className="button subtle" href={inventoryExportUrl()}>↓ Excel</a></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>Дата</th><th>Тип</th><th>Склад</th><th>Контрагент / документ</th><th>Позиции</th></tr></thead><tbody>{history.map(item => <tr key={item.id}><td data-label="Дата">{item.date}</td><td data-label="Тип"><strong>{kindLabel[item.kind]}</strong></td><td data-label="Склад">{item.warehouse}{item.destination_warehouse ? ` → ${item.destination_warehouse}` : ''}</td><td data-label="Контрагент / документ">{item.partner || item.reference || '—'}</td><td data-label="Позиции">{item.lines.map(line => `${line.sku} × ${fmt(line.quantity)}`).join(', ')}</td></tr>)}</tbody></table>{!history.length && <div className="empty">Операций пока нет.</div>}</div></div>}

    {(section === 'purchase' || section === 'sale' || (section === 'movements' && movementTab !== 'HISTORY')) && <div className="operations-layout">
      <div className="operations-main">
        <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">НОВЫЙ ДОКУМЕНТ</p><h3>{kindLabel[kind]}</h3></div><span className="editor-status">{lines.length} позиций</span></div><div className="operations-fields">
          <label className="editor-field"><span>Дата *</span><input type="date" value={date} onChange={event => setDate(event.target.value)} /></label>
          <label className="editor-field"><span>{kind === 'TRANSFER' ? 'Откуда *' : 'Склад *'}</span><input list="warehouses" value={warehouse} onChange={event => setWarehouse(event.target.value)} placeholder="Выберите склад" /></label>
          {kind === 'TRANSFER' && <label className="editor-field"><span>Куда *</span><input list="warehouses" value={destination} onChange={event => setDestination(event.target.value)} placeholder="Склад назначения" /></label>}
          {(kind === 'PURCHASE' || kind === 'SALE' || kind === 'RETURN') && <label className="editor-field"><span>{kind === 'PURCHASE' ? 'Поставщик *' : 'Покупатель'}</span><input value={partner} onChange={event => setPartner(event.target.value)} placeholder={kind === 'PURCHASE' ? 'Название поставщика' : 'ID покупателя'} /></label>}
          {kind === 'PURCHASE' && <label className="editor-field"><span>Ожидаемая дата *</span><input type="date" value={arrival} onChange={event => setArrival(event.target.value)} /></label>}
          <label className="editor-field"><span>Номер документа / комментарий</span><input value={reference} onChange={event => setReference(event.target.value)} placeholder="Необязательно" /></label>
          <datalist id="warehouses">{warehouses.map(value => <option key={value} value={value} />)}</datalist>
        </div></div>
        <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">СОСТАВ ДОКУМЕНТА</p><h3>Добавить товар</h3></div></div><div className="operations-fields line-fields">
          <label className="editor-field"><span>Артикул SKU *</span><input list="catalog-skus" value={entry.sku} onChange={event => selectSku(event.target.value)} placeholder="Найти или ввести новый" /><datalist id="catalog-skus">{catalog.map(item => <option key={item.sku} value={item.sku}>{item.product_name}</option>)}</datalist></label>
          <label className="editor-field"><span>Название *</span><input value={entry.product_name} onChange={event => setEntry(current => ({ ...current, product_name: event.target.value }))} /></label>
          <label className="editor-field"><span>Категория</span><input value={entry.category} onChange={event => setEntry(current => ({ ...current, category: event.target.value }))} /></label>
          <label className="editor-field"><span>Количество *</span><input type="number" step="any" value={entry.quantity} onChange={event => setEntry(current => ({ ...current, quantity: Number(event.target.value) }))} /></label>
          <label className="editor-field"><span>Цена за единицу, ₸</span><input type="number" min="0" step="any" value={entry.unit_price} onChange={event => setEntry(current => ({ ...current, unit_price: Number(event.target.value) }))} /></label>
          <button className="button subtle add-line" onClick={addLine}>＋ В документ</button>
        </div><p className="operations-hint">{kind === 'PURCHASE' ? 'Заказ увеличивает товары в пути; склад пополнится после поступления.' : kind === 'RECEIPT' ? 'Поступление списывает количество из «в пути» и добавляет его на склад.' : kind === 'SALE' ? 'Продажа уменьшает склад и попадает в историю спроса.' : kind === 'ADJUSTMENT' ? 'Укажите отрицательное количество для списания.' : 'Изменения появятся в складском учёте и журнале.'}</p></div>
        <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">ДОКУМЕНТ</p><h3>Позиции <span>{lines.length}</span></h3></div><strong>{fmt(total)} ₸</strong></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>SKU</th><th>Товар</th><th>Кол-во</th><th>Цена</th><th>Сумма</th><th></th></tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td data-label="SKU">{line.sku}</td><td data-label="Товар">{line.product_name}</td><td data-label="Количество">{fmt(line.quantity)}</td><td data-label="Цена">{fmt(line.unit_price)} ₸</td><td data-label="Сумма">{fmt(line.quantity * line.unit_price)} ₸</td><td data-label="Действия"><button className="table-action danger" onClick={() => setLines(current => current.filter((_, position) => position !== index))}>Убрать</button></td></tr>)}</tbody></table>{!lines.length && <div className="empty">Добавьте несколько товаров и сохраните их одной операцией.</div>}</div><div className="operations-submit"><span>После сохранения можно сразу скачать обновлённый Excel.</span><button className="button primary" disabled={busy || !lines.length} onClick={submit}>{busy ? 'Сохраняем…' : `Провести ${kindLabel[kind].toLowerCase()}`}</button></div></div>
      </div>
      <aside className="operations-aside">{section === 'purchase' && <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">ИЗ РЕКОМЕНДАЦИЙ</p><h3>Утверждённые заказы <span>{approved.length}</span></h3></div></div><div className="recommendation-picker">{approved.slice(0, 80).map(row => <button key={row.id} onClick={() => addRecommendation(row)}><span><strong>{row.sku}</strong><small>{row.product_name}<br />{row.supplier_name} · {row.warehouse}</small></span><b>＋ {fmt(row.final_quantity)}</b></button>)}{!approved.length && <p>Утвердите рекомендацию на главной странице или добавьте товар вручную.</p>}</div></div>}
        <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">ПОСЛЕДНИЕ ДЕЙСТВИЯ</p><h3>Журнал</h3></div></div><div className="operations-recent">{history.slice(0, 6).map(item => <div key={item.id}><strong>{kindLabel[item.kind]}</strong><span>{item.date} · {item.lines.length} поз.</span></div>)}{!history.length && <p>Пока нет операций.</p>}</div></div>
      </aside>
    </div>}
  </section>
}
