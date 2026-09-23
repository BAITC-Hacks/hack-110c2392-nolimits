import type { Point, Recommendation, Summary } from './types'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'Request failed') }
  return response.json()
}

export async function loadDemo() { return request<{ datasets: Record<string, number> }>('/api/data/demo', { method: 'POST' }) }
export async function loadEkt() { return request<{ message: string; datasets: Record<string, number>; recommendations: number }>('/api/data/load-ekt', { method: 'POST' }) }
export async function loadEktExtreme() { return request<{ message: string; datasets: Record<string, number>; recommendations: number; outliers: number }>('/api/data/load-ekt-extreme', { method: 'POST' }) }
export async function calculate() { return request<{ count: number; outliers: number; recommendations: Recommendation[] }>('/api/recommendations/calculate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }) }
export async function getRecommendations(params = '') { return request<{ recommendations: Recommendation[]; summary: Summary }>(`/api/recommendations${params}`) }
export async function getAnalytics(sku: string, warehouse: string) { return request<{ sku: string; warehouse: string; product_name: string; points: Point[]; recommendation: Recommendation | null; outliers: unknown[] }>(`/api/analytics/${encodeURIComponent(sku)}?warehouse=${encodeURIComponent(warehouse)}`) }
export async function getOutliers() { return request<{ outliers: unknown[]; count: number }>('/api/outliers') }
export async function adjustOrder(id: string, quantity: number) { return request<Recommendation>(`/api/orders/${encodeURIComponent(id)}/adjust`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ final_quantity: quantity }) }) }
export async function approveOrder(id: string) { return request<Recommendation>(`/api/orders/${encodeURIComponent(id)}/approve`, { method: 'POST' }) }
export function exportUrl(format: 'csv' | 'xlsx') { return `${API}/api/orders/export?format=${format}` }
export async function uploadFile(dataset: string, file: File) { const form = new FormData(); form.append('file', file); return request<{ rows_loaded: number; errors: string[]; warnings: string[]; recommendations: number; outliers: number }>(`/api/data/upload/${dataset}`, { method: 'POST', body: form }) }
export async function uploadWorkbook(file: File) { const form = new FormData(); form.append('file', file); return request<{ message: string; datasets: Record<string, number>; recommendations: number; errors: string[]; warnings: string[] }>('/api/data/upload-workbook', { method: 'POST', body: form }) }
