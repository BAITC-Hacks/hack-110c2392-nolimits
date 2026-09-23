from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import forecast_series, mad_outliers


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def prepare_demand(data: dict[str, pd.DataFrame], warehouse: str | None = None, category: str | None = None, outlier_threshold: float = 3.5) -> tuple[pd.DataFrame, list[dict]]:
    """Build one calendar-day demand series per SKU/warehouse for calculation and charts."""
    sales = data['sales'].copy()
    if sales.empty:
        return pd.DataFrame(), []
    sales['date'] = pd.to_datetime(sales['date']).dt.normalize()
    sales['quantity'] = pd.to_numeric(sales['quantity'], errors='coerce').fillna(0)
    if warehouse:
        sales = sales[sales['warehouse'] == warehouse]
    if category:
        sales = sales[sales['category'] == category]
    if sales.empty:
        return pd.DataFrame(), []
    if 'transaction_type' in sales:
        dropship = sales['transaction_type'].astype(str).str.contains('транзитная поставка|dropship|drop-ship', case=False, regex=True)
        sales = sales.loc[~dropship].copy()
        # Reconcile credit notes against the originating client invoice before
        # anomaly detection. A 4,000-unit typo with a -3,960 return is 40 units.
        for returned in sales.loc[sales['quantity'] < 0].sort_values('date').itertuples():
            outstanding = -float(returned.quantity)
            candidates = sales[(sales['sku'] == returned.sku) & (sales['warehouse'] == returned.warehouse)
                               & (sales['customer_id'] == returned.customer_id)
                               & (sales['date'] <= returned.date)
                               & (sales['date'] >= returned.date - pd.Timedelta(days=7))
                               & (sales['quantity'] > 0)].sort_values('date', ascending=False)
            for index in candidates.index:
                offset = min(outstanding, float(sales.at[index, 'quantity']))
                sales.at[index, 'quantity'] -= offset
                outstanding -= offset
                if outstanding <= 0:
                    break
    sales['quantity'] = sales['quantity'].clip(lower=0)
    if sales.empty:
        return pd.DataFrame(), []
    sales['adjusted_quantity'] = sales['quantity'].astype(float)
    # A purchase may be split across many invoice lines. Detect the client/day total.
    keys = ['sku', 'warehouse', 'date', 'customer_id']
    client_day = sales.groupby(keys, dropna=False)['quantity'].sum().reset_index()
    client_day['is_outlier'] = False
    for _, indices in client_day.groupby(['sku', 'warehouse']).groups.items():
        flagged = mad_outliers(client_day.loc[indices, 'quantity'], outlier_threshold)
        client_day.loc[indices[flagged.to_numpy()], 'is_outlier'] = True
    sales = sales.merge(client_day[keys + ['is_outlier']], on=keys, how='left', validate='many_to_one')
    sales.loc[sales['is_outlier'], 'adjusted_quantity'] = 0.0
    outlier_rows = [{
        'date': item.date.strftime('%Y-%m-%d'), 'sku': item.sku, 'warehouse': item.warehouse,
        'customer_id': item.customer_id, 'quantity': round(float(item.quantity), 2),
        'typical_quantity': 0.0,
        'reason': 'Client/day total exceeds robust MAD threshold; possible one-off order', 'used_in_forecast': False,
    } for item in client_day.loc[client_day['is_outlier']].itertuples()]
    daily = sales.groupby(['sku', 'warehouse', 'date'], as_index=False).agg(
        actual_sales=('quantity', 'sum'), adjusted_demand=('adjusted_quantity', 'sum'),
        product_name=('product_name', 'first'), category=('category', 'first'), is_outlier=('is_outlier', 'any'))
    for _, indices in daily.groupby(['sku', 'warehouse']).groups.items():
        normal = daily.loc[indices, 'adjusted_demand']
        typical_day = float(normal[normal > 0].median()) if (normal > 0).any() else 0.0
        only_outlier = daily.loc[indices, 'is_outlier'] & (normal == 0)
        daily.loc[indices[only_outlier.to_numpy()], 'adjusted_demand'] = typical_day
    last_date = daily['date'].max()
    stockouts = data.get('stockouts', pd.DataFrame())
    result = []
    for (sku, wh), group in daily.groupby(['sku', 'warehouse']):
        group = group.set_index('date').reindex(pd.date_range(group['date'].min(), last_date, freq='D').rename('date'))
        group[['sku', 'warehouse', 'product_name', 'category']] = group[['sku', 'warehouse', 'product_name', 'category']].ffill().bfill()
        group[['actual_sales', 'adjusted_demand']] = group[['actual_sales', 'adjusted_demand']].fillna(0)
        group['is_outlier'] = group['is_outlier'].eq(True)
        group['estimated_lost_demand'] = 0.0
        group['is_stockout'] = False
        if not stockouts.empty:
            periods = stockouts[(stockouts['sku'].astype(str) == str(sku)) & (stockouts['warehouse'] == wh)]
            affected = np.zeros(len(group), dtype=bool)
            for period in periods.itertuples():
                start, end = pd.to_datetime(period.start_date), pd.to_datetime(period.end_date)
                if pd.notna(start) and pd.notna(end) and end >= start:
                    affected |= (group.index >= start) & (group.index <= end)
            if affected.any():
                comparable = group.loc[~affected, 'adjusted_demand']
                expected = float(comparable.median()) if len(comparable) else 0.0
                group.loc[affected, 'estimated_lost_demand'] = np.maximum(expected - group.loc[affected, 'adjusted_demand'], 0)
                group.loc[affected, 'adjusted_demand'] = np.maximum(group.loc[affected, 'adjusted_demand'], expected)
                group.loc[affected, 'is_stockout'] = True
        result.append(group.reset_index())
    return pd.concat(result, ignore_index=True), outlier_rows


def calculate_recommendations(data: dict[str, pd.DataFrame], warehouse: str | None = None, category: str | None = None, safety_days: int = 7, service_factor: float = 1.65, outlier_threshold: float = 3.5) -> tuple[list[dict], list[dict]]:
    daily, outlier_rows = prepare_demand(data, warehouse, category, outlier_threshold)
    if daily.empty:
        return [], []
    source = hashlib.sha256()
    for name in ('sales', 'stock', 'transit', 'stockouts', 'suppliers'):
        source.update(name.encode())
        source.update(data.get(name, pd.DataFrame()).to_csv(index=False).encode('utf-8'))
    dataset_signature = source.hexdigest()
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
        if not transit_rows.empty:
            arrivals = pd.to_datetime(transit_rows['expected_arrival_date'], errors='coerce')
            due = group['date'].max() + pd.Timedelta(days=lead)
            incoming = _number(transit_rows.loc[arrivals <= due, 'quantity_in_transit'].sum())
        else:
            incoming = 0
        inventory_position = current + incoming
        raw_order = max(0.0, forecast_lead + safety - inventory_position)
        moq = max(0.0, _number(supplier.get('moq', 0)))
        package = max(1.0, _number(supplier.get('package_size', 1)))
        unit_cost = _number(supplier.get('unit_cost', supplier.get('price', 0)))
        minimum_order_value = max(0.0, _number(supplier.get('minimum_order_value', 0)))
        recommended = raw_order
        if recommended > 0 and moq:
            recommended = max(recommended, moq)
        if recommended > 0 and minimum_order_value and unit_cost > 0:
            recommended = max(recommended, minimum_order_value / unit_cost)
        if recommended > 0:
            recommended = np.ceil((recommended - 1e-9) / package) * package
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
        if not unit_cost and 'price' in group.columns:
            unit_cost = _number(group['price'].iloc[0])
        total_cost_kzt = round(recommended * unit_cost, 2)

        lost = float(group['estimated_lost_demand'].sum())
        relevant_outliers = [item for item in outlier_rows if item['sku'] == sku and item['warehouse'] == wh]
        outlier_count = len(relevant_outliers)
        explanation = _explanation(recommended, lead, forecast_lead, current, incoming, safety, details, outlier_count, lost, moq, package, unit_cost, total_cost_kzt, minimum_order_value)
        metadata = {'dataset_signature': dataset_signature, 'forecast_model': details['model'], 'forecast_horizon_days': lead + safety_days, 'demand_std': round(demand_std, 2), 'service_factor': service_factor, 'raw_order': round(raw_order, 2), 'rounded_order': round(recommended, 2), 'unit_cost': round(unit_cost, 2), 'total_cost_kzt': round(total_cost_kzt, 2), 'minimum_order_value': round(minimum_order_value, 2), 'outliers_removed': relevant_outliers, 'stockout_adjustments': [{'estimated_lost_demand': round(lost, 2)}] if lost else []}
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
