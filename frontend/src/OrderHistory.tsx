import { translateText } from './i18n'
import { useEffect, useState } from 'react'
import { getOrderHistory, type ArchivedOrder } from './api'
import { Badge, number } from './ui'

export default function OrderHistory() {
  const [orders, setOrders] = useState<ArchivedOrder[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  useEffect(() => { let active = true; getOrderHistory().then(r => { if (active) setOrders(r.orders) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [])
  return <section className="content-card history-archive"><div className="card-header"><div><h2>{translateText("Архив заказов")}</h2><p>{translateText("Сохранённые версии заказов при изменении исходных данных.")}</p></div></div>{error && <p className="error" role="alert">{error}</p>}<div className="table-wrap"><table className="operations-table"><thead><tr><th>{translateText("Заказ")}</th><th>{translateText("Статус")}</th><th>{translateText("Количество")}</th><th>{translateText("Архивирован (UTC)")}</th></tr></thead><tbody>{orders.slice(page * 25, page * 25 + 25).map(order => <tr key={order.id}><td data-label={translateText("Заказ")}>{order.order_id}</td><td data-label={translateText("Статус")}><Badge value={order.status}/></td><td data-label={translateText("Количество")}>{number(order.final_quantity)}</td><td data-label={translateText("Архивирован (UTC)")}>{order.archived_at.replace('T', ' ').slice(0, 19)}</td></tr>)}</tbody></table></div>{!orders.length && <p className="empty">{loading ? 'Загружаем архив…' : error ? 'Архив недоступен.' : 'Архивных заказов пока нет.'}</p>}<div className="pagination"><span>{orders.length} записей</span><div><button className="button subtle" disabled={!page} onClick={() => setPage(p => p - 1)}>{translateText("Назад")}</button><button className="button subtle" disabled={(page + 1) * 25 >= orders.length} onClick={() => setPage(p => p + 1)}>{translateText("Далее")}</button></div></div></section>
}
