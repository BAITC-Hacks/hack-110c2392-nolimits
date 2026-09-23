import { translateText, formatNumber } from './i18n'
import { useEffect, useRef, type ReactNode } from 'react'
import type { Status, Urgency } from './types'

export const number = (value: number) => formatNumber(value)
export const money = (value?: number | null) => value == null ? 'Нет цены' : `${number(value)} ₸`
export const warehouseName = (value: string) => ({ 'WH-CENTRAL': 'Центральный склад', 'WH-NORTH': 'Северный склад', 'WH-SOUTH': 'Южный склад' }[value] || value)
export const riskLabels: Record<Urgency, string> = { CRITICAL: 'Критический', HIGH: 'Высокий', MEDIUM: 'Средний', LOW: 'Плановый' }
export const statusLabels: Record<Status, string> = { DRAFT: 'Черновик', ADJUSTED: 'Изменено', APPROVED: 'Утверждено' }
export function Badge({ value }: { value: Urgency | Status }) { return <span className={`badge ${value.toLowerCase()}`}>{translateText(value in riskLabels ? riskLabels[value as Urgency] : statusLabels[value as Status])}</span> }
export function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    plan: <><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 10v10"/></>,
    data: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/></>,
    alert: <><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/></>,
    history: <><path d="M3 11a9 9 0 1 1 3 8M3 4v7h7"/><path d="M12 7v6l4 2"/></>,
    settings: <><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
    panelHide: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16m8-11-3 3 3 3"/></>,
    panelShow: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16m5-11 3 3-3 3"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2"/></>,
    export: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/></>,
    search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  }
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.plan}</svg>
}
export function Modal({ title, children, onClose, className = '' }: { title: string; children: ReactNode; onClose: () => void; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.showModal()
    const before = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { ref.current?.close(); document.body.style.overflow = before; previous?.focus() }
  }, [])
  return <dialog ref={ref} className={`modal ${className}`} aria-label={translateText(title)} onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="modal-header"><h2>{translateText(title)}</h2><button className="icon-button" aria-label={translateText("Закрыть")} onClick={onClose}><Icon name="close"/></button></div>{children}
  </dialog>
}
