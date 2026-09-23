import type { Point } from './types'
export function compactChartPoints(points: Point[]): Point[] {
  const history = points.filter(point => point.forecast === undefined)
  const forecast = points.filter(point => point.forecast !== undefined)
  if (history.length <= 120) return points
  const latestDate = Date.parse(history[history.length - 1].date)
  const cutoff = latestDate - 90 * 24 * 60 * 60 * 1000
  const recent = history.filter(point => Date.parse(point.date) >= cutoff)
  const compacted: Point[] = []
  for (let index = 0; index < recent.length; index += 7) {
    const bucket = recent.slice(index, index + 7)
    const actual = bucket.map(point => point.actual_sales).filter((value): value is number => value !== null)
    const adjusted = bucket.map(point => point.adjusted_demand).filter((value): value is number => value !== null)
    compacted.push({
      date: bucket[0].date,
      actual_sales: actual.length ? actual.reduce((sum, value) => sum + value, 0) / actual.length : null,
      adjusted_demand: adjusted.length ? adjusted.reduce((sum, value) => sum + value, 0) / adjusted.length : null,
      is_outlier: bucket.some(point => point.is_outlier),
      is_stockout: bucket.some(point => point.is_stockout),
    })
  }
  return [...compacted, ...forecast]
}
