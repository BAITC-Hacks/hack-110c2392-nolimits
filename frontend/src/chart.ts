import type { Point } from './types'
export type ChartRange = 'day' | 'week' | '3m' | '9m'

export function prepareChartPoints(points: Point[], range: ChartRange): Point[] {
  const history = points.filter(point => point.forecast === undefined)
  const forecast = points.filter(point => point.forecast !== undefined)
  if (!history.length) return forecast
  const latestDate = Date.parse(history[history.length - 1].date)
  const rangeDays = range === 'day' ? 1 : range === 'week' ? 7 : range === '9m' ? 270 : 90
  const bucketSize = range === 'day' || range === 'week' ? 1 : range === '9m' ? 14 : 7
  const cutoff = latestDate - (rangeDays - 1) * 24 * 60 * 60 * 1000
  const recent = history.filter(point => Date.parse(point.date) >= cutoff)
  if (bucketSize === 1) return [...recent, ...forecast]
  const compacted: Point[] = []
  for (let index = 0; index < recent.length; index += bucketSize) {
    const bucket = recent.slice(index, index + bucketSize)
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
