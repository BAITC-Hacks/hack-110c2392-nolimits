import { translateText } from './i18n'
import { useState } from 'react'
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { adjustOrder, approveOrder } from './api'
import { prepareChartPoints, type ChartRange } from './chart'
import { useI18n } from './i18n'
import type { Point, Recommendation } from './types'
import { Badge, Modal, money, number, warehouseName } from './ui'

export default function ItemDetail({ row, points, loading, analyticsError, onClose, onChanged }: { row: Recommendation; points: Point[]; loading: boolean; analyticsError: string; onClose: () => void; onChanged: (row: Recommendation) => void }) {
  const { t } = useI18n()
  const [chartRange, setChartRange] = useState<ChartRange>('week')
  const [quantity, setQuantity] = useState(String(row.final_quantity))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const dirty = quantity !== String(row.final_quantity)
  const valid = quantity.trim() !== '' && Number.isFinite(Number(quantity)) && Number(quantity) >= 0
  const close = () => { if (!saving && (!dirty || window.confirm('Закрыть без сохранения количества?'))) onClose() }
  const change = async (approve: boolean) => {
    if (!valid || (approve && dirty)) return
    setSaving(true); setError('')
    try { const updated = approve ? await approveOrder(row.id) : await adjustOrder(row.id, Number(quantity)); setQuantity(String(updated.final_quantity)); onChanged(updated) }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить изменения') }
    finally { setSaving(false) }
  }
  const chart = prepareChartPoints(points, chartRange)
  return <Modal title={translateText("Карточка позиции")} className="item-drawer" onClose={close}>
    <div className="drawer-body">
      <section><div className="badge-row"><Badge value={row.urgency}/><Badge value={row.status}/></div><h2 className="product-title">{row.product_name}</h2><p>{row.sku} · {warehouseName(row.warehouse)}</p><p>{row.supplier_name} · поставка {row.lead_time_days} дн.</p></section>
      <section><h3>{translateText("Рекомендация")}</h3><dl className="detail-grid">{[['К заказу', `${number(row.recommended_quantity)} ед.`], ['Стоимость итогового заказа', money(row.total_cost_kzt)], ['Остаток', number(row.current_stock)], ['В пути', number(row.in_transit)], ['Прогноз за срок поставки', number(row.forecast_lead_time)], ['Страховой запас', number(row.safety_stock)]].map(([label, value]) => <div key={translateText(label)}><dt>{translateText(label)}</dt><dd>{value}</dd></div>)}</dl></section>
      <section><h3>{translateText("Расчёт количества")}</h3><dl className="calculation">{[['Прогноз спроса', number(row.forecast_lead_time)], ['+ Страховой запас', number(row.safety_stock)], ['− Остаток и товары в пути', number(row.inventory_position)], ['До округления', number(row.raw_recommended_quantity)], ['С учётом ограничений поставщика', number(row.recommended_quantity)]].map(([label, value]) => <div key={translateText(label)}><dt>{translateText(label)}</dt><dd>{value}</dd></div>)}</dl><p className="explanation">{row.explanation}</p></section>
      <section><h3>{translateText("График спроса")}</h3><div className="chart-range" aria-label={t('chartRange')}>{(['day', 'week', '3m', '9m'] as ChartRange[]).map(range => <button className="button subtle" aria-pressed={chartRange === range} key={range} onClick={() => setChartRange(range)}>{t(range === 'day' ? 'dayRange' : range === 'week' ? 'weekRange' : range === '3m' ? 'threeMonths' : 'nineMonths')}</button>)}</div>{loading ? <p role="status">{translateText("Загружаем аналитику…")}</p> : analyticsError ? <p role="alert" className="error">{analyticsError}</p> : !chart.length ? <p>{translateText("Для этой позиции нет истории.")}</p> : <><div className="chart"><ResponsiveContainer width="100%" height={220}><ComposedChart data={chart} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}><CartesianGrid stroke="#E2E6EA" vertical={false}/><XAxis dataKey="date" tick={{ fontSize: 12 }} tickFormatter={v => v.slice(5)} minTickGap={32}/><YAxis width={44} tick={{ fontSize: 12 }}/><Tooltip/><Line type="monotone" name="Продажи" dataKey="actual_sales" stroke="#89939F" dot={false} strokeWidth={1.5}/><Line type="monotone" name="Скорректированный спрос" dataKey="adjusted_demand" stroke="#2F6B4F" dot={false} strokeWidth={1.5}/><Line type="monotone" name="Прогноз" dataKey="forecast" stroke="#2F6B4F" strokeDasharray="5 4" dot={false}/><Scatter name="Дефицит" data={chart.filter(p => p.is_stockout)} dataKey="adjusted_demand" fill="#B7791F"/><Scatter name="Аномалия" data={chart.filter(p => p.is_outlier)} dataKey="actual_sales" fill="#C2413B"/></ComposedChart></ResponsiveContainer></div><div className="chart-legend"><span>{translateText("— Продажи")}</span><span className="green-text">{translateText("— Спрос · - - Прогноз")}</span><span className="danger-text">{translateText("● Аномалия")}</span><span>{translateText("● Дефицит")}</span></div></>}
        <dl className="detail-grid compact"><div><dt>{translateText("Средний спрос / день")}</dt><dd>{number(row.average_daily_demand)}</dd></div><div><dt>{translateText("Покрытие запасом")}</dt><dd>{number(row.days_of_cover)} дн.</dd></div><div><dt>{translateText("Тренд")}</dt><dd>{{ growing: 'Рост', stable: 'Стабильный', declining: 'Снижение' }[row.trend_direction]} · {number(row.trend_percent)}%</dd></div><div><dt>{translateText("Сезонность")}</dt><dd>{row.seasonality_detected ? 'Выявлена' : 'Не выявлена'}</dd></div><div><dt>{translateText("Исключено выбросов")}</dt><dd>{row.outliers_removed}</dd></div><div><dt>{translateText("Восстановленный спрос")}</dt><dd>{number(row.estimated_lost_demand)}</dd></div></dl>
      </section>
      <section><h3>{translateText("Количество к заказу")}</h3><label className="field">{translateText("Итоговое количество")}<input type="number" min="0" step="any" value={quantity} disabled={saving} onChange={e => setQuantity(e.target.value)}/></label>{!valid && <p className="error">{translateText("Введите число не меньше нуля.")}</p>}<p className="caption">{translateText("Количество указано в единицах исходных данных.")}</p><label className="field">{translateText("Причина изменения")}<textarea disabled placeholder={translateText("Сохранение комментариев пока не поддерживается")}/></label><p className="caption">{translateText("Текущий API сохраняет количество и статус, но не причину изменения.")}</p>{error && <p role="alert" className="error">{error}</p>}</section>
    </div>
    <div className="drawer-footer"><div><button className="button subtle" disabled={saving || !dirty || !valid} onClick={() => change(false)}>{translateText("Сохранить")}</button><button className="button primary" disabled={saving || dirty || !valid || row.status === 'APPROVED'} onClick={() => change(true)}>{saving ? 'Сохраняем…' : row.status === 'APPROVED' ? 'Утверждено' : 'Утвердить'}</button></div><small>{dirty ? 'Сохраните новое количество перед утверждением.' : 'Утверждение не отправляет заказ поставщику.'}</small></div>
  </Modal>
}
