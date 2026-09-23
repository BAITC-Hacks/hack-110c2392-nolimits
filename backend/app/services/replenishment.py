from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import forecast_series, mad_outliers


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def resolve_as_of(data: dict[str, pd.DataFrame], as_of: Any = None) -> pd.Timestamp:
    """One closing-date cutoff for every warehouse, calculation and chart.

    Explicit snapshots win. Without one, completed historical stockout records
    may extend the last sales date; future intervals are not observations.
    """
    if as_of is not None:
        cutoff = pd.to_datetime(as_of, errors='coerce')
        if pd.isna(cutoff):
            raise ValueError('Invalid calculation as_of date')
        return pd.Timestamp(cutoff).tz_localize(None).normalize()
    stock = data.get('stock', pd.DataFrame())
    for column in ('as_of', 'snapshot_date', 'balance_date', 'остаток_на_дату'):
        if column in stock:
            dates = pd.to_datetime(stock[column], errors='coerce')
            if dates.notna().any():
                return pd.Timestamp(dates.max()).tz_localize(None).normalize()
    sales = data.get('sales', pd.DataFrame())
    cutoff = pd.to_datetime(sales.get('date', pd.Series(dtype='datetime64[ns]')), errors='coerce').max()
    stockouts = data.get('stockouts', pd.DataFrame())
    if not stockouts.empty and 'end_date' in stockouts and pd.notna(cutoff):
        ends = pd.to_datetime(stockouts['end_date'], errors='coerce')
        ends = ends[ends <= pd.Timestamp.now().normalize()]
        if ends.notna().any():
            cutoff = max(cutoff, ends.max())
    return pd.Timestamp(cutoff).normalize() if pd.notna(cutoff) else pd.NaT


def _recurring_large_orders(client_day: pd.DataFrame, candidates: pd.Series) -> pd.Index:
    """Keep repeated, similarly sized client orders rather than erase B2B demand.

    Require four orders over at least three weeks with a reasonably regular
    cadence. An isolated project-sized spike remains an outlier even for an
    otherwise recurring customer.
    """
    retained: list[int] = []
    for _, orders in client_day.loc[candidates].groupby('customer_id', dropna=False):
        typical = float(orders['quantity'].median())
        comparable = orders[orders['quantity'].between(typical * 0.5, typical * 2)].sort_values('date')
        if len(comparable) < 4:
            continue
        gaps = comparable['date'].diff().dropna().dt.days
        cadence = float(gaps.median())
        span = (comparable['date'].iloc[-1] - comparable['date'].iloc[0]).days
        if span >= 21 and 1 <= cadence <= 35 and float(gaps.max()) <= 2 * cadence + 2:
            retained.extend(comparable.index.tolist())
    return pd.Index(retained)


def prepare_demand(data: dict[str, pd.DataFrame], warehouse: str | None = None, category: str | None = None, outlier_threshold: float = 3.5, as_of: Any = None) -> tuple[pd.DataFrame, list[dict]]:
    """Build one calendar-day demand series per SKU/warehouse for calculation and charts."""
    sales = data['sales'].copy()
    if sales.empty:
        return pd.DataFrame(), []
    sales['date'] = pd.to_datetime(sales['date']).dt.normalize()
    sales['quantity'] = pd.to_numeric(sales['quantity'], errors='coerce').fillna(0)
    unknown_ids = sales['customer_id'].isna() | sales['customer_id'].astype(str).str.strip().isin(['', 'UNKNOWN'])
    if 'customer_id_unknown' in sales:
        unknown_ids |= sales['customer_id_unknown'].fillna(False).astype(bool)
    sales['customer_id_unknown'] = unknown_ids
    sales['unreconciled_return'] = 0.0
    cutoff = resolve_as_of(data, as_of)
    sales = sales[sales['date'] <= cutoff]
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
            if returned.customer_id_unknown:
                sales.at[returned.Index, 'unreconciled_return'] = outstanding
                continue
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
            sales.at[returned.Index, 'unreconciled_return'] = outstanding
    sales['quantity'] = sales['quantity'].clip(lower=0)
    if sales.empty:
        return pd.DataFrame(), []
    sales['adjusted_quantity'] = sales['quantity'].astype(float)
    # A purchase may be split across many invoice lines. Detect the client/day total.
    keys = ['sku', 'warehouse', 'date', 'customer_id']
    client_day = sales.groupby(keys, dropna=False).agg(quantity=('quantity', 'sum'), customer_id_unknown=('customer_id_unknown', 'any')).reset_index()
    client_day['is_outlier'] = False
    client_day['typical_quantity'] = 0.0
    for _, indices in client_day.groupby(['sku', 'warehouse']).groups.items():
        # Missing client IDs are not one real buyer. Keep their demand, do not
        # invent client-level anomaly or return reconciliation evidence.
        known_indices = indices[~client_day.loc[indices, 'customer_id_unknown'].to_numpy()]
        if not len(known_indices):
            continue
        flagged = mad_outliers(client_day.loc[known_indices, 'quantity'], outlier_threshold)
        recurring = _recurring_large_orders(client_day.loc[known_indices], flagged)
        flagged.loc[recurring] = False
        client_day.loc[known_indices[flagged.to_numpy()], 'is_outlier'] = True
        normal = client_day.loc[known_indices[~flagged.to_numpy()], 'quantity']
        client_day.loc[indices, 'typical_quantity'] = float(normal.median()) if len(normal) else 0.0
    sales = sales.merge(client_day[keys + ['is_outlier']], on=keys, how='left', validate='many_to_one')
    sales.loc[sales['is_outlier'], 'adjusted_quantity'] = 0.0
    outlier_rows = [{
        'date': item.date.strftime('%Y-%m-%d'), 'sku': item.sku, 'warehouse': item.warehouse,
        'customer_id': item.customer_id, 'quantity': round(float(item.quantity), 2),
        'typical_quantity': round(float(item.typical_quantity), 2),
        'reason': 'Client/day total exceeds robust MAD threshold; possible one-off order', 'used_in_forecast': False,
    } for item in client_day.loc[client_day['is_outlier']].itertuples()]
    daily = sales.groupby(['sku', 'warehouse', 'date'], as_index=False).agg(
        actual_sales=('quantity', 'sum'), adjusted_demand=('adjusted_quantity', 'sum'),
        product_name=('product_name', 'first'), category=('category', 'first'), is_outlier=('is_outlier', 'any'),
        unknown_customer_sales=('customer_id_unknown', 'any'), unreconciled_returns=('unreconciled_return', 'sum'))
    for _, indices in daily.groupby(['sku', 'warehouse']).groups.items():
        normal = daily.loc[indices, 'adjusted_demand']
        typical_day = float(normal[normal > 0].median()) if (normal > 0).any() else 0.0
        only_outlier = daily.loc[indices, 'is_outlier'] & (normal == 0)
        daily.loc[indices[only_outlier.to_numpy()], 'adjusted_demand'] = typical_day
    last_date = cutoff
    stockouts = data.get('stockouts', pd.DataFrame())
    result = []
    for (sku, wh), group in daily.groupby(['sku', 'warehouse']):
        group = group.set_index('date').reindex(pd.date_range(group['date'].min(), last_date, freq='D').rename('date'))
        group[['sku', 'warehouse', 'product_name', 'category']] = group[['sku', 'warehouse', 'product_name', 'category']].ffill().bfill()
        group[['actual_sales', 'adjusted_demand']] = group[['actual_sales', 'adjusted_demand']].fillna(0)
        group['is_outlier'] = group['is_outlier'].eq(True)
        group['unknown_customer_sales'] = group['unknown_customer_sales'].eq(True)
        group['unreconciled_returns'] = group['unreconciled_returns'].fillna(0)
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


def calculate_recommendations(data: dict[str, pd.DataFrame], warehouse: str | None = None, category: str | None = None, safety_days: int = 7, service_factor: float = 1.65, outlier_threshold: float = 3.5, as_of: Any = None) -> tuple[list[dict], list[dict]]:
    cutoff = resolve_as_of(data, as_of)
    daily, outlier_rows = prepare_demand(data, warehouse, category, outlier_threshold, cutoff)
    if daily.empty:
        return [], []
    source = hashlib.sha256()
    for name in ('sales', 'stock', 'transit', 'stockouts', 'suppliers'):
        source.update(name.encode())
        # Drafts are stored as JSON records, so the signature must survive
        # their reload (timestamps become ISO strings and empty frames lose columns).
        frame = data.get(name, pd.DataFrame())
        frame = frame[[column for column in frame.columns if not str(column).startswith('__')]]
        records = json.loads(frame.to_json(orient='records', date_format='iso'))
        normalized = sorted(json.dumps(record, sort_keys=True, ensure_ascii=False) for record in records)
        source.update(json.dumps(normalized, ensure_ascii=False).encode('utf-8'))
    dataset_signature = source.hexdigest()
    calculation_signature = hashlib.sha256(json.dumps({
        'dataset': dataset_signature, 'as_of': cutoff.strftime('%Y-%m-%d'),
        'safety_days': safety_days, 'service_factor': service_factor,
        'outlier_threshold': outlier_threshold, 'model_version': 'calendar-demand-v2',
    }, sort_keys=True).encode()).hexdigest()
    stock = data.get('stock', pd.DataFrame()).copy()
    transit = data.get('transit', pd.DataFrame()).copy()
    has_snapshot_date = any(
        column in stock and pd.to_datetime(stock[column], errors='coerce').notna().any()
        for column in ('as_of', 'snapshot_date', 'balance_date', 'остаток_на_дату')
    )
    as_of_source = 'explicit' if as_of is not None else 'stock_snapshot' if has_snapshot_date else 'inferred_from_history'
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
        warnings: list[str] = []
        data_quality_warnings: list[str] = []
        if group['unknown_customer_sales'].any():
            data_quality_warnings.append('Customer identity is missing: client-level outlier detection is unavailable for those sales; demand is retained.')
        unreconciled_returns = float(group['unreconciled_returns'].sum())
        if unreconciled_returns > 0:
            data_quality_warnings.append(f'{unreconciled_returns:g} returned units could not be matched to a client invoice; no unrelated sale was offset.')
        for record in [supplier, *stock_rows.to_dict(orient='records')]:
            source_warning = record.get('source_warning')
            if pd.notna(source_warning) and source_warning:
                data_quality_warnings.append(str(source_warning))
        balance_is_stale = bool(stock_rows.get('balance_is_stale', pd.Series(False, index=stock_rows.index)).fillna(False).any())
        if balance_is_stale:
            data_quality_warnings.append('Stock balance is stale; enter the current available balance before approving this recommendation.')
        unknown_cost_value = supplier.get('cost_unknown', False)
        cost_unknown = bool(unknown_cost_value) if pd.notna(unknown_cost_value) else False
        if cost_unknown:
            data_quality_warnings.append('Purchase cost is unknown; zero is a placeholder, not a confirmed supplier price.')
        data_quality_warnings = list(dict.fromkeys(data_quality_warnings))
        overdue_quantity = unknown_quantity = 0.0
        arrivals_per_day = np.zeros(lead)
        if not transit_rows.empty:
            arrivals = pd.to_datetime(transit_rows['expected_arrival_date'], errors='coerce').dt.normalize()
            due = cutoff + pd.Timedelta(days=lead)
            pending = transit_rows['quantity_in_transit'] > 0
            overdue = pending & (arrivals <= cutoff)
            unknown = pending & arrivals.isna()
            eligible = pending & (arrivals > cutoff) & (arrivals <= due)
            incoming = _number(transit_rows.loc[eligible, 'quantity_in_transit'].sum())
            for index in transit_rows.index[eligible]:
                arrival_day = (arrivals.loc[index] - cutoff).days
                arrivals_per_day[arrival_day - 1] += float(transit_rows.loc[index, 'quantity_in_transit'])
            if overdue.any():
                overdue_quantity = float(transit_rows.loc[overdue, 'quantity_in_transit'].sum())
                warnings.append(f'{overdue_quantity:g} overdue inbound units excluded; confirm a new arrival date or register receipt.')
            if unknown.any():
                unknown_quantity = float(transit_rows.loc[unknown, 'quantity_in_transit'].sum())
                warnings.append(f'{unknown_quantity:g} inbound units without an arrival date excluded.')
        else:
            incoming = 0
        if as_of_source == 'inferred_from_history':
            warnings.append('Calculation date inferred from source data; confirm the closing-date snapshot before approval.')
        inventory_position = current + incoming
        raw_order = max(0.0, forecast_lead + safety - inventory_position)
        if raw_order < 1e-9:
            raw_order = 0.0
        moq = max(0.0, _number(supplier.get('moq', 0)))
        package = _number(supplier.get('package_size', 1))
        package = package if package > 0 else 1.0
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
        days_cover = current / avg
        # Receipts arrive before demand on their scheduled day. Follow the whole
        # horizon: a tiny early shipment cannot mask a gap before the next one.
        balances = current + np.cumsum(arrivals_per_day - forecast[:lead])
        shortage_days = np.flatnonzero(balances < -1e-8)
        first_shortage_date = (cutoff + pd.Timedelta(days=int(shortage_days[0]) + 1)).strftime('%Y-%m-%d') if len(shortage_days) else None
        if first_shortage_date:
            urgency = 'CRITICAL'
            warnings.append(f'Projected stock deficit begins on {first_shortage_date}; expedite or transfer stock before the regular replenishment arrives.')
        elif raw_order > 0 and inventory_position < forecast_lead + safety:
            urgency = 'HIGH'
        elif raw_order > 0:
            urgency = 'MEDIUM'
        else:
            urgency = 'LOW'
        recommended = round(float(recommended), 8)
        if not unit_cost and 'price' in group.columns:
            unit_cost = _number(group['price'].iloc[0])
        total_cost_kzt = round(recommended * unit_cost, 2)

        lost = float(group['estimated_lost_demand'].sum())
        relevant_outliers = [item for item in outlier_rows if item['sku'] == sku and item['warehouse'] == wh]
        outlier_count = len(relevant_outliers)
        explanation = _explanation(recommended, lead, forecast_lead, current, incoming, safety, details, outlier_count, lost, moq, package, unit_cost, total_cost_kzt, minimum_order_value)
        if warnings or data_quality_warnings:
            explanation += ' ' + ' '.join(warnings + data_quality_warnings)
        metadata = {
            'dataset_signature': dataset_signature, 'calculation_signature': calculation_signature,
            'as_of': cutoff.strftime('%Y-%m-%d'), 'as_of_source': as_of_source,
            'forecast_model': details['model'],
            'forecast_horizon_days': lead + safety_days, 'safety_days': safety_days,
            'outlier_threshold': outlier_threshold, 'demand_std': round(demand_std, 2),
            'service_factor': service_factor, 'raw_order': round(raw_order, 8),
            'rounded_order': recommended, 'unit_cost': round(unit_cost, 2),
            'total_cost_kzt': round(total_cost_kzt, 2), 'minimum_order_value': round(minimum_order_value, 2),
            'warnings': warnings, 'first_shortage_date': first_shortage_date,
            'overdue_inbound': overdue_quantity, 'unknown_arrival_inbound': unknown_quantity,
            'data_quality_warnings': data_quality_warnings, 'balance_is_stale': balance_is_stale,
            'source_warning': ' '.join(str(value) for value in stock_rows.get('source_warning', pd.Series(dtype=str)).dropna() if value),
            'cost_unknown': cost_unknown, 'unreconciled_returns': unreconciled_returns,
            'minimum_projected_balance': round(float(balances.min()), 2),
            'outliers_removed': relevant_outliers,
            'stockout_adjustments': [{'estimated_lost_demand': round(lost, 2)}] if lost else [],
        }
        recommendations.append({'id': f'{sku}:{wh}', 'sku': sku, 'product_name': group['product_name'].iloc[0], 'warehouse': wh, 'category': group['category'].iloc[0], 'supplier_id': str(supplier.get('supplier_id', 'UNASSIGNED')), 'supplier_name': str(supplier.get('supplier_name', 'Unassigned supplier')), 'current_stock': round(current, 2), 'in_transit': round(incoming, 2), 'average_daily_demand': round(avg, 2), 'forecast_lead_time': round(forecast_lead, 2), 'safety_stock': round(safety, 2), 'inventory_position': round(inventory_position, 2), 'raw_recommended_quantity': round(raw_order, 8), 'recommended_quantity': recommended, 'final_quantity': recommended, 'unit_cost': round(unit_cost, 2), 'total_cost_kzt': round(total_cost_kzt, 2), 'lead_time_days': lead, 'days_of_cover': round(days_cover, 1), 'urgency': urgency, 'trend_direction': details['trend_direction'], 'trend_percent': details['trend_percent'], 'seasonality_detected': details['seasonality_detected'], 'outliers_removed': outlier_count, 'estimated_lost_demand': round(lost, 2), 'status': 'DRAFT', 'explanation': explanation, 'metadata': metadata})
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
    if package != 1 and recommended:
        lines.append(f'Quantity was rounded up to a package multiple of {package:g}.')
    if minimum_order_value and total_cost_kzt >= minimum_order_value:
        lines.append(f'Supplier minimum order value of {minimum_order_value:,.0f} KZT was respected.')
    if total_cost_kzt > 0:
        lines.append(f'Total estimated budget: {total_cost_kzt:,.0f} KZT ({unit_cost:,.0f} KZT/unit).')
    return ' '.join(lines)
