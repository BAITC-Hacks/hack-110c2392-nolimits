export type Urgency = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type Status = 'DRAFT' | 'ADJUSTED' | 'APPROVED'

export interface Recommendation {
  id: string; sku: string; product_name: string; warehouse: string; category: string
  supplier_id: string; supplier_name: string; current_stock: number; in_transit: number
  average_daily_demand: number; forecast_lead_time: number; safety_stock: number
  inventory_position: number; raw_recommended_quantity: number; recommended_quantity: number
  final_quantity: number; lead_time_days: number; days_of_cover: number; urgency: Urgency
  trend_direction: 'growing' | 'stable' | 'declining'; trend_percent: number
  seasonality_detected: boolean; outliers_removed: number; estimated_lost_demand: number
  status: Status; explanation: string; metadata: Record<string, unknown>
}

export interface Summary { skus_requiring_replenishment: number; critical_risks: number; total_recommended_units: number; suppliers_involved: number; detected_anomalies: number; estimated_lost_demand: number }
export interface Point { date: string; actual_sales: number | null; adjusted_demand: number | null; forecast?: number }
