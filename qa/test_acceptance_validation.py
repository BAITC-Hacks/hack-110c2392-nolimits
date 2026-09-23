"""Input errors must be visible before they affect procurement."""
import pandas as pd
import pytest

from app.services.validation import validate_table


@pytest.mark.parametrize("dataset,column,value", [
    ("stock", "current_stock", -1),
    ("stock", "current_stock", "not-a-number"),
    ("stock", "current_stock", float("inf")),
    ("sales", "quantity", float("nan")),
    ("sales", "quantity", float("inf")),
    ("suppliers", "lead_time_days", 0),
    ("suppliers", "package_size", 0),
    ("suppliers", "package_size", -1),
])
def test_V01_invalid_numeric_input_is_reported(dataset, column, value):
    from conftest import make_data
    frame = make_data()[dataset].astype({column: object})
    frame.loc[0, column] = value
    _, errors, _ = validate_table(dataset, frame)
    assert errors, f"Accepted {dataset}.{column}={value!r}"


def test_V02_conflicting_stock_key_is_rejected(dataset):
    frame = pd.concat([dataset["stock"], dataset["stock"].assign(current_stock=999)], ignore_index=True)
    _, errors, _ = validate_table("stock", frame)
    assert errors, "Two different balances for one SKU/warehouse have no timestamp or aggregation rule"


def test_V03_reversed_stockout_interval_is_rejected():
    frame = pd.DataFrame([{"sku": "QA-001", "warehouse": "ASTANA", "start_date": "2026-03-16", "end_date": "2026-03-01"}])
    _, errors, _ = validate_table("stockouts", frame)
    assert errors


@pytest.mark.parametrize("sku", [None, "", "   "])
def test_V04_empty_sku_is_reported(dataset, sku):
    dataset["stock"].loc[0, "sku"] = sku
    assert validate_table("stock", dataset["stock"])[1]


def test_V05_invalid_date_is_reported(dataset):
    frame = dataset["sales"].astype({"date": object})
    frame.loc[0, "date"] = "2026-02-30"
    assert validate_table("sales", frame)[1]
