from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import forecast_series, mad_outliers


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate_recommendations(data: dict[str, pd.DataFrame], warehouse: str | None = None, category: str | None = None, safety_days: int = 7, service_factor: float = 1.65, outlier_threshold: float = 3.5) -> tuple[list[dict], list[dict]]:
    sales = data['sales'].copy()
    if sales.empty:
        return [], []
    sales['date'] = pd.to_datetime(sales['date'])
    sales['quantity'] = pd.to_numeric(sales['quantity'], errors='coerce').fillna(0).clip(lower=0)
    if warehouse:
        sales = sales[sales['warehouse'] == warehouse]
    if category:
        sales = sales[sales['category'] == category]
    sales['is_outlier'] = False
    sales['outlier_reason'] = ''
    for _, group_index in sales.groupby(['sku', 'warehouse']).groups.items():
        mask = mad_outliers(sales.loc[group_index, 'quantity'], outlier_threshold)
        sales.loc[group_index[mask.to_numpy()], 'is_outlier'] = True
        sales.loc[group_index[mask.to_numpy()], 'outlier_reason'] = 'Robust MAD score above threshold; possible one-off order'
    sales['adjusted_quantity'] = np.where(sales['is_outlier'], sales['quantity'].groupby([sales['sku'], sales['warehouse']]).transform('median'), sales['quantity'])
    outliers = sales[sales['is_outlier']].copy()
    outlier_rows = [{
        'date': row.date.strftime('%Y-%m-%d'), 'sku': row.sku, 'warehouse': row.warehouse, 'customer_id': row.customer_id,
        'quantity': round(_number(row.quantity), 1), 'typical_quantity': round(_number(row.adjusted_quantity), 1),
        'reason': row.outlier_reason, 'used_in_forecast': False,
    } for row in outliers.itertuples()]
    stockouts = data.get('stockouts', pd.DataFrame()).copy()
    stockouts['start_date'] = pd.to_datetime(stockouts.get('start_date', pd.Series(dtype='datetime64[ns]')), errors='coerce')
    stockouts['end_date'] = pd.to_datetime(stockouts.get('end_date', pd.Series(dtype='datetime64[ns]')), errors='coerce')
    stockout_lookup: dict[tuple[str, str], list[tuple[pd.Timestamp, pd.Timestamp]]] = defaultdict(list)
    for row in stockouts.itertuples():
        stockout_lookup[(row.sku, row.warehouse)].append((row.start_date, row.end_date))

    daily = sales.groupby(['sku', 'warehouse', 'date'], as_index=False).agg(
        actual_sales=('quantity', 'sum'), adjusted_demand=('adjusted_quantity', 'sum'), product_name=('product_name', 'first'), category=('category', 'first'))
    # Transaction exports often omit days with zero sales. Expand each series to
    # a complete calendar wherever a stockout interval is declared, otherwise a
    # stockout with no transactions would never receive lost-demand correction.
    expanded_groups: list[pd.DataFrame] = []
    for (sku, wh), group in daily.groupby(['sku', 'warehouse'], sort=False):
        intervals = [(start, end) for start, end in stockout_lookup.get((sku, wh), []) if not pd.isna(start) and not pd.isna(end)]
        start_dates = [group['date'].min(), *[start for start, _ in intervals]]
        end_dates = [group['date'].max(), *[end for _, end in intervals]]
        calendar = pd.DataFrame({'date': pd.date_range(min(start_dates), max(end_dates), freq='D')})
        expanded = calendar.merge(group.drop(columns=['sku', 'warehouse']), on='date', how='left')
        expanded['sku'] = sku
        expanded['warehouse'] = wh
        expanded['actual_sales'] = expanded['actual_sales'].fillna(0.0)
        expanded['adjusted_demand'] = expanded['adjusted_demand'].fillna(0.0)
        expanded['product_name'] = expanded['product_name'].fillna(group['product_name'].iloc[0])
        expanded['category'] = expanded['category'].fillna(group['category'].iloc[0])
        expanded_groups.append(expanded)
    daily = pd.concat(expanded_groups, ignore_index=True)
    daily['estimated_lost_demand'] = 0.0
    daily['is_stockout'] = False
    for (sku, wh), indices in daily.groupby(['sku', 'warehouse']).groups.items():
        idx = list(indices)
        series = daily.loc[idx].sort_values('date')
        for start, end in stockout_lookup.get((sku, wh), []):
            if pd.isna(start) or pd.isna(end):
                continue
            comparable = series[(series['date'] < start) | (series['date'] > end)]['adjusted_demand']
            expected = float(comparable.median()) if len(comparable) else float(series['adjusted_demand'].median())
            affected = series['date'].between(start, end)
            affected_idx = series.loc[affected].index
            daily.loc[affected_idx, 'estimated_lost_demand'] = np.maximum(expected - daily.loc[affected_idx, 'adjusted_demand'], 0)
            daily.loc[affected_idx, 'adjusted_demand'] = np.maximum(daily.loc[affected_idx, 'adjusted_demand'], expected)
            daily.loc[affected_idx, 'is_stockout'] = True
    stock = data.get('stock', pd.DataFrame()).copy()
    transit = data.get('transit', pd.DataFrame()).copy()
    if not stock.empty:
        stock['current_stock'] = pd.to_numeric(stock['current_stock'], errors='coerce').fillna(0)
    if not transit.empty:
        transit['quantity_in_transit'] = pd.to_numeric(transit['quantity_in_transit'], errors='coerce').fillna(0)
    supplier_frame = data.get('suppliers', pd.DataFrame()).copy()
    recommendations: list[dict] = []
    for (sku, wh), group in daily.groupby(['sku', 'warehouse']):
        group = group.sort_values('date').reset_index(drop=True)
        supplier_rows = supplier_frame[supplier_frame['sku'].astype(str) == str(sku)] if not supplier_frame.empty else pd.DataFrame()
        supplier = supplier_rows.iloc[0].to_dict() if not supplier_rows.empty else {'supplier_id': 'UNASSIGNED', 'supplier_name': 'Unassigned supplier', 'lead_time_days': 14, 'moq': 0, 'package_size': 1}
        lead = max(1, int(_number(supplier.get('lead_time_days', 14))))
        forecast, details = forecast_series(group, lead + safety_days, safety_days)
        forecast_lead = float(forecast[:lead].sum())
        demand_std = float(group['adjusted_demand'].tail(56).std(ddof=0) or 0)
        safety = float(service_factor * demand_std * np.sqrt(lead))
        stock_rows = stock[(stock['sku'].astype(str) == str(sku)) & (stock['warehouse'] == wh)] if not stock.empty else pd.DataFrame()
        transit_rows = transit[(transit['sku'].astype(str) == str(sku)) & (transit['warehouse'] == wh)] if not transit.empty else pd.DataFrame()
        current = _number(stock_rows.iloc[0].get('current_stock', 0)) if not stock_rows.empty else 0
        incoming = _number(transit_rows['quantity_in_transit'].sum()) if not transit_rows.empty else 0
        inventory_position = current + incoming
        raw_order = max(0.0, forecast_lead + safety - inventory_position)
        moq = max(0.0, _number(supplier.get('moq', 0)))
        package = max(1.0, _number(supplier.get('package_size', 1)))
        unit_cost = _number(supplier.get('unit_cost', supplier.get('price', 0)))
        if not unit_cost and 'price' in group.columns:
            unit_cost = _number(group['price'].iloc[0])
        minimum_order_value = max(0.0, _number(supplier.get('minimum_order_value', 0)))
        recommended = raw_order
        if recommended > 0 and moq:
            recommended = max(recommended, moq)
        if recommended > 0 and minimum_order_value and unit_cost > 0:
            recommended = max(recommended, minimum_order_value / unit_cost)
        if recommended > 0 and package > 1:
            recommended = np.ceil(recommended / package) * package
        avg = max(details['average_daily_demand'], 0.01)
        days_cover = inventory_position / avg
        if days_cover < lead and raw_order > 0:
            urgency = 'CRITICAL'
        elif raw_order > 0 and inventory_position < forecast_lead + safety:
            urgency = 'HIGH'
        elif raw_order > 0:
            urgency = 'MEDIUM'
        else:
            urgency = 'LOW'
        recommended = round(float(recommended), 2)
        total_cost_kzt = round(recommended * unit_cost, 2)

        lost = float(group['estimated_lost_demand'].sum())
        outlier_count = len(outliers[(outliers['sku'] == sku) & (outliers['warehouse'] == wh)])
        explanation = _explanation(recommended, lead, forecast_lead, current, incoming, safety, details, outlier_count, lost, moq, package, unit_cost, total_cost_kzt, minimum_order_value)
        metadata = {'forecast_model': details['model'], 'forecast_horizon_days': lead + safety_days, 'demand_std': round(demand_std, 2), 'service_factor': service_factor, 'raw_order': round(raw_order, 2), 'rounded_order': round(recommended, 2), 'unit_cost': round(unit_cost, 2), 'total_cost_kzt': round(total_cost_kzt, 2), 'minimum_order_value': round(minimum_order_value, 2), 'outliers_removed': outlier_rows, 'stockout_adjustments': [{'estimated_lost_demand': round(lost, 2)}] if lost else []}
        recommendations.append({'id': f'{sku}:{wh}', 'sku': sku, 'product_name': group['product_name'].iloc[0], 'warehouse': wh, 'category': group['category'].iloc[0], 'supplier_id': str(supplier.get('supplier_id', 'UNASSIGNED')), 'supplier_name': str(supplier.get('supplier_name', 'Unassigned supplier')), 'current_stock': round(current, 2), 'in_transit': round(incoming, 2), 'average_daily_demand': round(avg, 2), 'forecast_lead_time': round(forecast_lead, 2), 'safety_stock': round(safety, 2), 'inventory_position': round(inventory_position, 2), 'raw_recommended_quantity': round(raw_order, 2), 'recommended_quantity': round(recommended, 2), 'final_quantity': round(recommended, 2), 'unit_cost': round(unit_cost, 2), 'total_cost_kzt': round(total_cost_kzt, 2), 'lead_time_days': lead, 'days_of_cover': round(days_cover, 1), 'urgency': urgency, 'trend_direction': details['trend_direction'], 'trend_percent': details['trend_percent'], 'seasonality_detected': details['seasonality_detected'], 'outliers_removed': outlier_count, 'estimated_lost_demand': round(lost, 2), 'status': 'DRAFT', 'explanation': explanation, 'metadata': metadata})
    return recommendations, outlier_rows


def _explanation(recommended: float, lead: int, forecast: float, current: float, incoming: float, safety: float, details: dict, outliers: int, lost: float, moq: float, package: float, unit_cost: float = 0.0, total_cost_kzt: float = 0.0, minimum_order_value: float = 0.0) -> str:
    lines = [f'Recommended: {recommended:g} units.', f'Expected demand during the supplier\'s {lead}-day lead time: {forecast:g} units.', f'Current warehouse stock: {current:g} units.', f'Goods already in transit: {incoming:g} units.', f'Safety stock: {safety:g} units.', f'Trend: {details["trend_direction"]} ({details["trend_percent"]:+.1f}%).']
    if details['seasonality_detected']:
        lines.append('A seasonal demand pattern was detected and included in the forecast.')
    if outliers:
        lines.append(f'{outliers} one-off transaction(s) were excluded from regular demand using a robust MAD check.')
    if lost:
        lines.append(f'Estimated lost demand of {lost:g} units was added for stockout periods.')
    if moq and recommended:
        lines.append(f'Supplier MOQ of {moq:g} units was respected.')
    if package > 1 and recommended:
        lines.append(f'Quantity was rounded up to a package multiple of {package:g}.')
    if minimum_order_value and total_cost_kzt >= minimum_order_value:
        lines.append(f'Supplier minimum order value of {minimum_order_value:,.0f} KZT was respected.')
    if total_cost_kzt > 0:
        lines.append(f'Total estimated budget: {total_cost_kzt:,.0f} KZT ({unit_cost:,.0f} KZT/unit).')
    return ' '.join(lines)
