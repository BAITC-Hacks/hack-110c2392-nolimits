from __future__ import annotations

import io
from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .schemas import AdjustOrderRequest, CalculateRequest, EditorDraftPayload, EditorRowPayload
from .services.demo import build_demo_data
from .services.replenishment import calculate_recommendations, prepare_demand
from .services.forecasting import forecast_series
from .services.validation import parse_workbook, read_table, validate_table
from .repositories.database import (
    clear_editor_buffer,
    draft_updated_at,
    init_db,
    load_datasets_draft,
    read_editor_buffer,
    read_order_history,
    save_datasets_draft,
    save_editor_buffer,
    save_recommendations,
    update_order,
)


EDITOR_DATASETS = ('products', 'sales', 'stock', 'transit', 'stockouts', 'suppliers')


def build_product_catalog(sales: pd.DataFrame) -> pd.DataFrame:
    columns = ['sku', 'product_name', 'category', 'unit_price', 'active']
    if sales.empty:
        return pd.DataFrame(columns=columns)
    catalog = sales[['sku', 'product_name', 'category', 'price']].copy()
    catalog = catalog.rename(columns={'price': 'unit_price'}).drop_duplicates(subset=['sku'])
    catalog['active'] = True
    return catalog[columns].reset_index(drop=True)


def ensure_product_catalog(datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if 'products' not in datasets or datasets['products'].empty:
        datasets['products'] = build_product_catalog(datasets.get('sales', pd.DataFrame()))
    return datasets


class AppState:
    def __init__(self) -> None:
        self.datasets: dict[str, pd.DataFrame] = {name: pd.DataFrame() for name in EDITOR_DATASETS}
        self.recommendations: list[dict] = []
        self.outliers: list[dict] = []
        self.last_calculation: dict = {}

    def load_demo(self) -> dict[str, int]:
        self.datasets = ensure_product_catalog(build_demo_data())
        self.recommendations = []
        self.outliers = []
        self.last_calculation = {}
        return {key: len(value) for key, value in self.datasets.items()}

    def load_ekt(self) -> dict[str, int]:
        from pathlib import Path
        data_paths = [
            Path(__file__).parent.parent / "data" / "ekt_sales_and_stock_history.xlsx",
            Path("c:/Users/олд/Desktop/Alema/data/ekt_sales_and_stock_history.xlsx"),
            Path("c:/Users/олд/Desktop/HackAlem/data/ekt_sales_and_stock_history.xlsx"),
        ]
        for p in data_paths:
            if p.exists():
                with open(p, "rb") as f:
                    self.datasets = ensure_product_catalog(parse_workbook(f.read()))
                    self.recommendations = []
                    self.outliers = []
                    self.last_calculation = {}
                    return {key: len(value) for key, value in self.datasets.items()}
        return {}

    def load_anomalies(self) -> dict[str, int]:
        from pathlib import Path
        data_paths = [
            Path(__file__).parent.parent / "data" / "ekt_extreme_anomalies_sales_and_stock.xlsx",
            Path("data/ekt_extreme_anomalies_sales_and_stock.xlsx"),
            Path("c:/Users/олд/Desktop/Alema/data/ekt_extreme_anomalies_sales_and_stock.xlsx"),
            Path("c:/Users/олд/Desktop/HackAlem/data/ekt_extreme_anomalies_sales_and_stock.xlsx"),
        ]
        for p in data_paths:
            if p.exists():
                with open(p, "rb") as f:
                    self.datasets = ensure_product_catalog(parse_workbook(f.read()))
                    self.recommendations = []
                    self.outliers = []
                    self.last_calculation = {}
                    return {key: len(value) for key, value in self.datasets.items()}
        return {}


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    restored = load_datasets_draft()
    state.datasets = ensure_product_catalog(restored) if restored and not restored.get('sales', pd.DataFrame()).empty else state.datasets
    if state.datasets.get('sales', pd.DataFrame()).empty:
        state.load_demo()
    state.recommendations, state.outliers = calculate_recommendations(state.datasets)
    save_recommendations(state.recommendations)
    save_datasets_draft(state.datasets)
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
    recs, outliers = calculate_recommendations(state.datasets)
    state.recommendations = recs
    state.outliers = outliers
    save_recommendations(recs)
    save_datasets_draft(state.datasets)
    return {'message': 'Deterministic demo dataset loaded and calculated', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers)}


@app.post('/api/data/upload/{dataset}')
async def upload(dataset: str, file: UploadFile = File(...)) -> dict:
    if dataset not in state.datasets:
        raise HTTPException(status_code=404, detail=f'Unknown dataset: {dataset}')
    try:
        raw = await file.read()
        frame = read_table(raw, file.filename or 'upload.csv')
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Could not read {file.filename}: {exc}') from exc
    known_skus = set(state.datasets['sales'].get('sku', pd.Series(dtype=str)).dropna().astype(str))
    # Tables may be uploaded in any order; the current demo's warehouses are
    # not authoritative for a new import session.
    cleaned, errors, warnings = validate_table(dataset, frame, known_skus=known_skus)
    if len(cleaned) or (frame.empty and not errors):
        state.datasets[dataset] = cleaned
        state.datasets = ensure_product_catalog(state.datasets)
        state.recommendations, state.outliers = calculate_recommendations(state.datasets)
        save_recommendations(state.recommendations)
        save_datasets_draft(state.datasets)
    return {
        'dataset': dataset,
        'rows_loaded': len(cleaned),
        'errors': errors,
        'warnings': warnings,
        'recommendations': len(state.recommendations),
        'outliers': len(state.outliers),
    }


@app.post('/api/data/load-ekt')
def load_ekt() -> dict:
    counts = state.load_ekt()
    if not counts:
        raise HTTPException(status_code=404, detail='ekt.kz dataset file not found')
    recs, outliers = calculate_recommendations(state.datasets)
    state.recommendations = recs
    state.outliers = outliers
    save_recommendations(recs)
    save_datasets_draft(state.datasets)
    return {'message': 'Real ekt.kz dataset loaded and calculated', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers)}


@app.post('/api/data/load-anomalies')
def load_anomalies() -> dict:
    counts = state.load_anomalies()
    if not counts:
        raise HTTPException(status_code=404, detail='Extreme anomalies dataset file not found')
    recs, outliers = calculate_recommendations(state.datasets)
    state.recommendations = recs
    state.outliers = outliers
    save_recommendations(recs)
    save_datasets_draft(state.datasets)
    return {'message': 'Real-world extreme anomalies dataset loaded and calculated', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers)}


@app.post('/api/data/upload-workbook')
async def upload_workbook(file: UploadFile = File(...)) -> dict:
    try:
        raw = await file.read()
        datasets, errors, warnings = parse_workbook(raw, include_report=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Could not parse Excel workbook {file.filename}: {exc}') from exc
    if errors or datasets['sales'].empty:
        raise HTTPException(status_code=422, detail={'errors': errors or ['Workbook has no usable sales history']})
    state.datasets = ensure_product_catalog(datasets)
    state.last_calculation = {}
    recs, outliers = calculate_recommendations(state.datasets)
    state.recommendations = recs
    state.outliers = outliers
    save_recommendations(recs)
    save_datasets_draft(state.datasets)
    counts = {key: len(value) for key, value in state.datasets.items()}
    return {'message': f'Workbook {file.filename} loaded successfully', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers), 'errors': errors, 'warnings': warnings}


def _require_editor_dataset(dataset: str) -> None:
    if dataset not in EDITOR_DATASETS:
        raise HTTPException(status_code=404, detail=f'Unknown editor dataset: {dataset}')


def _editor_frame(dataset: str, rows: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame(rows)
    if 'row_id' in frame.columns:
        frame = frame.drop(columns=['row_id'])
    known_warehouses = set(state.datasets['stock'].get('warehouse', pd.Series(dtype=str)).dropna().astype(str))
    known_skus = set(state.datasets['sales'].get('sku', pd.Series(dtype=str)).dropna().astype(str))
    cleaned, errors, warnings = validate_table(dataset, frame, known_warehouses, known_skus)
    if errors or len(cleaned) != len(frame):
        raise HTTPException(status_code=400, detail={'message': 'Row validation failed', 'errors': errors, 'warnings': warnings})
    return cleaned.reset_index(drop=True), warnings


def _recalculate_editor_state(dataset: str, frame: pd.DataFrame, warnings: list[str] | None = None) -> dict:
    state.datasets[dataset] = frame.reset_index(drop=True)
    state.datasets = ensure_product_catalog(state.datasets)
    state.recommendations, state.outliers = calculate_recommendations(state.datasets)
    save_recommendations(state.recommendations)
    save_datasets_draft(state.datasets)
    return {
        'dataset': dataset,
        'rows': len(state.datasets[dataset]),
        'recommendations': len(state.recommendations),
        'outliers': len(state.outliers),
        'warnings': warnings or [],
    }


@app.get('/api/editor/state')
def editor_state() -> dict:
    return {
        'datasets': {name: len(state.datasets.get(name, pd.DataFrame())) for name in EDITOR_DATASETS},
        'draft': read_editor_buffer(),
        'updated_at': draft_updated_at(),
    }


@app.get('/api/editor/draft')
def get_editor_draft() -> dict:
    return {'draft': read_editor_buffer(), 'updated_at': draft_updated_at()}


@app.post('/api/editor/draft')
def save_editor_draft(payload: EditorDraftPayload) -> dict:
    _require_editor_dataset(payload.dataset)
    save_editor_buffer(payload.dataset, payload.row, payload.row_id)
    return {'saved': True, 'draft': read_editor_buffer(), 'updated_at': draft_updated_at()}


@app.delete('/api/editor/draft')
def delete_editor_draft() -> dict:
    clear_editor_buffer()
    return {'deleted': True}


@app.get('/api/editor/{dataset}')
def editor_rows(dataset: str, offset: int = 0, limit: int = 50, search: str | None = None) -> dict:
    _require_editor_dataset(dataset)
    offset = max(offset, 0)
    limit = min(max(limit, 1), 200)
    frame = state.datasets.get(dataset, pd.DataFrame())
    if search:
        needle = search.lower()
        mask = frame.astype(str).apply(lambda column: column.str.lower().str.contains(needle, regex=False, na=False)).any(axis=1)
        frame = frame.loc[mask]
    total = len(frame)
    rows = []
    for index, row in frame.iloc[offset:offset + limit].iterrows():
        rows.append({'row_id': int(index), **_json_safe(row.to_dict())})
    return {'dataset': dataset, 'columns': list(state.datasets[dataset].columns), 'rows': rows, 'total': total, 'offset': offset, 'limit': limit, 'draft': read_editor_buffer()}


@app.get('/api/editor/{dataset}/export')
def export_editor_dataset(dataset: str, format: str = 'xlsx') -> StreamingResponse:
    _require_editor_dataset(dataset)
    normalized_format = format.lower()
    if normalized_format not in {'csv', 'xlsx'}:
        raise HTTPException(status_code=400, detail="Export format must be 'csv' or 'xlsx'")
    frame = state.datasets[dataset]
    filename = f'stockpilot-{dataset}'
    if normalized_format == 'xlsx':
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment; filename={filename}.xlsx'})
    content = frame.to_csv(index=False).encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(content), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}.csv'})


@app.post('/api/editor/{dataset}/rows')
def create_editor_row(dataset: str, payload: EditorRowPayload) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    candidate = pd.concat([current, pd.DataFrame([payload.row])], ignore_index=True)
    cleaned, warnings = _editor_frame(dataset, candidate.to_dict(orient='records'))
    result = _recalculate_editor_state(dataset, cleaned, warnings)
    clear_editor_buffer()
    return result


@app.patch('/api/editor/{dataset}/rows/{row_id}')
def update_editor_row(dataset: str, row_id: int, payload: EditorRowPayload) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    if row_id < 0 or row_id >= len(current):
        raise HTTPException(status_code=404, detail='Editor row not found')
    for column, value in payload.row.items():
        if column in current.columns:
            current.at[row_id, column] = value
    cleaned, warnings = _editor_frame(dataset, current.to_dict(orient='records'))
    result = _recalculate_editor_state(dataset, cleaned, warnings)
    clear_editor_buffer()
    return result


@app.delete('/api/editor/{dataset}/rows/{row_id}')
def delete_editor_row(dataset: str, row_id: int) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    if row_id < 0 or row_id >= len(current):
        raise HTTPException(status_code=404, detail='Editor row not found')
    current = current.drop(index=row_id).reset_index(drop=True)
    result = _recalculate_editor_state(dataset, current) if current.empty else _recalculate_editor_state(dataset, _editor_frame(dataset, current.to_dict(orient='records'))[0])
    clear_editor_buffer()
    return result


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
    options = state.last_calculation
    prepared, _ = prepare_demand(state.datasets, wh, outlier_threshold=options.get('outlier_threshold', 3.5))
    daily = prepared[prepared['sku'].astype(str) == sku].sort_values('date')
    points = [{'date': item.date.strftime('%Y-%m-%d'), 'actual_sales': round(float(item.actual_sales), 2), 'adjusted_demand': round(float(item.adjusted_demand), 2), 'is_outlier': bool(item.is_outlier), 'is_stockout': bool(item.is_stockout)} for item in daily.itertuples()]
    if rec:
        forecast_start = pd.to_datetime(daily['date'].max()) + pd.Timedelta(days=1)
        forecast, _ = forecast_series(daily, rec['lead_time_days'] + options.get('safety_days', 7), options.get('safety_days', 7))
        for day, value in enumerate(forecast):
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
    row['total_cost_kzt'] = round(request.final_quantity * row['unit_cost'], 2)
    row['status'] = 'ADJUSTED'
    update_order(order_id, status='ADJUSTED', final_quantity=request.final_quantity)
    return row


@app.get('/api/orders/history')
def order_history() -> dict:
    return {'orders': read_order_history()}


@app.post('/api/orders/{order_id}/approve')
def approve_order(order_id: str) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    supplier_rows = state.datasets['suppliers']
    supplier_rows = supplier_rows[supplier_rows['sku'].astype(str) == str(row['sku'])] if not supplier_rows.empty else pd.DataFrame()
    supplier = supplier_rows.iloc[0] if not supplier_rows.empty else {}
    moq = float(supplier.get('moq', 0) or 0)
    package = float(supplier.get('package_size', 1) or 1)
    minimum_order_value = float(supplier.get('minimum_order_value', 0) or 0)
    quantity = float(row['final_quantity'])
    if quantity < 0 or (quantity > 0 and (quantity < moq or abs(quantity / package - round(quantity / package)) > 1e-8)):
        raise HTTPException(status_code=422, detail=f'Final quantity must respect supplier MOQ {moq:g} and package multiple {package:g}')
    if quantity > 0 and quantity * row['unit_cost'] + 1e-8 < minimum_order_value:
        raise HTTPException(status_code=422, detail=f'Final order value must be at least {minimum_order_value:g} KZT')
    row['status'] = 'APPROVED'
    update_order(order_id, status='APPROVED')
    return row


@app.get('/api/orders/export')
def export_orders(format: str = 'csv') -> StreamingResponse:
    normalized_format = format.lower()
    if normalized_format not in {'csv', 'xlsx'}:
        raise HTTPException(status_code=400, detail="Export format must be 'csv' or 'xlsx'")
    columns = {
        'SKU': 'sku',
        'Product': 'product_name',
        'Supplier': 'supplier_name',
        'Warehouse': 'warehouse',
        'Recommended Quantity': 'final_quantity',
        'Unit Cost (KZT)': 'unit_cost',
        'Total Cost (KZT)': 'total_cost_kzt',
        'Urgency': 'urgency',
        'Current Stock': 'current_stock',
        'Goods In Transit': 'in_transit',
        'Forecast': 'forecast_lead_time',
        'Safety Stock': 'safety_stock',
        'Lead Time': 'lead_time_days',
        'Explanation': 'explanation',
        'Status': 'status'
    }
    def spreadsheet_safe(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value
    frame = pd.DataFrame([{label: spreadsheet_safe(row.get(key)) for label, key in columns.items()} for row in state.recommendations])
    if normalized_format == 'xlsx':
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=stockpilot-orders.xlsx'})
    content = frame.to_csv(index=False).encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(content), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=stockpilot-orders.csv'})


def _summary(rows: list[dict]) -> dict:
    sales_dates = pd.to_datetime(state.datasets['sales'].get('date', pd.Series(dtype='datetime64[ns]')), errors='coerce')
    data_as_of = sales_dates.max().strftime('%Y-%m-%d') if not sales_dates.empty and pd.notna(sales_dates.max()) else None
    return {
        'data_as_of': data_as_of,
        'skus_requiring_replenishment': sum(item['final_quantity'] > 0 for item in rows),
        'critical_risks': sum(item['urgency'] == 'CRITICAL' for item in rows),
        'total_recommended_units': round(sum(item['final_quantity'] for item in rows), 1),
        'total_budget_kzt': round(sum(item.get('total_cost_kzt', 0) for item in rows), 2),
        'suppliers_involved': len({item['supplier_id'] for item in rows}),
        'detected_anomalies': sum(item['outliers_removed'] for item in rows),
        'estimated_lost_demand': round(sum(item['estimated_lost_demand'] for item in rows), 1)
    }


def _json_safe(value):
    """Convert numpy scalar values nested in calculation output to JSON primitives."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if hasattr(value, 'item') and value.__class__.__module__.startswith('numpy'):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
