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

COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "sales": {
        "date": ["date", "дата", "дата_продажи", "дата продажи", "период", "sale_date"],
        "sku": ["sku", "артикул", "код", "код_товара", "код товара", "item_code"],
        "product_name": ["product_name", "наименование_товара", "наименование", "наименование товара", "номенклатура", "товар", "name"],
        "quantity": ["quantity", "количество", "кол-во", "кол_во", "объем", "qty"],
        "price": ["price", "цена", "цена_за_ед_kzt", "цена_kzt", "цена за ед", "стоимость"],
        "customer_id": ["customer_id", "id_клиента", "id клиента", "клиент", "контрагент", "client_id"],
        "warehouse": ["warehouse", "склад", "склад_отгрузки", "склад отгрузки", "филиал"],
        "category": ["category", "категория", "товарная_группа", "товарная группа", "группа"],
    },
    "stock": {
        "sku": ["sku", "артикул", "код", "код_товара"],
        "warehouse": ["warehouse", "склад", "склад_хранения"],
        "current_stock": ["current_stock", "доступный_остаток", "физический_остаток", "остаток", "текущий_остаток", "stock", "qty_on_hand"],
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
    
    # Specific logic for stock when physical and reserved are present
    if dataset == "stock":
        if "current_stock" not in frame.columns:
            if "доступный_остаток" in frame.columns:
                frame["current_stock"] = frame["доступный_остаток"]
            elif "физический_остаток" in frame.columns:
                physical = pd.to_numeric(frame["физический_остаток"], errors="coerce").fillna(0)
                reserved = pd.to_numeric(frame.get("зарезервировано", 0), errors="coerce").fillna(0)
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
    for col in [c for c in frame.columns if "date" in c or c.endswith("_date") or c in {"start_date", "end_date"}]:
        parsed = pd.to_datetime(frame[col], errors="coerce")
        bad = int(parsed.isna().sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} invalid date value(s)")
            invalid_rows |= parsed.isna()
        frame[col] = parsed
        
    numeric_cols = {"quantity", "price", "current_stock", "quantity_in_transit", "lead_time_days", "moq", "package_size", "unit_cost", "minimum_order_value"}
    for col in numeric_cols.intersection(frame.columns):
        values = pd.to_numeric(frame[col], errors="coerce")
        bad = int(values.isna().sum())
        if bad:
            errors.append(f"{dataset}.{col}: {bad} non-numeric value(s)")
            invalid_rows |= values.isna()
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
    for col in ["current_stock", "quantity_in_transit", "quantity", "lead_time_days", "moq", "package_size"]:
        if col in frame:
            values = pd.to_numeric(frame[col], errors="coerce")
            negative_mask = values < 0
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
        duplicate_keys = int(frame.duplicated(subset=["supplier_id", "sku"]).sum())
        if duplicate_keys:
            warnings.append(f"suppliers: {duplicate_keys} duplicate supplier/SKU mapping(s) ignored")
            frame = frame.drop_duplicates(subset=["supplier_id", "sku"])
    # Keep valid rows so one malformed record does not discard the full upload.
    if invalid_rows.any():
        frame = frame.loc[~invalid_rows].copy()
    return frame, errors, warnings


def parse_workbook(raw: bytes) -> dict[str, pd.DataFrame]:
    """
    Parses a multi-sheet Excel workbook (such as ekt_sales_and_stock_history.xlsx).
    Automatically maps known sheet names to standard datasets and extracts:
    - sales
    - stock
    - transit
    - suppliers
    - stockouts
    """
    excel_file = pd.ExcelFile(BytesIO(raw))
    sheet_names = excel_file.sheet_names
    
    datasets: dict[str, pd.DataFrame] = {}
    
    # Mapping sheet names
    for sheet in sheet_names:
        sheet_lower = sheet.lower()
        if "продаж" in sheet_lower or "sale" in sheet_lower:
            df = excel_file.parse(sheet)
            cleaned, _, _ = validate_table("sales", df)
            datasets["sales"] = cleaned
        elif "дефицит" in sheet_lower or "stockout" in sheet_lower:
            df = excel_file.parse(sheet)
            cleaned, _, _ = validate_table("stockouts", df)
            datasets["stockouts"] = cleaned
        elif "поставщик" in sheet_lower or "supplier" in sheet_lower:
            df = excel_file.parse(sheet)
            cleaned, _, _ = validate_table("suppliers", df)
            datasets["suppliers"] = cleaned
        elif "остатк" in sheet_lower or "stock" in sheet_lower or "пути" in sheet_lower:
            df = excel_file.parse(sheet)
            # This sheet usually contains both stock and transit columns
            cleaned_stock, _, _ = validate_table("stock", df)
            datasets["stock"] = cleaned_stock
            
            # Extract transit if present in this sheet
            df_norm = normalize_columns("transit", df)
            if "quantity_in_transit" in df_norm.columns:
                transit_df = df_norm[pd.to_numeric(df_norm["quantity_in_transit"], errors="coerce") > 0].copy()
                if not transit_df.empty:
                    if "expected_arrival_date" not in transit_df.columns:
                        transit_df["expected_arrival_date"] = pd.Timestamp.now() + pd.Timedelta(days=7)
                    cleaned_transit, _, _ = validate_table("transit", transit_df)
                    datasets["transit"] = cleaned_transit
                    
    # Fill any missing empty DataFrames
    for key in ["sales", "stock", "transit", "stockouts", "suppliers"]:
        if key not in datasets:
            datasets[key] = pd.DataFrame()
            
    return datasets
