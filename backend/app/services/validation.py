from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import numpy as np


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "products": {"sku", "product_name", "category"},
    "sales": {"date", "sku", "product_name", "quantity", "price", "customer_id", "warehouse", "category"},
    "stock": {"sku", "warehouse", "current_stock"},
    "transit": {"sku", "warehouse", "quantity_in_transit", "expected_arrival_date"},
    "stockouts": {"sku", "warehouse", "start_date", "end_date"},
    "suppliers": {"supplier_id", "supplier_name", "sku", "lead_time_days"},
}

COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "products": {
        "sku": ["sku", "артикул", "код", "код_товара", "код товара", "item_code"],
        "product_name": ["product_name", "наименование_товара", "наименование", "наименование товара", "номенклатура", "товар", "name"],
        "category": ["category", "категория", "товарная_группа", "товарная группа", "группа"],
        "unit_price": ["unit_price", "цена", "цена_за_ед_kzt", "цена_kzt", "price"],
        "active": ["active", "активен", "активный"],
    },
    "sales": {
        "date": ["date", "дата", "дата_продажи", "дата продажи", "период", "sale_date"],
        "sku": ["sku", "артикул", "код", "код_товара", "код товара", "item_code"],
        "product_name": ["product_name", "наименование_товара", "наименование", "наименование товара", "номенклатура", "товар", "name"],
        "quantity": ["quantity", "количество", "кол-во", "кол_во", "объем", "qty"],
        "price": ["price", "цена", "цена_за_ед_kzt", "цена_kzt", "цена за ед", "стоимость"],
        "customer_id": ["customer_id", "id_клиента", "id клиента", "клиент", "контрагент", "client_id"],
        "warehouse": ["warehouse", "склад", "склад_отгрузки", "склад отгрузки", "филиал"],
        "category": ["category", "категория", "товарная_группа", "товарная группа", "группа"],
        "transaction_type": ["transaction_type", "тип_транзакции", "тип транзакции", "operation_type"],
    },
    "stock": {
        "sku": ["sku", "артикул", "код", "код_товара"],
        "warehouse": ["warehouse", "склад", "склад_хранения"],
        "current_stock": ["current_stock", "доступный_остаток", "остаток", "текущий_остаток", "stock", "qty_on_hand"],
        "physical_stock": ["physical_stock", "физический_остаток", "факт_остаток"],
        "reserved": ["reserved", "зарезервировано", "резерв"],
    },
    "transit": {
        "sku": ["sku", "артикул", "код", "код_товара"],
        "warehouse": ["warehouse", "склад"],
        "quantity_in_transit": ["quantity_in_transit", "товар_в_пути", "в_пути", "в пути", "in_transit", "transit_qty"],
        "expected_arrival_date": ["expected_arrival_date", "ожидаемая_дата_поставки", "дата_поставки", "срок_поставки", "arrival_date", "eta"],
    },
    "stockouts": {
        "sku": ["sku", "артикул", "код"],
        "warehouse": ["warehouse", "склад"],
        "start_date": ["start_date", "дата_начала_дефицита", "начало", "дата_начала", "out_start"],
        "end_date": ["end_date", "дата_окончания_дефицита", "конец", "дата_окончания", "out_end"],
    },
    "suppliers": {
        "supplier_id": ["supplier_id", "id_поставщика", "код_поставщика", "поставщик", "vendor_id"],
        "supplier_name": ["supplier_name", "поставщик", "наименование_поставщика", "vendor_name", "компания"],
        "sku": ["sku", "артикул", "код", "код_товара"],
        "lead_time_days": ["lead_time_days", "срок_поставки_leadtime_дней", "срок_поставки", "срок_поставки_дней", "lead_time", "leadtime"],
        "moq": ["moq", "минимальная_партия_moq", "минимальная_партия", "мин_партия"],
        "package_size": ["package_size", "кратность_упаковки_pack", "кратность_упаковки", "кратность", "пачка", "pack_size", "квант"],
        "unit_cost": ["unit_cost", "базовая_закупочная_цена_kzt", "закупочная_цена", "цена_закупки", "себестоимость", "cost", "price"],
        "minimum_order_value": ["minimum_order_value", "минимальная_сумма_заказа", "минимальная_сумма_заказа_kzt"],
    },
}


def read_table(raw: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(raw))
    return pd.read_csv(BytesIO(raw))


def normalize_columns(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    raw_cols = {str(c).strip().lower(): c for c in frame.columns}
    aliases = COLUMN_ALIASES.get(dataset, {})
    
    rename_map = {}
    for target_col, variants in aliases.items():
        if target_col in frame.columns:
            continue
        for variant in variants:
            v_clean = variant.strip().lower()
            if v_clean in raw_cols:
                rename_map[raw_cols[v_clean]] = target_col
                break
                
    if rename_map:
        frame = frame.rename(columns=rename_map)
        
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    
    # Aliases have already been normalized. An explicit available balance wins;
    # otherwise derive it from physical stock, preserving invalid values for validation.
    if dataset == "stock" and "current_stock" not in frame and "physical_stock" in frame:
        physical = pd.to_numeric(frame["physical_stock"], errors="coerce")
        reserved = pd.to_numeric(frame["reserved"], errors="coerce") if "reserved" in frame else 0
        frame["current_stock"] = (physical - reserved).clip(lower=0)
                
    # Specific fallback for supplier_id if only supplier_name is present
    if dataset == "suppliers":
        if "supplier_id" not in frame.columns and "supplier_name" in frame.columns:
            frame["supplier_id"] = frame["supplier_name"]
            
    return frame


def validate_table(dataset: str, frame: pd.DataFrame, known_warehouses: set[str] | None = None, known_skus: set[str] | None = None) -> tuple[pd.DataFrame, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = REQUIRED_COLUMNS[dataset]
    
    frame = normalize_columns(dataset, frame)
    missing = sorted(required - set(frame.columns))
    if missing:
        errors.append(f"{dataset}: missing required column(s): {', '.join(missing)}")
        return frame.iloc[0:0], errors, warnings
        
    if frame.duplicated().any():
        warnings.append(f"{dataset}: {int(frame.duplicated().sum())} duplicate row(s) ignored")
        frame = frame.drop_duplicates()
    invalid_rows = pd.Series(False, index=frame.index)
    date_columns = {"date", "expected_arrival_date", "start_date", "end_date", "as_of", "snapshot_date", "balance_date"}
    for col in date_columns.intersection(frame.columns):
        parsed = pd.to_datetime(frame[col], errors="coerce")
        bad_mask = parsed.isna()
        if dataset == "transit" and col == "expected_arrival_date" and "arrival_date_unknown" in frame:
            explicitly_unknown = frame["arrival_date_unknown"].astype(str).str.lower().isin(["true", "1"])
            missing_date = frame[col].isna() | frame[col].astype(str).str.strip().eq("")
            unknown = explicitly_unknown & missing_date
            bad_mask &= ~unknown
            if unknown.any():
                warnings.append(f"transit: {int(unknown.sum())} arrival date(s) unknown; excluded from timely replenishment coverage")
        bad = int(bad_mask.sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} invalid date value(s)")
            invalid_rows |= bad_mask
        frame[col] = parsed
        
    numeric_cols = {"quantity", "price", "unit_price", "current_stock", "physical_stock", "reserved", "quantity_in_transit", "lead_time_days", "moq", "package_size", "unit_cost", "minimum_order_value"}
    for col in numeric_cols.intersection(frame.columns):
        values = pd.to_numeric(frame[col], errors="coerce")
        bad_mask = ~np.isfinite(values)
        bad = int(bad_mask.sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} non-finite or non-numeric value(s)")
            invalid_rows |= bad_mask
        frame[col] = values
        
    if "sku" in frame:
        missing_sku = int(frame["sku"].isna().sum() + (frame["sku"].astype(str).str.strip() == "").sum())
        if missing_sku:
            errors.append(f"{dataset}.sku: {missing_sku} missing SKU value(s)")
            invalid_rows |= frame["sku"].isna() | (frame["sku"].astype(str).str.strip() == "")
    if "warehouse" in frame:
        missing_warehouse = int(frame["warehouse"].isna().sum() + (frame["warehouse"].astype(str).str.strip() == "").sum())
        if missing_warehouse:
            errors.append(f"{dataset}.warehouse: {missing_warehouse} missing warehouse value(s)")
            invalid_rows |= frame["warehouse"].isna() | (frame["warehouse"].astype(str).str.strip() == "")
    for col in numeric_cols:
        if col in frame:
            values = pd.to_numeric(frame[col], errors="coerce")
            negative_mask = values < 0
            if dataset == "sales" and col == "quantity" and "transaction_type" in frame:
                is_return = frame["transaction_type"].astype(str).str.contains("сторно|возврат|return|credit", case=False, regex=True)
                negative_mask &= ~is_return
            negative = int(negative_mask.sum())
            if negative:
                errors.append(f"{dataset}.{col}: {negative} negative value(s) are not allowed")
                invalid_rows |= negative_mask
    if dataset != "stock" and known_warehouses and "warehouse" in frame:
        unknown = sorted(set(frame.loc[~frame["warehouse"].isin(known_warehouses), "warehouse"].dropna().astype(str)))
        if unknown:
            errors.append(f"{dataset}.warehouse: unknown warehouse(s): {', '.join(unknown)}")
            invalid_rows |= ~frame["warehouse"].isin(known_warehouses)
    if known_skus and dataset in {"stock", "transit", "stockouts", "suppliers"}:
        unknown_skus = sorted(set(frame.loc[~frame["sku"].astype(str).isin(known_skus), "sku"].dropna().astype(str)))
        if unknown_skus:
            warnings.append(f"{dataset}.sku: SKU(s) not present in sales history: {', '.join(unknown_skus[:10])}")
    if dataset == "suppliers":
        invalid = int((pd.to_numeric(frame["lead_time_days"], errors="coerce") <= 0).sum())
        if invalid:
            errors.append(f"suppliers.lead_time_days: {invalid} value(s) must be greater than zero")
            invalid_rows |= pd.to_numeric(frame["lead_time_days"], errors="coerce") <= 0
        if "package_size" in frame:
            invalid_package = frame["package_size"] <= 0
            if invalid_package.any():
                errors.append(f"suppliers.package_size: {int(invalid_package.sum())} value(s) must be greater than zero")
                invalid_rows |= invalid_package
        duplicate_keys = int(frame.duplicated(subset=["supplier_id", "sku"]).sum())
        if duplicate_keys:
            warnings.append(f"suppliers: {duplicate_keys} duplicate supplier/SKU mapping(s) ignored")
            frame = frame.drop_duplicates(subset=["supplier_id", "sku"])
    if dataset == "stock":
        duplicate_keys = frame.duplicated(subset=["sku", "warehouse"], keep=False)
        if duplicate_keys.any():
            errors.append(f"stock: {int(duplicate_keys.sum())} conflicting SKU/warehouse balance(s)")
            invalid_rows |= duplicate_keys
    if dataset == "stockouts":
        reversed_dates = frame["start_date"] > frame["end_date"]
        if reversed_dates.any():
            errors.append(f"stockouts: {int(reversed_dates.sum())} reversed date interval(s)")
            invalid_rows |= reversed_dates
    # Keep valid rows so one malformed record does not discard the full upload.
    if invalid_rows.any():
        frame = frame.loc[~invalid_rows].copy()
    return frame, errors, warnings


def parse_workbook(raw: bytes, include_report: bool = False) -> dict[str, pd.DataFrame] | tuple[dict[str, pd.DataFrame], list[str], list[str]]:
    """Read normalized workbooks, including every dataset of our own export.

    Explicit transit sheets take precedence over embedded stock/inbound columns.
    Unknown dates stay unknown; importing a file must never invent a delivery.
    """
    errors: list[str] = []
    warnings: list[str] = []
    parts: dict[str, list[pd.DataFrame]] = {key: [] for key in REQUIRED_COLUMNS}
    embedded_transit: list[pd.DataFrame] = []

    def kind(name: str) -> str | None:
        name = name.strip().lower()
        if name in REQUIRED_COLUMNS:
            return name
        for key, fragments in (
            ("stockouts", ("дефицит", "stockout")),
            ("transit", ("transit", "пути", "inbound")),
            ("suppliers", ("поставщик", "supplier")),
            ("sales", ("продаж", "sale")),
            ("products", ("product", "каталог", "номенклатур")),
            ("stock", ("остатк", "stock")),
        ):
            if any(fragment in name for fragment in fragments):
                return key
        return None

    with pd.ExcelFile(BytesIO(raw)) as workbook:
        for sheet in workbook.sheet_names:
            dataset = kind(sheet)
            if dataset is None:
                if sheet.lower() == "movements":
                    warnings.append("movements: journal is informational; importing balances does not replay warehouse operations")
                else:
                    warnings.append(f"{sheet}: unrecognized sheet; use a normalized template or the partner archive importer")
                continue
            frame = workbook.parse(sheet)
            if frame.empty and not len(frame.columns):
                continue
            parts[dataset].append(frame)
            if dataset == "stock":
                transit = normalize_columns("transit", frame)
                if "quantity_in_transit" in transit:
                    transit = transit.loc[pd.to_numeric(transit["quantity_in_transit"], errors="coerce").fillna(0) > 0].copy()
                    if not transit.empty:
                        if "expected_arrival_date" not in transit:
                            transit["expected_arrival_date"] = pd.NaT
                        missing = transit["expected_arrival_date"].isna() | transit["expected_arrival_date"].astype(str).str.strip().eq("")
                        transit["arrival_date_unknown"] = missing
                        embedded_transit.append(transit)
    if not parts["transit"]:
        parts["transit"] = embedded_transit

    datasets: dict[str, pd.DataFrame] = {}
    for dataset, frames in parts.items():
        if not frames:
            datasets[dataset] = pd.DataFrame(columns=sorted(REQUIRED_COLUMNS[dataset]))
            continue
        normalized = pd.concat([normalize_columns(dataset, frame) for frame in frames], ignore_index=True)
        cleaned, table_errors, table_warnings = validate_table(dataset, normalized)
        datasets[dataset] = cleaned
        errors.extend(table_errors)
        warnings.extend(table_warnings)
    if include_report:
        return datasets, errors, warnings
    return datasets
