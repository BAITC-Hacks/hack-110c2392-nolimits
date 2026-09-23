"""Regression coverage for data corruption and hidden import assumptions."""
from io import BytesIO

import pandas as pd
import pytest

from app.services.validation import parse_workbook, validate_table


def workbook_bytes(tables):
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        for name, frame in tables.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return stream.getvalue()


@pytest.mark.parametrize("field", ["unit_cost", "minimum_order_value"])
def test_negative_supplier_money_is_rejected(dataset, field):
    dataset["suppliers"][field] = -100
    valid, errors, _ = validate_table("suppliers", dataset["suppliers"])
    assert valid.empty
    assert any(field in error for error in errors)


def test_negative_sales_price_is_rejected(dataset):
    dataset["sales"]["price"] = -1
    valid, errors, _ = validate_table("sales", dataset["sales"])
    assert valid.empty and errors


@pytest.mark.parametrize("physical,reserved", [
    ("physical_stock", "reserved"), ("физический_остаток", "зарезервировано"),
])
def test_physical_balance_subtracts_reservations(physical, reserved):
    frame = pd.DataFrame([{"sku": "A", "warehouse": "WH", physical: 100, reserved: 80}])
    valid, errors, _ = validate_table("stock", frame)
    assert not errors
    assert valid.iloc[0]["current_stock"] == 20


def test_explicit_available_balance_is_not_reserved_twice():
    frame = pd.DataFrame([{"sku": "A", "warehouse": "WH", "current_stock": 20, "physical_stock": 100, "reserved": 80}])
    valid, errors, _ = validate_table("stock", frame)
    assert not errors and valid.iloc[0]["current_stock"] == 20


def test_normalized_inventory_roundtrip_keeps_transit_and_catalog(dataset):
    dataset["transit"]["quantity_in_transit"] = 50
    dataset["products"] = pd.DataFrame([{"sku": "CATALOG-ONLY", "product_name": "Standalone", "category": "Cable"}])
    imported, errors, _ = parse_workbook(workbook_bytes(dataset), include_report=True)
    assert not errors
    assert imported["transit"]["quantity_in_transit"].sum() == 50
    assert imported["products"].iloc[0]["sku"] == "CATALOG-ONLY"


def test_missing_embedded_eta_is_explicitly_unknown(dataset):
    dataset["stock"]["quantity_in_transit"] = 100
    dataset.pop("transit")
    imported, errors, warnings = parse_workbook(workbook_bytes(dataset), include_report=True)
    assert not errors
    assert imported["transit"]["expected_arrival_date"].isna().all()
    assert imported["transit"]["arrival_date_unknown"].all()
    assert any("unknown" in warning for warning in warnings)


def test_explicit_transit_is_not_duplicated_from_stock(dataset):
    dataset["stock"]["quantity_in_transit"] = 50
    dataset["transit"]["quantity_in_transit"] = 50
    imported, errors, _ = parse_workbook(workbook_bytes(dataset), include_report=True)
    assert not errors
    assert imported["transit"]["quantity_in_transit"].sum() == 50


def test_invalid_eta_cannot_be_hidden_by_unknown_flag(dataset):
    dataset["transit"]["expected_arrival_date"] = "not-a-date"
    dataset["transit"]["arrival_date_unknown"] = True
    valid, errors, _ = validate_table("transit", dataset["transit"])
    assert valid.empty and errors
