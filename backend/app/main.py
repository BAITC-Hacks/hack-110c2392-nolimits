from __future__ import annotations

import io
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .schemas import AdjustOrderRequest, CalculateRequest
from .services.demo import build_demo_data
from .services.replenishment import calculate_recommendations
from .services.validation import read_table, validate_table
from .repositories.database import init_db, save_recommendations, update_order


class AppState:
    def __init__(self) -> None:
        self.datasets: dict[str, pd.DataFrame] = {name: pd.DataFrame() for name in ['sales', 'stock', 'transit', 'stockouts', 'suppliers']}
        self.recommendations: list[dict] = []
        self.outliers: list[dict] = []
        self.last_calculation: dict = {}

    def load_demo(self) -> dict[str, int]:
        self.datasets = build_demo_data()
        self.recommendations = []
        self.outliers = []
        return {key: len(value) for key, value in self.datasets.items()}


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    state.load_demo()
    state.recommendations, state.outliers = calculate_recommendations(state.datasets)
    save_recommendations(state.recommendations)
    yield


app = FastAPI(title='StockPilot API', version='1.0.0', description='Explainable warehouse replenishment recommendations', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://localhost:4173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])


@app.get('/health')
def health() -> dict:
    return {'status': 'ok', 'service': 'stockpilot-api'}


@app.get('/api/data/status')
def data_status() -> dict:
    return {'datasets': {key: len(value) for key, value in state.datasets.items()}, 'recommendations': len(state.recommendations), 'has_data': bool(len(state.datasets['sales']))}


@app.post('/api/data/demo')
def load_demo() -> dict:
    counts = state.load_demo()
    return {'message': 'Deterministic demo dataset loaded', 'datasets': counts}


@app.post('/api/data/upload/{dataset}')
async def upload(dataset: str, file: UploadFile = File(...)) -> dict:
    if dataset not in state.datasets:
        raise HTTPException(status_code=404, detail=f'Unknown dataset: {dataset}')
    try:
        raw = await file.read()
        frame = read_table(raw, file.filename or 'upload.csv')
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Could not read {file.filename}: {exc}') from exc
    known = set(state.datasets['stock'].get('warehouse', pd.Series(dtype=str)).dropna().astype(str))
    cleaned, errors, warnings = validate_table(dataset, frame, known)
    if len(cleaned):
        state.datasets[dataset] = cleaned
        state.recommendations = []
        state.outliers = []
    return {'dataset': dataset, 'rows_loaded': len(cleaned), 'errors': errors, 'warnings': warnings}


@app.post('/api/recommendations/calculate')
def calculate(request: CalculateRequest = CalculateRequest()) -> dict:
    recommendations, outliers = calculate_recommendations(state.datasets, request.warehouse, request.category, request.safety_days, request.service_factor, request.outlier_threshold)
    state.recommendations = recommendations
    state.outliers = outliers
    state.last_calculation = request.model_dump()
    save_recommendations(recommendations)
    return {'count': len(recommendations), 'outliers': len(outliers), 'recommendations': _json_safe(recommendations)}


@app.get('/api/recommendations')
def recommendations(warehouse: str | None = None, supplier: str | None = None, category: str | None = None, urgency: str | None = None, search: str | None = None) -> dict:
    rows = state.recommendations
    if warehouse:
        rows = [row for row in rows if row['warehouse'] == warehouse]
    if supplier:
        rows = [row for row in rows if row['supplier_id'] == supplier or row['supplier_name'] == supplier]
    if category:
        rows = [row for row in rows if row['category'] == category]
    if urgency:
        rows = [row for row in rows if row['urgency'] == urgency]
    if search:
        needle = search.lower()
        rows = [row for row in rows if needle in row['sku'].lower() or needle in row['product_name'].lower()]
    return {'recommendations': _json_safe(rows), 'summary': _json_safe(_summary(rows))}


@app.get('/api/recommendations/{order_id}')
def get_recommendation(order_id: str) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    return row


@app.get('/api/analytics/{sku}')
def analytics(sku: str, warehouse: str | None = None) -> dict:
    sales = state.datasets['sales']
    if sales.empty:
        raise HTTPException(status_code=404, detail='No sales data')
    row = sales[sales['sku'].astype(str) == sku]
    if warehouse:
        row = row[row['warehouse'] == warehouse]
    if row.empty:
        raise HTTPException(status_code=404, detail='SKU not found')
    wh = str(row['warehouse'].iloc[0])
    rec = next((item for item in state.recommendations if item['sku'] == sku and item['warehouse'] == wh), None)
    row = row.copy()
    row['date'] = pd.to_datetime(row['date'])
    daily = row.groupby('date', as_index=False).agg(actual_sales=('quantity', 'sum'), product_name=('product_name', 'first'))
    # Approximate adjusted history for the chart from the same deterministic robust rule used by the engine.
    daily['adjusted_demand'] = daily['actual_sales'].astype(float)
    if rec:
        outlier_dates = {item['date'] for item in state.outliers if item['sku'] == sku and item['warehouse'] == wh}
        for index, date in enumerate(daily['date'].dt.strftime('%Y-%m-%d')):
            if date in outlier_dates:
                daily.loc[index, 'adjusted_demand'] = daily['adjusted_demand'].median()
    stockout_dates: set[str] = set()
    stockout_rows = state.datasets['stockouts']
    if not stockout_rows.empty:
        for item in stockout_rows[(stockout_rows['sku'].astype(str) == sku) & (stockout_rows['warehouse'] == wh)].itertuples():
            stockout_dates.update(pd.date_range(item.start_date, item.end_date, freq='D').strftime('%Y-%m-%d'))
    points = [{'date': item.date.strftime('%Y-%m-%d'), 'actual_sales': round(float(item.actual_sales), 2), 'adjusted_demand': round(float(item.adjusted_demand), 2), 'is_outlier': item.date.strftime('%Y-%m-%d') in outlier_dates if rec else False, 'is_stockout': item.date.strftime('%Y-%m-%d') in stockout_dates} for item in daily.itertuples()]
    if rec:
        forecast_start = pd.to_datetime(daily['date'].max()) + pd.Timedelta(days=1)
        for day in range(rec['lead_time_days'] + 7):
            value = rec['average_daily_demand'] * (1 + rec['trend_percent'] / 100 * (day + 1) / max(rec['lead_time_days'] + 7, 1))
            points.append({'date': (forecast_start + pd.Timedelta(days=day)).strftime('%Y-%m-%d'), 'actual_sales': None, 'adjusted_demand': None, 'forecast': round(max(value, 0), 2)})
    return {'sku': sku, 'warehouse': wh, 'product_name': str(row['product_name'].iloc[0]), 'points': points, 'recommendation': rec, 'outliers': [item for item in state.outliers if item['sku'] == sku and (not warehouse or item['warehouse'] == warehouse)]}


@app.get('/api/outliers')
def outliers() -> dict:
    return {'outliers': state.outliers, 'count': len(state.outliers)}


@app.post('/api/orders/{order_id}/adjust')
def adjust_order(order_id: str, request: AdjustOrderRequest) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    row['final_quantity'] = request.final_quantity
    row['status'] = 'ADJUSTED'
    update_order(order_id, status='ADJUSTED', final_quantity=request.final_quantity)
    return row


@app.post('/api/orders/{order_id}/approve')
def approve_order(order_id: str) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    row['status'] = 'APPROVED'
    update_order(order_id, status='APPROVED')
    return row


@app.get('/api/orders/export')
def export_orders(format: str = 'csv') -> StreamingResponse:
    columns = {'SKU': 'sku', 'Product': 'product_name', 'Supplier': 'supplier_name', 'Warehouse': 'warehouse', 'Recommended Quantity': 'final_quantity', 'Urgency': 'urgency', 'Current Stock': 'current_stock', 'Goods In Transit': 'in_transit', 'Forecast': 'forecast_lead_time', 'Safety Stock': 'safety_stock', 'Lead Time': 'lead_time_days', 'Explanation': 'explanation', 'Status': 'status'}
    frame = pd.DataFrame([{label: row.get(key) for label, key in columns.items()} for row in state.recommendations])
    if format.lower() == 'xlsx':
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=stockpilot-orders.xlsx'})
    content = frame.to_csv(index=False).encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(content), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=stockpilot-orders.csv'})


def _summary(rows: list[dict]) -> dict:
    return {'skus_requiring_replenishment': sum(item['recommended_quantity'] > 0 for item in rows), 'critical_risks': sum(item['urgency'] == 'CRITICAL' for item in rows), 'total_recommended_units': round(sum(item['recommended_quantity'] for item in rows), 1), 'suppliers_involved': len({item['supplier_id'] for item in rows}), 'detected_anomalies': sum(item['outliers_removed'] for item in rows), 'estimated_lost_demand': round(sum(item['estimated_lost_demand'] for item in rows), 1)}


def _json_safe(value):
    """Convert numpy scalar values nested in calculation output to JSON primitives."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, 'item') and value.__class__.__module__.startswith('numpy'):
        return value.item()
    return value
