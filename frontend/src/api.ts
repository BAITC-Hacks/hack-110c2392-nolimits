import type { Point, Recommendation, Summary } from './types'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map(item => item.msg || String(item)).join(' · ')
      : detail && typeof detail === 'object' ? [detail.message, ...(Array.isArray(detail.errors) ? detail.errors : []), ...(Array.isArray(detail.warnings) ? detail.warnings : [])].filter(Boolean).join(' · ')
      : 'Request failed'
    throw new Error(message || 'Request failed')
  }
  return response.json()
}

export async function loadDemo() { return request<{ datasets: Record<string, number> }>('/api/data/demo', { method: 'POST' }) }
export async function loadEkt() { return request<{ message: string; datasets: Record<string, number>; recommendations: number }>('/api/data/load-ekt', { method: 'POST' }) }
export async function loadAnomalies() { return request<{ message: string; datasets: Record<string, number>; recommendations: number; outliers: number }>('/api/data/load-anomalies', { method: 'POST' }) }
export async function calculate() { return request<{ count: number; outliers: number; recommendations: Recommendation[] }>('/api/recommendations/calculate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }) }
export async function getRecommendations(params = '') { return request<{ recommendations: Recommendation[]; summary: Summary }>(`/api/recommendations${params}`) }
export async function getAnalytics(sku: string, warehouse: string) { return request<{ sku: string; warehouse: string; product_name: string; points: Point[]; recommendation: Recommendation | null; outliers: unknown[] }>(`/api/analytics/${encodeURIComponent(sku)}?warehouse=${encodeURIComponent(warehouse)}`) }
export async function getOutliers() { return request<{ outliers: unknown[]; count: number }>('/api/outliers') }
export async function adjustOrder(id: string, quantity: number) { return request<Recommendation>(`/api/orders/${encodeURIComponent(id)}/adjust`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ final_quantity: quantity }) }) }
export async function approveOrder(id: string) { return request<Recommendation>(`/api/orders/${encodeURIComponent(id)}/approve`, { method: 'POST' }) }
export function exportUrl(format: 'csv' | 'xlsx') { return `${API}/api/orders/export?format=${format}` }
export function editorExportUrl(dataset: EditorDataset, format: 'csv' | 'xlsx') { return `${API}/api/editor/${dataset}/export?format=${format}` }
export async function uploadFile(dataset: string, file: File) { const form = new FormData(); form.append('file', file); return request<{ rows_loaded: number; errors: string[]; warnings: string[]; recommendations: number; outliers: number }>(`/api/data/upload/${dataset}`, { method: 'POST', body: form }) }
export async function uploadWorkbook(file: File) { const form = new FormData(); form.append('file', file); return request<{ message: string; datasets: Record<string, number>; recommendations: number; errors: string[]; warnings: string[] }>('/api/data/upload-workbook', { method: 'POST', body: form }) }

export type EditorDataset = 'products' | 'sales' | 'stock' | 'transit' | 'stockouts' | 'suppliers'
export type EditorRow = Record<string, unknown> & { row_id: number }
export interface EditorDraft { dataset: EditorDataset; row: Record<string, unknown>; row_id: number | null }
export async function getEditorState() { return request<{ datasets: Record<EditorDataset, number>; draft: EditorDraft | null; updated_at: string | null }>('/api/editor/state') }
export async function getEditorRows(dataset: EditorDataset, offset = 0, limit = 50, search = '') { return request<{ dataset: EditorDataset; columns: string[]; rows: EditorRow[]; total: number; offset: number; limit: number; draft: EditorDraft | null }>(`/api/editor/${dataset}?offset=${offset}&limit=${limit}&search=${encodeURIComponent(search)}`) }
export async function createEditorRow(dataset: EditorDataset, row: Record<string, unknown>) { return request<{ rows: number; recommendations: number; outliers: number; warnings: string[] }>(`/api/editor/${dataset}/rows`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ row }) }) }
export async function updateEditorRow(dataset: EditorDataset, rowId: number, row: Record<string, unknown>) { return request<{ rows: number; recommendations: number; outliers: number; warnings: string[] }>(`/api/editor/${dataset}/rows/${rowId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ row }) }) }
export async function deleteEditorRow(dataset: EditorDataset, rowId: number) { return request<{ rows: number; recommendations: number; outliers: number; warnings: string[] }>(`/api/editor/${dataset}/rows/${rowId}`, { method: 'DELETE' }) }
export async function saveEditorDraft(dataset: EditorDataset, row: Record<string, unknown>, rowId: number | null) { return request<{ saved: boolean; draft: EditorDraft; updated_at: string | null }>('/api/editor/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dataset, row, row_id: rowId }) }) }
export async function clearEditorDraft() { return request<{ deleted: boolean }>('/api/editor/draft', { method: 'DELETE' }) }

export type MovementKind = 'PURCHASE' | 'RECEIPT' | 'SALE' | 'TRANSFER' | 'ADJUSTMENT' | 'RETURN'
export interface MovementLine { sku: string; product_name: string; category: string; quantity: number; unit_price: number; recommendation_id?: string }
export interface MovementInput { kind: MovementKind; date: string; warehouse: string; destination_warehouse?: string; partner: string; reference: string; expected_arrival_date?: string; client_request_id: string; lines: MovementLine[] }
export interface Movement extends MovementInput { id: string }
export interface CatalogProduct { sku: string; product_name: string; category: string; unit_price: number; active: boolean }
export interface StockRow { sku: string; product_name: string; category: string; warehouse: string; current_stock: number; in_transit: number; unit_price: number }
export async function getInventoryCatalog(search = '') { return request<{ products: CatalogProduct[]; total: number }>(`/api/inventory/catalog?search=${encodeURIComponent(search)}`) }
export async function getInventoryStock(search = '') { return request<{ rows: StockRow[]; total: number }>(`/api/inventory/stock?search=${encodeURIComponent(search)}`) }
export async function getInventoryMovements() { return request<{ movements: Movement[]; total: number }>('/api/inventory/movements?limit=200') }
export async function postInventoryMovement(input: MovementInput) { return request<{ movement: Movement; recommendations: number; replayed: boolean }>('/api/inventory/movements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) }) }
export function inventoryExportUrl() { return `${API}/api/inventory/export` }
