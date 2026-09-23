from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "sales": {"date", "sku", "product_name", "quantity", "price", "customer_id", "warehouse", "category"},
    "stock": {"sku", "warehouse", "current_stock"},
    "transit": {"sku", "warehouse", "quantity_in_transit", "expected_arrival_date"},
    "stockouts": {"sku", "warehouse", "start_date", "end_date"},
    "suppliers": {"supplier_id", "supplier_name", "sku", "lead_time_days"},
}


def read_table(raw: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(('.xlsx', '.xls')):
        return pd.read_excel(BytesIO(raw))
    return pd.read_csv(BytesIO(raw))


def validate_table(dataset: str, frame: pd.DataFrame, known_warehouses: set[str] | None = None) -> tuple[pd.DataFrame, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = REQUIRED_COLUMNS[dataset]
    frame = frame.copy()
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = sorted(required - set(frame.columns))
    if missing:
        errors.append(f"{dataset}: missing required column(s): {', '.join(missing)}")
        return frame.iloc[0:0], errors, warnings
    if frame.duplicated().any():
        warnings.append(f"{dataset}: {int(frame.duplicated().sum())} duplicate row(s) ignored")
        frame = frame.drop_duplicates()
    for col in [c for c in frame.columns if 'date' in c or c.endswith('_date') or c in {'start_date', 'end_date'}]:
        parsed = pd.to_datetime(frame[col], errors='coerce')
        bad = int(parsed.isna().sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} invalid date value(s)")
        frame[col] = parsed
    numeric_cols = {'quantity', 'price', 'current_stock', 'quantity_in_transit', 'lead_time_days', 'moq', 'package_size', 'minimum_order_value'}
    for col in numeric_cols.intersection(frame.columns):
        values = pd.to_numeric(frame[col], errors='coerce')
        bad = int(values.isna().sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} non-numeric value(s)")
        frame[col] = values
    if 'sku' in frame:
        missing_sku = int(frame['sku'].isna().sum() + (frame['sku'].astype(str).str.strip() == '').sum())
        if missing_sku:
            errors.append(f"{dataset}.sku: {missing_sku} missing SKU value(s)")
    for col in ['current_stock', 'quantity_in_transit', 'quantity', 'lead_time_days', 'moq', 'package_size']:
        if col in frame:
            negative = int((pd.to_numeric(frame[col], errors='coerce') < 0).sum())
            if negative:
                errors.append(f"{dataset}.{col}: {negative} negative value(s) are not allowed")
    if dataset == 'stock' and known_warehouses:
        unknown = sorted(set(frame.loc[~frame['warehouse'].isin(known_warehouses), 'warehouse'].dropna().astype(str)))
        if unknown:
            warnings.append(f"{dataset}.warehouse: unknown warehouse(s): {', '.join(unknown)}")
    if dataset == 'suppliers':
        invalid = int((pd.to_numeric(frame['lead_time_days'], errors='coerce') <= 0).sum())
        if invalid:
            errors.append(f"suppliers.lead_time_days: {invalid} value(s) must be greater than zero")
    if errors:
        # Keep valid rows so one malformed record does not discard the full upload.
        frame = frame.dropna(subset=['sku'])
    return frame, errors, warnings
