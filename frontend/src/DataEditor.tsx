import { translateText } from './i18n'
import { useEffect, useMemo, useState } from 'react'
import RawDataEditor from './RawDataEditor'
import { getInventoryCatalog, getInventoryMovements, getInventoryStock, inventoryExportUrl, postInventoryMovement, type CatalogProduct, type Movement, type MovementInput, type MovementKind, type MovementLine, type StockRow } from './api'
import type { Recommendation } from './types'
import { localDate, readMovementDraft, storeMovementDraft } from './editorState'

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
const newLine = (): MovementLine => ({ sku: '', product_name: '', category: '', quantity: 1, unit_price: 0 })
const fmt = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)
const fmtMoney = (value: number) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: Number.isInteger(value) ? 0 : 2, maximumFractionDigits: 2 }).format(value)
const parseUnitPrice = (value: string): number | null => {
  const normalized = value.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.')
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null
  const price = Number(normalized)
  return Number.isFinite(price) ? price : null
}

export default function DataEditor({ onToast, onRefresh, recommendations, initialReference = false }: { onToast: (message: string) => void; onRefresh: () => void; recommendations: Recommendation[]; initialReference?: boolean }) {
  const [draft] = useState(() => readMovementDraft<{ section: Section; movementTab: MovementKind | 'HISTORY'; date: string; warehouse: string; destination: string; partner: string; reference: string; arrival: string; entry: MovementLine; priceInput: string; lines: MovementLine[]; requestId: string }>())
  const [section, setSection] = useState<Section>(initialReference ? 'reference' : draft.section || 'purchase')
  const [movementTab, setMovementTab] = useState<MovementKind | 'HISTORY'>(draft.movementTab || 'RECEIPT')
  const [catalog, setCatalog] = useState<CatalogProduct[]>([])
  const [stock, setStock] = useState<StockRow[]>([])
  const [history, setHistory] = useState<Movement[]>([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [date, setDate] = useState(draft.date || localDate())
  const [warehouse, setWarehouse] = useState(draft.warehouse || '')
  const [destination, setDestination] = useState(draft.destination || '')
  const [partner, setPartner] = useState(draft.partner || '')
  const [reference, setReference] = useState(draft.reference || '')
  const [arrival, setArrival] = useState(draft.arrival || localDate())
  const [entry, setEntry] = useState<MovementLine>(draft.entry || newLine())
  const [priceInput, setPriceInput] = useState(draft.priceInput || '')
  const [lines, setLines] = useState<MovementLine[]>(draft.lines || [])
  const [requestId, setRequestId] = useState(() => draft.requestId || crypto.randomUUID())
  useEffect(() => { storeMovementDraft({ section, movementTab, date, warehouse, destination, partner, reference, arrival, entry, priceInput, lines, requestId }) }, [section, movementTab, date, warehouse, destination, partner, reference, arrival, entry, priceInput, lines, requestId])

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
    setPriceInput(product?.unit_price ? String(product.unit_price) : '')
  }
  const addLine = () => {
    if (!entry.sku.trim() || !entry.product_name.trim()) { onToast('Укажите артикул и название товара'); return }
    if (!Number.isFinite(entry.quantity) || entry.quantity === 0 || (entry.quantity < 0 && kind !== 'ADJUSTMENT')) { onToast('Проверьте количество'); return }
    const unitPrice = parseUnitPrice(priceInput)
    if (unitPrice === null) { onToast('Укажите корректную цену, например 1500 или 1500,50'); return }
    setLines(current => [...current, { ...entry, sku: entry.sku.trim(), product_name: entry.product_name.trim(), unit_price: unitPrice }])
    setEntry(newLine()); setPriceInput('')
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
      setLines([]); setEntry(newLine()); setPriceInput(''); setReference(''); setRequestId(crypto.randomUUID())
      await reload(); onRefresh()
      onToast(`${kindLabel[kind]} сохранён${kind === 'SALE' ? 'а' : ''}: ${result.movement.lines.length} позиций. Excel обновлён.`)
    } catch (error) { onToast(error instanceof Error ? error.message : 'Не удалось сохранить операцию') }
    finally { setBusy(false) }
  }

  return <section className="operations-page">
    <div className="page-intro operations-intro"><div><p className="eyebrow">{translateText("ТОВАРНЫЙ УЧЁТ")}</p><h2>{translateText("Управление товарами")}</h2><p>{translateText("Оформляйте несколько товаров как один документ. Остатки, товары в пути, история продаж и рекомендации обновятся автоматически.")}</p></div><a className="button primary" href={inventoryExportUrl()}>{translateText("↓ Скачать обновлённый Excel")}</a></div>
    <fieldset disabled={busy} className="operations-workspace"><nav className="operations-sections" aria-label={translateText('Разделы товарного учёта')}>{sections.map(item => <button key={item.key} type="button" title={translateText(item.help)} aria-current={section === item.key ? 'page' : undefined} className={section === item.key ? 'operations-section active' : 'operations-section'} onClick={() => { if (item.key !== section) { if (lines.length && !window.confirm('Несохранённые позиции документа будут очищены. Продолжить?')) return; setLines([]); setEntry(newLine()); setPriceInput(''); setPartner(''); setDestination(''); setRequestId(crypto.randomUUID()) }; setSection(item.key) }}>{translateText(item.label)}</button>)}</nav>

    {section === 'warehouse' && <div className="content-card"><div className="card-header"><div><p className="eyebrow">{translateText("СКЛАД / КАТАЛОГ")}</p><h3>{translateText("Все товары в истории проекта")}<span>{catalog.length}</span></h3></div><div className="search editor-search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} aria-label={translateText("Поиск по складу")} placeholder={translateText("Артикул, название, склад")} /></div></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>{translateText("Артикул")}</th><th>{translateText("Товар")}</th><th>{translateText("Категория")}</th><th>{translateText("Склад")}</th><th>{translateText("В наличии")}</th><th>{translateText("В пути")}</th></tr></thead><tbody>{visibleStock.map((row, index) => <tr key={`${row.sku}-${row.warehouse}-${index}`}><td data-label={translateText("Артикул")}><strong className="sku">{row.sku}</strong></td><td data-label={translateText("Товар")}>{row.product_name}</td><td data-label={translateText("Категория")}>{row.category}</td><td data-label={translateText("Склад")}>{row.warehouse || 'Пока не размещён'}</td><td data-label={translateText("В наличии")}><strong>{fmt(row.current_stock)}</strong></td><td data-label={translateText("В пути")}>{fmt(row.in_transit)}</td></tr>)}</tbody></table>{!visibleStock.length && <div className="empty">{translateText("Товары не найдены.")}</div>}</div></div>}

    {section === 'reference' && <RawDataEditor onToast={onToast} onRefresh={() => { reload(); onRefresh() }} />}

    {section === 'movements' && <div className="movement-subtabs">{movementKinds.map(item => <button key={item.key} aria-pressed={movementTab === item.key} className={movementTab === item.key ? 'active' : ''} onClick={() => { if (item.key === movementTab || busy) return; if (lines.length && !window.confirm('Несохранённые позиции документа будут очищены. Продолжить?')) return; setMovementTab(item.key); setLines([]); setEntry(newLine()); setPriceInput(''); setRequestId(crypto.randomUUID()) }}>{translateText(item.label)}</button>)}</div>}
    {section === 'movements' && movementTab === 'HISTORY' && <div className="content-card"><div className="card-header"><div><p className="eyebrow">{translateText("ЖУРНАЛ")}</p><h3>{translateText("Движения товаров")}<span>{history.length}</span></h3></div><a className="button subtle" href={inventoryExportUrl()}>↓ Excel</a></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>{translateText("Дата")}</th><th>{translateText("Тип")}</th><th>{translateText("Склад")}</th><th>{translateText("Контрагент / документ")}</th><th>{translateText("Позиции")}</th></tr></thead><tbody>{history.map(item => <tr key={item.id}><td data-label={translateText("Дата")}>{item.date}</td><td data-label={translateText("Тип")}><strong>{kindLabel[item.kind]}</strong></td><td data-label={translateText("Склад")}>{item.warehouse}{item.destination_warehouse ? ` → ${item.destination_warehouse}` : ''}</td><td data-label={translateText("Контрагент / документ")}>{item.partner || item.reference || '—'}</td><td data-label={translateText("Позиции")}>{item.lines.map(line => `${line.sku} × ${fmt(line.quantity)}`).join(', ')}</td></tr>)}</tbody></table>{!history.length && <div className="empty">{translateText("Операций пока нет.")}</div>}</div></div>}

    {(section === 'purchase' || section === 'sale' || (section === 'movements' && movementTab !== 'HISTORY')) && <div className="operations-layout">
      <div className="operations-main">
        <div className="content-card operations-card operations-document"><div className="card-header"><div><p className="eyebrow">{translateText("НОВЫЙ ДОКУМЕНТ")}</p><h3>{kindLabel[kind]}</h3></div><span className="editor-status">{lines.length} {translateText("поз.")}</span></div><div className="operations-fields">
          <label className="editor-field"><span>{translateText("Дата *")}</span><input type="date" value={date} onChange={event => setDate(event.target.value)} /></label>
          <label className="editor-field"><span>{kind === 'TRANSFER' ? 'Откуда *' : 'Склад *'}</span><input list="warehouses" value={warehouse} onChange={event => setWarehouse(event.target.value)} placeholder={translateText("Выберите склад")} /></label>
          {kind === 'TRANSFER' && <label className="editor-field"><span>{translateText("Куда *")}</span><input list="warehouses" value={destination} onChange={event => setDestination(event.target.value)} placeholder={translateText("Склад назначения")} /></label>}
          {(kind === 'PURCHASE' || kind === 'SALE' || kind === 'RETURN') && <label className="editor-field"><span>{kind === 'PURCHASE' ? 'Поставщик *' : 'Покупатель'}</span><input value={partner} onChange={event => setPartner(event.target.value)} placeholder={kind === 'PURCHASE' ? 'Название поставщика' : 'ID покупателя'} /></label>}
          {kind === 'PURCHASE' && <label className="editor-field"><span>{translateText("Ожидаемая дата *")}</span><input type="date" value={arrival} onChange={event => setArrival(event.target.value)} /></label>}
          <label className="editor-field"><span>{translateText("Номер документа / комментарий")}</span><input value={reference} onChange={event => setReference(event.target.value)} placeholder={translateText("Необязательно")} /></label>
          <datalist id="warehouses">{warehouses.map(value => <option key={value} value={value} />)}</datalist>
        </div></div>
        <div className="content-card operations-card operations-product"><div className="card-header"><div><p className="eyebrow">{translateText("СОСТАВ ДОКУМЕНТА")}</p><h3>{translateText("Добавить товар")}</h3></div></div><div className="operations-fields line-fields">
          <label className="editor-field"><span>{translateText("Артикул SKU *")}</span><input list="catalog-skus" value={entry.sku} onChange={event => selectSku(event.target.value)} placeholder={translateText("Найти или ввести новый")} /><datalist id="catalog-skus">{catalog.map(item => <option key={item.sku} value={item.sku}>{item.product_name}</option>)}</datalist></label>
          <label className="editor-field"><span>{translateText("Название *")}</span><input value={entry.product_name} onChange={event => setEntry(current => ({ ...current, product_name: event.target.value }))} /></label>
          <label className="editor-field"><span>{translateText("Категория")}</span><input value={entry.category} onChange={event => setEntry(current => ({ ...current, category: event.target.value }))} /></label>
          <label className="editor-field"><span>{translateText("Количество *")}</span><input type="number" step="any" value={entry.quantity} onChange={event => setEntry(current => ({ ...current, quantity: Number(event.target.value) }))} /></label>
          <label className="editor-field"><span>{translateText("Цена за единицу, ₸ *")}</span><input type="text" inputMode="decimal" value={priceInput} onChange={event => setPriceInput(event.target.value)} onBlur={() => { const price = parseUnitPrice(priceInput); if (price !== null) setPriceInput(fmtMoney(price)) }} placeholder={translateText("Введите цену")} /></label>
          <button className="button subtle add-line" onClick={addLine}>{translateText("＋ В документ")}</button>
        </div><p className="operations-hint">{kind === 'PURCHASE' ? 'Заказ увеличивает товары в пути; склад пополнится после поступления.' : kind === 'RECEIPT' ? 'Поступление списывает количество из «в пути» и добавляет его на склад.' : kind === 'SALE' ? 'Продажа уменьшает склад и попадает в историю спроса.' : kind === 'ADJUSTMENT' ? 'Укажите отрицательное количество для списания.' : 'Изменения появятся в складском учёте и журнале.'}</p></div>
        <div className="content-card operations-card operations-lines"><div className="card-header"><div><p className="eyebrow">{translateText("ДОКУМЕНТ")}</p><h3>{translateText("Позиции")}<span className="count">{lines.length}</span></h3></div><strong>{fmtMoney(total)} ₸</strong></div><div className="table-wrap"><table className="operations-table"><thead><tr><th>SKU</th><th>{translateText("Товар")}</th><th>{translateText("Кол-во")}</th><th>{translateText("Цена")}</th><th>{translateText("Сумма")}</th><th></th></tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td data-label="SKU">{line.sku}</td><td data-label={translateText("Товар")}>{line.product_name}</td><td data-label={translateText("Количество")}>{fmt(line.quantity)}</td><td data-label={translateText("Цена")}>{fmtMoney(line.unit_price)} ₸</td><td data-label={translateText("Сумма")}>{fmtMoney(line.quantity * line.unit_price)} ₸</td><td data-label={translateText("Действия")}><button className="table-action danger" onClick={() => setLines(current => current.filter((_, position) => position !== index))}>{translateText("Убрать")}</button></td></tr>)}</tbody></table>{!lines.length && <div className="empty">{translateText("Добавьте несколько товаров и сохраните их одной операцией.")}</div>}</div><div className="operations-submit"><span>{translateText("После сохранения можно сразу скачать обновлённый Excel.")}</span><button className="button primary" disabled={busy || !lines.length} onClick={submit}>{busy ? 'Сохраняем…' : `Провести ${kindLabel[kind].toLowerCase()}`}</button></div></div>
      </div>
      <aside className="operations-aside">{section === 'purchase' && <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">{translateText("ИЗ РЕКОМЕНДАЦИЙ")}</p><h3>{translateText("Утверждённые заказы")}<span>{approved.length}</span></h3></div></div><div className="recommendation-picker">{approved.slice(0, 80).map(row => <button key={row.id} onClick={() => addRecommendation(row)}><span><strong>{row.sku}</strong><small>{row.product_name}<br />{row.supplier_name} · {row.warehouse}</small></span><b>＋ {fmt(row.final_quantity)}</b></button>)}{!approved.length && <p>{translateText("Утвердите рекомендацию на главной странице или добавьте товар вручную.")}</p>}</div></div>}
        <div className="content-card operations-card"><div className="card-header"><div><p className="eyebrow">{translateText("ПОСЛЕДНИЕ ДЕЙСТВИЯ")}</p><h3>{translateText("Журнал")}</h3></div></div><div className="operations-recent">{history.slice(0, 6).map(item => <div key={item.id}><strong>{kindLabel[item.kind]}</strong><span>{item.date} · {item.lines.length} поз.</span></div>)}{!history.length && <p>{translateText("Пока нет операций.")}</p>}</div></div>
      </aside>
    </div>}
  </fieldset></section>
}
