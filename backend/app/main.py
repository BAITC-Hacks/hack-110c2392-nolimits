from __future__ import annotations

import io
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import date, datetime
from functools import wraps
from threading import RLock
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .schemas import AdjustOrderRequest, CalculateRequest, EditorDraftPayload, EditorRowPayload, MovementRequest
from .services.demo import build_demo_data
from .services.replenishment import calculate_recommendations, prepare_demand, resolve_as_of
from .services.forecasting import forecast_series
from .services.inventory import InventoryError, apply_movement
from .services.validation import parse_workbook, read_table, validate_table
from .repositories.database import (
    clear_editor_buffer,
    draft_updated_at,
    init_db,
    load_datasets_draft,
    load_product_catalog,
    read_editor_buffer,
    read_inventory_movement,
    read_inventory_movements,
    read_order_history,
    save_datasets_draft,
    save_editor_buffer,
    save_inventory_movement,
    save_recommendations,
    update_order,
)


EDITOR_DATASETS = ('products', 'sales', 'stock', 'transit', 'stockouts', 'suppliers')
ROW_ID = '__row_id'


def public_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Internal record identities are never model features or exported columns."""
    return frame.drop(columns=[name for name in frame.columns if str(name).startswith('__')], errors='ignore')


def public_datasets(datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {name: public_frame(frame) for name, frame in datasets.items()}


def identify_rows(datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Persist opaque JS-safe integer IDs; deleting/reordering never reuses an ID."""
    result = {}
    for name in EDITOR_DATASETS:
        frame = datasets.get(name, pd.DataFrame()).copy().reset_index(drop=True)
        old_ids = frame[ROW_ID].tolist() if ROW_ID in frame else [None] * len(frame)
        used: set[int] = set()
        identities = []
        for value in old_ids:
            identity = int(value) if pd.notna(value) else None
            if identity is None or identity in used:
                identity = uuid4().int >> 76  # 52 bits, exactly representable by JS Number
                while identity in used:
                    identity = uuid4().int >> 76
            identities.append(identity)
            used.add(identity)
        if identities or ROW_ID in frame:
            frame[ROW_ID] = pd.Series(identities, dtype='int64')
        result[name] = frame
    return result


def active_products(frame: pd.DataFrame) -> pd.DataFrame:
    if 'active' not in frame:
        return frame
    return frame[frame['active'].fillna(True).astype(str).str.lower().isin({'true', '1', '1.0'})]


def spreadsheet_safe(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


def build_product_catalog(sales: pd.DataFrame) -> pd.DataFrame:
    columns = ['sku', 'product_name', 'category', 'unit_price', 'active']
    if sales.empty:
        return pd.DataFrame(columns=columns)
    catalog = sales[['sku', 'product_name', 'category', 'price']].copy()
    catalog = catalog.rename(columns={'price': 'unit_price'}).drop_duplicates(subset=['sku'])
    catalog['active'] = True
    return catalog[columns].reset_index(drop=True)


def ensure_product_catalog(datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    datasets = dict(datasets)
    current = datasets.get('products', pd.DataFrame())
    history = load_product_catalog()
    sales = build_product_catalog(datasets.get('sales', pd.DataFrame()))
    datasets['products'] = pd.concat([current, history, sales], ignore_index=True).drop_duplicates(subset=['sku'], keep='first').reset_index(drop=True)
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
inventory_lock = RLock()


def serialized(function):
    """All synchronous readers/writers share one consistent in-process snapshot."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with inventory_lock:
            result = function(*args, **kwargs)
            return deepcopy(result) if isinstance(result, (dict, list)) else result
    return wrapped


def commit_datasets(datasets: dict[str, pd.DataFrame], movement: dict | None = None) -> tuple[list, list]:
    """Calculate copies, commit once, and publish only the successfully saved snapshot.

    The caller must hold inventory_lock. Upload readers await file I/O before locking.
    """
    candidate = identify_rows(ensure_product_catalog(datasets))
    recommendations, outliers = calculate_recommendations(public_datasets(candidate))
    if movement is None:
        save_datasets_draft(candidate, recommendations)
    else:
        save_inventory_movement(candidate, movement, recommendations)
    state.datasets = candidate
    state.recommendations, state.outliers = recommendations, outliers
    state.last_calculation = {}
    return recommendations, outliers


@asynccontextmanager
async def lifespan(_: FastAPI):
    with inventory_lock:
        init_db()
        restored = load_datasets_draft()
        # Empty sales is a valid saved dataset, not permission to reset the user's stock.
        commit_datasets(restored if restored is not None else build_demo_data())
    yield


app = FastAPI(title='StockPilot API', version='1.0.0', description='Explainable warehouse replenishment recommendations', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://localhost:4173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])


@app.get('/health')
def health() -> dict:
    return {'status': 'ok', 'service': 'stockpilot-api'}


@app.get('/api/data/status')
@serialized
def data_status() -> dict:
    return {'datasets': {key: len(value) for key, value in state.datasets.items()}, 'recommendations': len(state.recommendations), 'has_data': bool(len(state.datasets['sales']))}


@app.post('/api/data/demo')
@serialized
def load_demo() -> dict:
    recs, outliers = commit_datasets(build_demo_data())
    clear_editor_buffer()
    counts = {key: len(value) for key, value in state.datasets.items()}
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
    with inventory_lock:
        known_skus = set(state.datasets['sales'].get('sku', pd.Series(dtype=str)).dropna().astype(str))
        # A new imported file receives fresh identities; stale editor forms must not match it.
        cleaned, errors, warnings = validate_table(dataset, public_frame(frame), known_skus=known_skus)
        if len(cleaned) or (frame.empty and not errors):
            candidate = dict(state.datasets)
            candidate[dataset] = cleaned
            commit_datasets(candidate)
            clear_editor_buffer()
        return {
            'dataset': dataset,
            'rows_loaded': len(cleaned),
            'errors': errors,
            'warnings': warnings,
            'recommendations': len(state.recommendations),
            'outliers': len(state.outliers),
        }


@app.post('/api/data/load-ekt')
@serialized
def load_ekt() -> dict:
    candidate = AppState()
    counts = candidate.load_ekt()
    if not counts:
        raise HTTPException(status_code=404, detail='ekt.kz dataset file not found')
    recs, outliers = commit_datasets(candidate.datasets)
    clear_editor_buffer()
    return {'message': 'Real ekt.kz dataset loaded and calculated', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers)}


@app.post('/api/data/load-anomalies')
@serialized
def load_anomalies() -> dict:
    candidate = AppState()
    counts = candidate.load_anomalies()
    if not counts:
        raise HTTPException(status_code=404, detail='Extreme anomalies dataset file not found')
    recs, outliers = commit_datasets(candidate.datasets)
    clear_editor_buffer()
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
    with inventory_lock:
        recs, outliers = commit_datasets(public_datasets(datasets))
        clear_editor_buffer()
        counts = {key: len(value) for key, value in state.datasets.items()}
        return {'message': f'Workbook {file.filename} loaded successfully', 'datasets': counts, 'recommendations': len(recs), 'outliers': len(outliers), 'errors': errors, 'warnings': warnings}


@app.post('/api/data/upload-partner')
async def upload_partner(file: UploadFile = File(...), lead_time_days: int = Form(..., ge=1, le=365), as_of: date | None = Form(None)) -> dict:
    """Import an original partner archive with an explicit delivery policy."""
    from .services.partner_import import parse_partner_archive

    raw = await file.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Partner ZIP must not exceed 25 MB')
    try:
        datasets, report = parse_partner_archive(raw, file.filename or 'partner.zip', lead_time_days=lead_time_days,
                                                as_of=as_of.isoformat() if as_of else None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={'errors': [str(exc)]}) from exc
    if report.get('errors') or datasets.get('sales', pd.DataFrame()).empty:
        raise HTTPException(status_code=422, detail=report)
    with inventory_lock:
        recs, outliers = commit_datasets(public_datasets(datasets))
        clear_editor_buffer()
        counts = {key: len(frame) for key, frame in state.datasets.items()}
        return {'message': 'Partner data imported', 'datasets': counts, 'recommendations': len(recs),
                'outliers': len(outliers), 'report': report, 'errors': report.get('errors', []),
                'warnings': report.get('warnings', [])}


@app.get('/api/inventory/catalog')
@serialized
def inventory_catalog(search: str = '', limit: int | None = None, include_inactive: bool = False) -> dict:
    frame = public_frame(state.datasets['products'])
    if not include_inactive:
        frame = active_products(frame)
    if search:
        needle = search.casefold()
        frame = frame[frame.astype(str).apply(lambda col: col.str.casefold().str.contains(needle, regex=False, na=False)).any(axis=1)]
    total = len(frame)
    if limit is not None:
        frame = frame.head(min(max(limit, 1), 1000))
    return {'products': _json_safe(frame.to_dict(orient='records')), 'total': total}


@app.get('/api/inventory/stock')
@serialized
def inventory_stock(search: str = '') -> dict:
    products = state.datasets['products']
    stock = state.datasets['stock']
    transit = state.datasets['transit']
    rows: list[dict] = []
    for item in products.to_dict(orient='records'):
        sku = str(item['sku'])
        balances = stock[stock['sku'].astype(str) == sku] if not stock.empty else pd.DataFrame()
        inbound = transit[transit['sku'].astype(str) == sku] if not transit.empty else pd.DataFrame()
        warehouses = sorted(set(balances.get('warehouse', pd.Series(dtype=str)).astype(str)) |
                            set(inbound.get('warehouse', pd.Series(dtype=str)).astype(str))) or ['']
        for warehouse in warehouses:
            current = balances[balances['warehouse'].astype(str) == warehouse] if not balances.empty else pd.DataFrame()
            incoming = inbound[inbound['warehouse'].astype(str) == warehouse] if not inbound.empty else pd.DataFrame()
            rows.append({'sku': sku, 'product_name': item.get('product_name', sku),
                         'category': item.get('category', ''), 'warehouse': warehouse,
                         'current_stock': round(pd.to_numeric(current.get('current_stock', pd.Series(dtype=float)), errors='coerce').fillna(0).sum(), 2),
                         'in_transit': round(pd.to_numeric(incoming.get('quantity_in_transit', pd.Series(dtype=float)), errors='coerce').fillna(0).sum(), 2),
                         'unit_price': item.get('unit_price', 0)})
    if search:
        needle = search.casefold()
        rows = [row for row in rows if needle in f"{row['sku']} {row['product_name']} {row['warehouse']}".casefold()]
    return {'rows': _json_safe(rows), 'total': len(rows)}


@app.get('/api/inventory/movements')
@serialized
def inventory_movements(limit: int = 100) -> dict:
    rows = read_inventory_movements(min(max(limit, 1), 500))
    return {'movements': rows, 'total': len(rows)}


@app.post('/api/inventory/movements')
@serialized
def create_inventory_movement(request: MovementRequest) -> dict:
    operation = request.model_dump(mode='json')
    movement_id = operation.pop('client_request_id') or str(uuid4())
    with inventory_lock:
        existing = read_inventory_movement(movement_id)
        if existing:
            if {key: value for key, value in existing.items() if key != 'id'} != operation:
                raise HTTPException(status_code=409, detail='This request ID already belongs to a different document. Reload the saved document or create a new operation.')
            return {'movement': existing, 'recommendations': len(state.recommendations), 'replayed': True}
        operation['id'] = movement_id
        try:
            candidate = apply_movement(state.datasets, operation)
            recommendations, outliers = commit_datasets(candidate, operation)
        except (InventoryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'movement': operation, 'recommendations': len(recommendations), 'replayed': False}


@app.get('/api/inventory/export')
@serialized
def export_inventory() -> StreamingResponse:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for name in EDITOR_DATASETS:
            frame = public_frame(state.datasets[name]).copy()
            frame = frame.map(spreadsheet_safe)
            frame.to_excel(writer, index=False, sheet_name=name)
        movements = read_inventory_movements(None)
        pd.DataFrame([{'id': item['id'], 'type': item['kind'], 'date': item['date'],
                       'warehouse': item['warehouse'], 'destination': item.get('destination_warehouse'),
                       'partner': item.get('partner'), 'reference': item.get('reference'),
                       'sku': line['sku'], 'quantity': line['quantity'], 'unit_price': line['unit_price']}
                      for item in movements for line in item['lines']]).map(spreadsheet_safe).to_excel(writer, index=False, sheet_name='movements')
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             headers={'Content-Disposition': 'attachment; filename=stockpilot-current.xlsx'})


def _require_editor_dataset(dataset: str) -> None:
    if dataset not in EDITOR_DATASETS:
        raise HTTPException(status_code=404, detail=f'Unknown editor dataset: {dataset}')


def _editor_frame(dataset: str, rows: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame(rows)
    if 'row_id' in frame.columns:
        frame = frame.drop(columns=['row_id'])
    identities = frame[ROW_ID].copy() if ROW_ID in frame else None
    frame = public_frame(frame)
    known_warehouses = set(state.datasets['stock'].get('warehouse', pd.Series(dtype=str)).dropna().astype(str))
    known_skus = set(state.datasets['sales'].get('sku', pd.Series(dtype=str)).dropna().astype(str))
    cleaned, errors, warnings = validate_table(dataset, frame, known_warehouses, known_skus)
    if errors or len(cleaned) != len(frame):
        raise HTTPException(status_code=400, detail={'message': 'Row validation failed', 'errors': errors, 'warnings': warnings})
    if identities is not None:
        cleaned[ROW_ID] = identities.loc[cleaned.index]
    return cleaned.reset_index(drop=True), warnings


def _recalculate_editor_state(dataset: str, frame: pd.DataFrame, warnings: list[str] | None = None) -> dict:
    candidate = dict(state.datasets)
    candidate[dataset] = frame.reset_index(drop=True)
    commit_datasets(candidate)
    return {
        'dataset': dataset,
        'rows': len(state.datasets[dataset]),
        'recommendations': len(state.recommendations),
        'outliers': len(state.outliers),
        'warnings': warnings or [],
    }


@app.get('/api/editor/state')
@serialized
def editor_state() -> dict:
    return {
        'datasets': {name: len(state.datasets.get(name, pd.DataFrame())) for name in EDITOR_DATASETS},
        'draft': read_editor_buffer(),
        'updated_at': draft_updated_at(),
    }


@app.get('/api/editor/draft')
@serialized
def get_editor_draft() -> dict:
    return {'draft': read_editor_buffer(), 'updated_at': draft_updated_at()}


@app.post('/api/editor/draft')
@serialized
def save_editor_draft(payload: EditorDraftPayload) -> dict:
    _require_editor_dataset(payload.dataset)
    save_editor_buffer(payload.dataset, payload.row, payload.row_id)
    return {'saved': True, 'draft': read_editor_buffer(), 'updated_at': draft_updated_at()}


@app.delete('/api/editor/draft')
@serialized
def delete_editor_draft() -> dict:
    clear_editor_buffer()
    return {'deleted': True}


@app.get('/api/editor/{dataset}')
@serialized
def editor_rows(dataset: str, offset: int = 0, limit: int = 50, search: str | None = None) -> dict:
    _require_editor_dataset(dataset)
    offset = max(offset, 0)
    limit = min(max(limit, 1), 200)
    frame = state.datasets.get(dataset, pd.DataFrame())
    if dataset == 'products':
        frame = active_products(frame)
    if search:
        needle = search.lower()
        mask = public_frame(frame).astype(str).apply(lambda column: column.str.lower().str.contains(needle, regex=False, na=False)).any(axis=1)
        frame = frame.loc[mask]
    total = len(frame)
    rows = []
    for index, row in frame.iloc[offset:offset + limit].iterrows():
        rows.append({'row_id': int(row[ROW_ID]), **_json_safe(row.drop(labels=[ROW_ID], errors='ignore').to_dict())})
    return {'dataset': dataset, 'columns': list(public_frame(state.datasets[dataset]).columns), 'rows': rows, 'total': total, 'offset': offset, 'limit': limit, 'draft': read_editor_buffer()}


@app.get('/api/editor/{dataset}/export')
@serialized
def export_editor_dataset(dataset: str, format: str = 'xlsx') -> StreamingResponse:
    _require_editor_dataset(dataset)
    normalized_format = format.lower()
    if normalized_format not in {'csv', 'xlsx'}:
        raise HTTPException(status_code=400, detail="Export format must be 'csv' or 'xlsx'")
    frame = public_frame(state.datasets[dataset]).map(spreadsheet_safe)
    filename = f'stockpilot-{dataset}'
    if normalized_format == 'xlsx':
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment; filename={filename}.xlsx'})
    content = frame.to_csv(index=False).encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(content), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}.csv'})


@app.post('/api/editor/{dataset}/rows')
@serialized
def create_editor_row(dataset: str, payload: EditorRowPayload) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    row = {key: value for key, value in payload.row.items() if key != 'row_id' and not key.startswith('__')}
    if dataset == 'products' and 'sku' in current and (current['sku'].astype(str) == str(row.get('sku', ''))).any():
        raise HTTPException(status_code=409, detail='This SKU already exists, including archived catalog entries.')
    candidate = pd.concat([current, pd.DataFrame([row])], ignore_index=True)
    cleaned, warnings = _editor_frame(dataset, candidate.to_dict(orient='records'))
    result = _recalculate_editor_state(dataset, cleaned, warnings)
    clear_editor_buffer()
    return result


@app.patch('/api/editor/{dataset}/rows/{row_id}')
@serialized
def update_editor_row(dataset: str, row_id: int, payload: EditorRowPayload) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    matching = current.index[current[ROW_ID] == row_id] if ROW_ID in current else []
    if not len(matching) or (dataset == 'products' and matching[0] not in active_products(current).index):
        raise HTTPException(status_code=404, detail='Editor row not found')
    previous = current.loc[matching[0]].copy()
    for column, value in payload.row.items():
        if column in current.columns and not column.startswith('__'):
            current.at[matching[0], column] = value
    if dataset == 'stock' and 'current_stock' in payload.row and 'balance_is_stale' in current:
        current.at[matching[0], 'balance_is_stale'] = False
        if 'balance_unknown' in current:
            current.at[matching[0], 'balance_unknown'] = False
        if 'source_warning' in current:
            current.at[matching[0], 'source_warning'] = ''
        if 'balance_date' in current:
            current.at[matching[0], 'balance_date'] = resolve_as_of(public_datasets(state.datasets)).isoformat()
    cleaned, warnings = _editor_frame(dataset, current.to_dict(orient='records'))
    if dataset == 'suppliers':
        # Editing another policy must not confirm the adapter's zero-price/one-pack placeholders.
        for field, flag in [('unit_cost', 'cost_unknown'), ('package_size', 'package_unknown')]:
            if field in payload.row and field in cleaned and flag in cleaned:
                value = cleaned.at[matching[0], field]
                if pd.notna(value) and value > 0 and value != previous.get(field):
                    cleaned.at[matching[0], flag] = False
    result = _recalculate_editor_state(dataset, cleaned, warnings)
    clear_editor_buffer()
    return result


@app.delete('/api/editor/{dataset}/rows/{row_id}')
@serialized
def delete_editor_row(dataset: str, row_id: int) -> dict:
    _require_editor_dataset(dataset)
    current = state.datasets.get(dataset, pd.DataFrame()).copy()
    matching = current.index[current[ROW_ID] == row_id] if ROW_ID in current else []
    if not len(matching):
        raise HTTPException(status_code=404, detail='Editor row not found')
    if dataset == 'products':
        if matching[0] not in active_products(current).index:
            raise HTTPException(status_code=404, detail='Editor row not found')
        current.at[matching[0], 'active'] = False
    else:
        current = current.drop(index=matching[0]).reset_index(drop=True)
    result = _recalculate_editor_state(dataset, current) if current.empty else _recalculate_editor_state(dataset, _editor_frame(dataset, current.to_dict(orient='records'))[0])
    clear_editor_buffer()
    return result


@app.post('/api/recommendations/calculate')
@serialized
def calculate(request: CalculateRequest = CalculateRequest()) -> dict:
    recommendations, outliers = calculate_recommendations(public_datasets(state.datasets), request.warehouse, request.category, request.safety_days, request.service_factor, request.outlier_threshold)
    save_recommendations(recommendations)
    state.recommendations = recommendations
    state.outliers = outliers
    state.last_calculation = request.model_dump()
    return {'count': len(recommendations), 'outliers': len(outliers), 'recommendations': _json_safe(recommendations)}


@app.get('/api/recommendations')
@serialized
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
@serialized
def get_recommendation(order_id: str) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    return row


@app.get('/api/analytics/{sku}')
@serialized
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
    options = {**state.last_calculation, **(rec.get('metadata', {}) if rec else {})}
    prepared, _ = prepare_demand(public_datasets(state.datasets), wh, outlier_threshold=options.get('outlier_threshold', 3.5), as_of=rec.get('metadata', {}).get('as_of') if rec else None)
    daily = prepared[prepared['sku'].astype(str) == sku].sort_values('date')
    points = [{'date': item.date.strftime('%Y-%m-%d'), 'actual_sales': round(float(item.actual_sales), 2), 'adjusted_demand': round(float(item.adjusted_demand), 2), 'is_outlier': bool(item.is_outlier), 'is_stockout': bool(item.is_stockout)} for item in daily.itertuples()]
    if rec:
        forecast_start = pd.to_datetime(daily['date'].max()) + pd.Timedelta(days=1)
        forecast, _ = forecast_series(daily, rec['lead_time_days'] + options.get('safety_days', 7), options.get('safety_days', 7))
        for day, value in enumerate(forecast):
            points.append({'date': (forecast_start + pd.Timedelta(days=day)).strftime('%Y-%m-%d'), 'actual_sales': None, 'adjusted_demand': None, 'forecast': round(max(value, 0), 2)})
    return {'sku': sku, 'warehouse': wh, 'product_name': str(row['product_name'].iloc[0]), 'points': points, 'recommendation': rec, 'outliers': [item for item in state.outliers if item['sku'] == sku and (not warehouse or item['warehouse'] == warehouse)]}


@app.get('/api/outliers')
@serialized
def outliers() -> dict:
    return {'outliers': state.outliers, 'count': len(state.outliers)}


@app.post('/api/orders/{order_id}/adjust')
@serialized
def adjust_order(order_id: str, request: AdjustOrderRequest) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    update_order(order_id, status='ADJUSTED', final_quantity=request.final_quantity)
    row['final_quantity'] = request.final_quantity
    row['total_cost_kzt'] = round(request.final_quantity * row['unit_cost'], 2)
    row['status'] = 'ADJUSTED'
    return row


@app.get('/api/orders/history')
@serialized
def order_history() -> dict:
    return {'orders': read_order_history()}


@app.post('/api/orders/{order_id}/approve')
@serialized
def approve_order(order_id: str) -> dict:
    row = next((item for item in state.recommendations if item['id'] == order_id), None)
    if not row:
        raise HTTPException(status_code=404, detail='Recommendation not found')
    if row.get('metadata', {}).get('balance_is_stale'):
        raise HTTPException(status_code=422, detail='Обновите остаток на дату расчёта в справочнике «Остатки». Утверждение по устаревшему месячному снимку недоступно.')
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
    update_order(order_id, status='APPROVED')
    row['status'] = 'APPROVED'
    return row


@app.get('/api/orders/export')
@serialized
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
    cutoff = resolve_as_of(public_datasets(state.datasets))
    data_as_of = cutoff.strftime('%Y-%m-%d') if cutoff is not None and pd.notna(cutoff) else None
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
