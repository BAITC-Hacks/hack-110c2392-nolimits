import { useState, type FormEvent } from 'react'
import { ApiError, uploadPartner, type PartnerImportResult, type PartnerReport } from './api'
import { translateText, useI18n } from './i18n'

const metricLabels: Record<string, string> = {
  brand: 'Производитель', source_dated_sales: 'Продажи с датой в источнике', imported_sales: 'Импортировано продаж',
  products: 'Товаров в каталоге', mapped_supplier_articles: 'Сопоставлено артикулов поставщика',
  stale_stock_rows: 'Устаревших остатков', missing_stock: 'Позиций без остатка', transit_rows: 'Строк в пути',
  transit_quantity: 'Количество в пути', lead_time_days: 'Заданный срок поставки, дней', as_of: 'Дата расчёта',
}

export default function PartnerImport({ disabled, onBusyChange, onRefresh }: { disabled: boolean; onBusyChange: (busy: boolean) => void; onRefresh: () => Promise<void> }) {
  const { formatNumber, formatDate } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [leadTime, setLeadTime] = useState('')
  const [asOf, setAsOf] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<PartnerImportResult | null>(null)
  const [report, setReport] = useState<PartnerReport | null>(null)
  const [error, setError] = useState('')
  const leadDays = Number(leadTime)
  const valid = !!file && acknowledged && leadTime.trim() !== '' && Number.isInteger(leadDays) && leadDays >= 1 && leadDays <= 365
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!valid || disabled || submitting || !file) return
    if (!file.name.toLowerCase().endsWith('.zip') || file.size > 25 * 1024 * 1024) { setError(translateText('Выберите ZIP-архив размером не более 25 МБ.')); return }
    setSubmitting(true); onBusyChange(true); setError(''); setResult(null); setReport(null)
    try {
      const response = await uploadPartner(file, leadDays, asOf)
      setResult(response); setReport(response.report); setAcknowledged(false)
      await onRefresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : translateText('Не удалось импортировать архив.'))
      if (caught instanceof ApiError && caught.detail && typeof caught.detail === 'object' && !Array.isArray(caught.detail)) {
        const detail = caught.detail as Partial<PartnerReport>
        if (Array.isArray(detail.errors) || Array.isArray(detail.warnings)) setReport({ ...detail, errors: detail.errors || [], warnings: detail.warnings || [] })
      }
    } finally { setSubmitting(false); onBusyChange(false) }
  }
  return <section className="partner-import" aria-labelledby="partner-import-title">
    <div><h3 id="partner-import-title">{translateText('Оригинальные архивы IEK / Systeme Electric')}</h3><p>{translateText('Загрузите ZIP поставщика целиком. Формат файлов определяется автоматически.')}</p></div>
    <form onSubmit={submit}>
      <fieldset disabled={disabled || submitting} className="operations-workspace partner-form">
        <label className="field">{translateText('ZIP-архив поставщика')}<input type="file" accept=".zip,application/zip" required onChange={event => { setFile(event.target.files?.[0] || null); setAcknowledged(false); setError(''); setReport(null); setResult(null) }}/></label>
        <label className="field">{translateText('Срок поставки, дней *')}<input type="number" inputMode="numeric" min="1" max="365" step="1" required value={leadTime} placeholder={translateText('Укажите согласованный срок')} onChange={event => setLeadTime(event.target.value)}/><small>{translateText('В архиве нет надёжного срока поставки. Укажите его явно: от 1 до 365 дней.')}</small></label>
        <label className="field">{translateText('Дата расчёта (необязательно)')}<input type="date" value={asOf} onChange={event => setAsOf(event.target.value)}/><small>{translateText('Если дата не задана, используется дата источника; она будет указана в отчёте.')}</small></label>
        <label className="partner-ack"><input type="checkbox" required checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)}/><span>{translateText('Подтверждаю замену текущего набора. Месячные остатки могут быть устаревшими: перед утверждением заказов я обновлю фактические остатки.')}</span></label>
        <button className="button primary" type="submit" disabled={!valid || disabled || submitting}>{translateText(submitting ? 'Импортируем архив…' : 'Импортировать ZIP')}</button>
      </fieldset>
    </form>
    {error && <div role="alert" className="error report">{error}</div>}
    {result && <p role="status" className="import-success">{translateText('Импорт завершён: {count} рекомендаций. Проверьте качество данных ниже.', { count: result.recommendations })}</p>}
    {report && <div className="partner-report">
      {!!report.metrics && <dl className="detail-grid">{Object.entries(metricLabels).filter(([key]) => report.metrics?.[key] !== undefined && report.metrics?.[key] !== null).map(([key, label]) => { const value = report.metrics![key]!; return <div key={key}><dt>{translateText(label)}</dt><dd>{typeof value === 'number' ? formatNumber(value) : key === 'as_of' && Number.isFinite(Date.parse(value)) ? formatDate(value) : value}</dd></div> })}</dl>}
      {!!report.errors.length && <details open><summary>{translateText('Ошибки импорта')} ({report.errors.length})</summary><ul>{report.errors.map((message, index) => <li key={index}>{message}</li>)}</ul></details>}
      {!!report.warnings.length && <details open><summary>{translateText('Предупреждения о качестве данных')} ({report.warnings.length})</summary><ul>{report.warnings.map((message, index) => <li key={index}>{message}</li>)}</ul></details>}
      {!!report.files?.length && <details><summary>{translateText('Обработанные файлы')} ({report.files.length})</summary><ul>{report.files.map((item, index) => <li key={index}><strong>{item.name}</strong><small>{item.kind} · {formatNumber(item.rows)} {translateText('строк')}</small></li>)}</ul></details>}
    </div>}
  </section>
}
