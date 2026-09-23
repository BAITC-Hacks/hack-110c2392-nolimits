"""Explicit adapters for the six-workbook Systeme Electric and IEK archives.

Unknown commercial facts are flagged, not manufactured. Monthly opening stock
is retained with its real date and blocks approval until a current balance is supplied.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import math
import re
import zipfile

import pandas as pd
from openpyxl import load_workbook

from .validation import REQUIRED_COLUMNS, validate_table

MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
          "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _name(value: str) -> str:
    try:
        return value.encode("cp437").decode("cp866")
    except UnicodeError:
        return value


def _number(value, default=0.0) -> float:
    if _text(value) == "":
        return default
    try:
        result = float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
        if not math.isfinite(result):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError(f"Expected a finite numeric cell, received {_text(value)[:40]!r}") from None


def _month(value):
    match = re.search(r"([а-яё]+)\.?\s+(20\d{2})", _text(value).lower())
    if not match or match[1][:3] not in MONTHS:
        return None
    return pd.Timestamp(year=int(match[2]), month=MONTHS[match[1][:3]], day=1)


def _column(headers, *aliases):
    choices = {alias.lower() for alias in aliases}
    return next((i for i, value in enumerate(headers) if _text(value).lower() in choices), None)


def _cell(row, index):
    return row[index] if index is not None and index < len(row) else None


def _table(raw: bytes):
    # Check the inner XLSX expansion too; a tiny outer ZIP can contain a huge XML.
    with zipfile.ZipFile(BytesIO(raw)) as inner:
        if sum(item.file_size for item in inner.infolist()) > 300 * 1024 * 1024:
            raise ValueError("Excel expansion exceeds 300 MB")
    book = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    try:
        sheet = book.active
        if (sheet.max_row or 0) > 350_000 or (sheet.max_column or 0) > 150:
            raise ValueError("Excel dimensions exceed the partner import limit")
        rows = list(sheet.iter_rows(values_only=True))
        for index, row in enumerate(rows[:15]):
            if _column(row, "Код", "Код 1с", "Номенклатура.Код") is not None:
                return list(row), rows[index + 1:]
        # Seasonality is a reference sheet, not a second source of sales.
        return [], rows
    finally:
        book.close()


def _kind(name):
    name = name.lower()
    if "динамика" in name:
        return "sales"
    if "moq" in name:
        return "policies"
    if "остатк" in name:
        return "monthly_stock"
    if "ежемесяч" in name and "продаж" in name:
        return "monthly_sales"
    if "сезон" in name:
        return "seasonality"
    if "пути" in name or "путь" in name:
        return "inbound"
    return None


def parse_partner_archive(raw: bytes, filename: str, lead_time_days: int, as_of=None):
    report = {"errors": [], "warnings": [], "files": [], "metrics": {}, "source": "partner_original"}
    empty = {name: pd.DataFrame(columns=sorted(columns)) for name, columns in REQUIRED_COLUMNS.items()}
    if not filename.lower().endswith(".zip") or len(raw) > 25 * 1024 * 1024:
        report["errors"].append("Upload a partner ZIP archive no larger than 25 MB")
        return empty, report
    if not 1 <= lead_time_days <= 365:
        report["errors"].append("A supplier lead time between 1 and 365 days must be supplied explicitly")
        return empty, report
    tables = {}
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > 20 or sum(item.file_size for item in members) > 100 * 1024 * 1024:
                raise ValueError("Archive exceeds 20 files or 100 MB expanded size")
            names = [_name(item.filename) for item in members]
            brand = "Systeme Electric" if any("system" in name.lower() for name in names) else "IEK" if any("iek" in name.lower() or "иэк" in name.lower() for name in names) else None
            if brand is None:
                raise ValueError("Only the supplied Systeme Electric and IEK archive layouts are supported")
            for item, name in zip(members, names):
                path = PurePosixPath(name.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or item.flag_bits & 1:
                    raise ValueError("Unsafe or encrypted archive entry")
                kind = _kind(name)
                if not name.lower().endswith(".xlsx") or kind is None:
                    report["warnings"].append(f"Ignored unsupported file: {path.name}")
                    continue
                if kind in tables:
                    raise ValueError(f"More than one {kind} workbook; upload one supplier archive at a time")
                headers, rows = _table(archive.read(item))
                tables[kind] = (headers, rows)
                report["files"].append({"name": path.name, "kind": kind, "rows": sum(any(value is not None for value in row) for row in rows)})
            if "sales" not in tables or "monthly_stock" not in tables:
                raise ValueError("Archive must include sales dynamics and monthly stock workbooks")
        return _normalize(tables, brand, lead_time_days, as_of, report)
    except (ValueError, KeyError, zipfile.BadZipFile, OSError) as exc:
        report["errors"].append(str(exc))
        return empty, report


def _normalize(tables, brand, lead_time_days, as_of, report):
    products: dict[str, dict] = {}
    mapping: dict[str, str] = {}
    packages: dict[str, float] = {}
    minimums: dict[str, float] = {}
    metrics = report["metrics"]
    metrics["brand"] = brand

    def catalog(headers, row):
        sku = _text(_cell(row, _column(headers, "Код", "Код 1с", "Номенклатура.Код")))
        if not sku or sku.lower().startswith(("итого", "всего")):
            return None
        title = _text(_cell(row, _column(headers, "Номенклатура", "Наименование")))
        if not title:
            return None
        item = products.setdefault(sku, {"sku": sku, "product_name": title, "category": brand,
            "unit_price": 0, "price_unknown": True, "active": True, "source": "partner_original"})
        article = _text(_cell(row, _column(headers, "Артикул", "Артикул поставщика", "Артикул ИЭК")))
        if article:
            if sku in mapping and mapping[sku] != article:
                raise ValueError(f"Conflicting supplier article for internal SKU {sku}")
            mapping[sku] = article
            item["supplier_article"] = article
        return sku

    for kind, (headers, rows) in tables.items():
        if kind == "sales" or not headers:
            continue
        for row in rows:
            sku = catalog(headers, row)
            if not sku:
                continue
            if kind == "policies":
                pack = _column(headers, "Кратность")
                moq = _column(headers, "Мин. разр. к отгр.")
                if pack is not None:
                    try:
                        value = _number(_cell(row, pack))
                    except ValueError:
                        metrics["unknown_policy_cells"] = metrics.get("unknown_policy_cells", 0) + 1
                        continue
                    if value > 0:
                        packages[sku] = value
                if moq is not None:
                    try:
                        minimums[sku] = max(0, _number(_cell(row, moq)))
                    except ValueError:
                        metrics["unknown_policy_cells"] = metrics.get("unknown_policy_cells", 0) + 1

    headers, rows = tables["sales"]
    dates = pd.to_datetime(pd.Series([_cell(row, _column(headers, "Дата")) for row in rows]), errors="coerce", dayfirst=True, format="mixed")
    dated_count = int(dates.notna().sum())
    cutoff = pd.Timestamp(as_of).normalize() if as_of else dates.max().normalize()
    if pd.isna(cutoff):
        raise ValueError("No dated sales records found")
    sales_records = []
    for index, (row, date) in enumerate(zip(rows, dates)):
        if pd.isna(date) or date.normalize() > cutoff:
            continue
        sku = catalog(headers, row)
        if not sku:
            raise ValueError(f"Dated sales row {index + 2} has no product code/name")
        quantity = _number(_cell(row, _column(headers, "Количество")))
        warehouse = _text(_cell(row, _column(headers, "Склад")))
        if not warehouse:
            raise ValueError(f"Dated sales row {index + 2} has no warehouse")
        sales_records.append({"date": date.normalize(), "sku": sku, "product_name": products[sku]["product_name"],
            "warehouse": warehouse, "quantity": quantity, "category": brand, "price": 0,
            "price_unknown": True, "customer_id": "UNKNOWN", "customer_id_unknown": True,
            "transaction_type": "return" if quantity < 0 else "sale", "source_row": index + 2,
            "unit": _text(_cell(row, _column(headers, "Ед.", "Ед.изм")))})
    sales = pd.DataFrame(sales_records)
    if sales.empty:
        raise ValueError("No sales on or before the chosen cutoff")
    warehouses = sales["warehouse"].unique()
    if len(warehouses) != 1:
        raise ValueError("Monthly balances have no warehouse mapping; multiple sales warehouses require an explicit allocation")
    warehouse = str(warehouses[0])
    metrics.update({"source_dated_sales": dated_count, "imported_sales": len(sales),
        "future_sales_excluded": int((dates.dt.normalize() > cutoff).sum()), "negative_sales_rows": int((sales.quantity < 0).sum()),
        "sales_net_quantity": float(sales.quantity.sum()), "as_of": cutoff.strftime("%Y-%m-%d"), "warehouse": warehouse})

    headers, rows = tables["monthly_stock"]
    months = [(i, _month(value)) for i, value in enumerate(headers)]
    months = [(i, date) for i, date in months if date is not None and date <= cutoff]
    if not months:
        raise ValueError("No monthly opening balance on or before the cutoff")
    stock_column, balance_date = max(months, key=lambda pair: pair[1])
    stock_records = {}
    for row in rows:
        sku = catalog(headers, row)
        if sku:
            stock_records[sku] = {"sku": sku, "warehouse": warehouse, "current_stock": _number(_cell(row, stock_column)),
                "as_of": cutoff, "balance_date": balance_date, "balance_is_stale": balance_date < cutoff,
                "source_warning": "Monthly opening balance: supply a current stock count before approval." if balance_date < cutoff else ""}

    transit_records = []
    if "inbound" in tables:
        headers, rows = tables["inbound"]
        file_name = next(item["name"] for item in report["files"] if item["kind"] == "inbound")
        file_dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", file_name)
        snapshot_date = pd.to_datetime(file_dates[-1], dayfirst=True) if file_dates else None
        if snapshot_date is not None and snapshot_date > cutoff:
            report["warnings"].append("Inbound snapshot is newer than the chosen cutoff and was excluded to avoid using future information.")
            rows = []
        eta_columns = []
        for i, header in enumerate(headers):
            header = _text(header)
            if "поступление до" in header.lower():
                matches = re.findall(r"\d{2}\.\d{2}\.\d{4}", header)
                eta_columns.append((i, pd.to_datetime(matches[-1], dayfirst=True) if matches else pd.NaT))
            elif "в пути" in header.lower():
                match = re.search(r"(\d{2})\.(\d{2})(?:\.(\d{4}))?", header)
                eta = pd.Timestamp(year=int(match[3]) if match and match[3] else cutoff.year, month=int(match[2]), day=int(match[1])) if match else pd.NaT
                eta_columns.append((i, eta))
        for row in rows:
            sku = catalog(headers, row)
            if not sku:
                continue
            free = _column(headers, "Свободный остаток")
            if free is not None and snapshot_date is not None and snapshot_date <= cutoff:
                stock_records[sku] = {"sku": sku, "warehouse": warehouse, "current_stock": _number(_cell(row, free)),
                    "as_of": cutoff, "balance_date": snapshot_date, "balance_is_stale": snapshot_date < cutoff,
                    "source_warning": "Stock snapshot predates calculation cutoff; update the balance." if snapshot_date < cutoff else ""}
            for column, eta in eta_columns:
                quantity = _number(_cell(row, column))
                if quantity:
                    transit_records.append({"sku": sku, "warehouse": warehouse, "quantity_in_transit": quantity,
                        "expected_arrival_date": eta, "arrival_date_unknown": pd.isna(eta), "source_column": column + 1})

    missing_stock = set(sales.sku) - set(stock_records)
    for sku in missing_stock:
        stock_records[sku] = {"sku": sku, "warehouse": warehouse, "current_stock": 0, "as_of": cutoff,
            "balance_date": cutoff, "balance_is_stale": True, "balance_unknown": True,
            "source_warning": "No source balance found; zero is a placeholder, update stock before approval."}
    suppliers = [{"sku": sku, "supplier_id": "SYSTEME" if brand == "Systeme Electric" else "IEK", "supplier_name": brand,
        "supplier_article": mapping.get(sku, ""), "lead_time_days": lead_time_days,
        "lead_time_source": "user_confirmed", "moq": minimums.get(sku, 0), "package_size": packages.get(sku, 1),
        "minimum_order_unknown": sku not in minimums and brand == "IEK",
        "moq_unknown": sku not in minimums and brand == "IEK",
        "package_unknown": sku not in packages and brand == "Systeme Electric", "unit_cost": 0, "cost_unknown": True} for sku in products]
    datasets = {"sales": sales, "stock": pd.DataFrame(stock_records.values()), "products": pd.DataFrame(products.values()),
        "suppliers": pd.DataFrame(suppliers), "transit": pd.DataFrame(transit_records, columns=[*sorted(REQUIRED_COLUMNS["transit"]), "arrival_date_unknown", "source_column"]),
        "stockouts": pd.DataFrame(columns=sorted(REQUIRED_COLUMNS["stockouts"]))}
    for key, frame in datasets.items():
        datasets[key], errors, warnings = validate_table(key, frame)
        report["errors"].extend(errors)
        report["warnings"].extend(warnings)
    metrics.update({"products": len(products), "mapped_supplier_articles": len(mapping), "missing_stock": len(missing_stock),
        "stale_stock_rows": int(datasets["stock"]["balance_is_stale"].sum()), "transit_rows": len(transit_records),
        "transit_quantity": float(sum(row["quantity_in_transit"] for row in transit_records)), "lead_time_days": lead_time_days})
    report["warnings"].extend([
        "Customer IDs and selling/purchase prices are absent: explicitly marked unknown. Budget is incomplete; customer-specific anomaly detection is disabled for these rows.",
        f"Lead time {lead_time_days} days is a user-supplied policy, not a fact extracted from the archive.",
        "Category uses supplier brand because a consistent category mapping is absent; supplier article is retained separately from the internal SKU.",
        "Monthly opening balances retain their original date. Stale/missing balances require correction before order approval.",
        "Monthly sales and seasonality sheets are reference aggregates, not additional transactions; they are not added to sales a second time.",
        "No daily stockout intervals are invented from monthly snapshots. Negative sales are retained as returns without a fabricated customer/invoice match.",
        "Warehouse-less balances are assigned to the single warehouse observed in the source sales; verify this source scope before operational use.",
    ])
    if metrics.get("unknown_policy_cells"):
        report["warnings"].append(f"{metrics['unknown_policy_cells']} supplier constraint cell(s) contain an Excel error or nonnumeric value. Constraints remain marked unknown; verify them before ordering.")
    return datasets, report
