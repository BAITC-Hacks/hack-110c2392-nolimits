"""Business invariants and hand-calculated oracles, independent of implementation."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from conftest import make_data
from app.services.forecasting import forecast_series
from app.services.replenishment import calculate_recommendations


def test_stress_return_reconciliation_and_dropship_exclusion():
    from conftest import make_data
    from app.services.replenishment import prepare_demand

    data = make_data()
    base = data['sales']
    typo = base.iloc[[70]].copy()
    typo['quantity'], typo['customer_id'], typo['transaction_type'] = 4000, 'TYPO-CLIENT', 'operator error'
    returned = base.iloc[[71]].copy()
    returned['quantity'], returned['customer_id'], returned['transaction_type'] = -3960, 'TYPO-CLIENT', 'СТОРНО / ВОЗВРАТ'
    dropship = base.iloc[[72]].copy()
    dropship['quantity'], dropship['customer_id'], dropship['transaction_type'] = 5000, 'PROJECT', 'ТРАНЗИТНАЯ ПОСТАВКА'
    base['transaction_type'] = 'regular'
    data['sales'] = pd.concat([base, typo, returned, dropship], ignore_index=True)

    daily, _ = prepare_demand(data)
    actual = daily.set_index('date')['actual_sales']
    assert actual.loc[base.iloc[70]['date']] == 50  # 10 regular + (4000 - 3960)
    assert actual.loc[base.iloc[72]['date']] == 10  # direct-to-customer shipment


def test_inbound_does_not_hide_stockout_before_its_arrival():
    data = make_data(stock=0, transit=100)
    data['transit'].loc[0, 'expected_arrival_date'] = data['sales']['date'].max() + pd.Timedelta(days=9)
    row = calculate(data)
    assert row['recommended_quantity'] == 0
    assert row['days_of_cover'] == 0
    assert row['urgency'] == 'CRITICAL'


def calculate(data, **kwargs):
    settings = {"service_factor": 0, "safety_days": 0, **kwargs}
    return calculate_recommendations(data, **settings)[0][0]


def stockout(data, start="2026-03-01", end="2026-03-16", *, remove=False):
    data["stockouts"] = pd.DataFrame([{
        "sku": "QA-001", "warehouse": "ASTANA", "start_date": start, "end_date": end,
    }])
    affected = data["sales"]["date"].between(start, end)
    if remove:
        data["sales"] = data["sales"].loc[~affected].reset_index(drop=True)
    else:
        data["sales"].loc[affected, "quantity"] = 0


def test_E01_exact_hand_calculation():
    # Demand 10/day * 10 days - available 20 - inbound 30 = 50.
    # MOQ 24, pack 12 => ceil(50/12)*12 = 60.
    row = calculate(make_data(stock=20, transit=30, moq=24, pack=12))
    assert row["forecast_lead_time"] == pytest.approx(100)
    assert row["raw_recommended_quantity"] == pytest.approx(50)
    assert row["recommended_quantity"] == 60


@pytest.mark.parametrize("field", ["stock", "transit"])
def test_E02_more_inventory_never_increases_order(field):
    rows = [calculate(make_data(**{field: amount}, moq=24, pack=12))
            for amount in [0, 1, 10, 11, 12, 50, 100, 1000]]
    for previous, current in zip(rows, rows[1:]):
        assert current["raw_recommended_quantity"] <= previous["raw_recommended_quantity"]
        assert current["recommended_quantity"] <= previous["recommended_quantity"]
    assert rows[-1]["recommended_quantity"] == 0


@pytest.mark.parametrize("stock,quantity", [(1000, 10), (0, 0)])
def test_E03_zero_need_does_not_activate_moq(stock, quantity):
    assert calculate(make_data(stock=stock, quantity=quantity, moq=1000, pack=40))["recommended_quantity"] == 0


def test_E04_nondivisible_moq_rounds_up():
    assert calculate(make_data(stock=99, moq=50, pack=12))["recommended_quantity"] == 60


def test_E05_pack_one_still_requires_whole_units():
    row = calculate(make_data(stock=0.5, pack=1))
    assert row["recommended_quantity"] == 100, row


def test_E06_later_delivery_cannot_cover_earlier_need():
    base = calculate(make_data())
    data = make_data(transit=1000)
    data["transit"]["expected_arrival_date"] = data["sales"]["date"].max() + pd.Timedelta(days=365)
    row = calculate(data)
    assert row["recommended_quantity"] == base["recommended_quantity"], row


def test_E07_warehouse_inventory_is_isolated():
    data = make_data()
    other = data["stock"].copy()
    other["warehouse"], other["current_stock"] = "ALMATY", 100000
    data["stock"] = pd.concat([data["stock"], other], ignore_index=True)
    assert calculate(data)["recommended_quantity"] == 100


def test_E08_stockout_explicit_zeroes_reconstruct_160_units():
    data = make_data()
    stockout(data)
    assert calculate(data)["estimated_lost_demand"] == pytest.approx(160)


def test_E09_stockout_missing_transactions_reconstruct_160_units():
    data = make_data()
    stockout(data, remove=True)
    assert calculate(data)["estimated_lost_demand"] == pytest.approx(160)


def test_E10_stockout_rows_missing_and_zero_are_equivalent():
    explicit, absent = make_data(), make_data()
    stockout(explicit)
    stockout(absent, remove=True)
    a, b = calculate(explicit), calculate(absent)
    assert a["estimated_lost_demand"] == b["estimated_lost_demand"]
    assert a["recommended_quantity"] == b["recommended_quantity"]


def test_E11_overlapping_stockouts_do_not_double_count():
    data = make_data()
    stockout(data)
    additional = data["stockouts"].copy()
    additional["start_date"], additional["end_date"] = "2026-03-05", "2026-03-10"
    data["stockouts"] = pd.concat([data["stockouts"], additional], ignore_index=True)
    assert calculate(data)["estimated_lost_demand"] == pytest.approx(160)


def test_E12_stockout_does_not_leak_between_warehouses():
    data = make_data()
    stockout(data)
    data["stockouts"]["warehouse"] = "ALMATY"
    assert calculate(data)["estimated_lost_demand"] == 0


def test_E13_missing_nonsale_days_equal_explicit_zeroes():
    explicit = make_data(days=84)
    weekends = explicit["sales"]["date"].dt.dayofweek >= 5
    explicit["sales"].loc[weekends, "quantity"] = 0
    absent = deepcopy(explicit)
    absent["sales"] = absent["sales"].loc[~weekends].reset_index(drop=True)
    a, b = calculate(explicit), calculate(absent)
    assert b["forecast_lead_time"] == pytest.approx(a["forecast_lead_time"], rel=0.01)


def test_E14_one_off_4800_does_not_inflate_regular_forecast():
    data = make_data()
    data["sales"].loc[70, ["quantity", "customer_id"]] = [4800, "PROJECT-CLIENT"]
    rows, audit = calculate_recommendations(data, service_factor=0, safety_days=0)
    assert any(item["customer_id"] == "PROJECT-CLIENT" for item in audit)
    assert next(item for item in audit if item["customer_id"] == "PROJECT-CLIENT")["typical_quantity"] > 0
    assert rows[0]["forecast_lead_time"] == pytest.approx(100, rel=0.05)
    assert data["sales"].loc[70, "quantity"] == 4800


def test_E15_split_customer_order_is_detected():
    data = make_data()
    # A single project order split into 480 rows of 10 units for one client/day.
    extra = pd.concat([data["sales"].iloc[[70]]] * 480, ignore_index=True)
    extra["customer_id"] = "PROJECT-CLIENT"
    data["sales"] = pd.concat([data["sales"], extra], ignore_index=True)
    rows, audit = calculate_recommendations(data, service_factor=0, safety_days=0)
    assert any(item["customer_id"] == "PROJECT-CLIENT" for item in audit), "4800-unit client/day order was not detected"
    assert rows[0]["forecast_lead_time"] == pytest.approx(100, rel=0.05)


def test_E16_audit_contains_only_relevant_sku():
    data = make_data()
    extra = data["sales"].copy()
    extra["sku"] = "QA-OTHER"
    extra.loc[30, "quantity"] = 4800
    data["sales"] = pd.concat([data["sales"], extra], ignore_index=True)
    rows, _ = calculate_recommendations(data)
    row = next(r for r in rows if r["sku"] == "QA-001")
    assert all(item["sku"] == row["sku"] for item in row["metadata"]["outliers_removed"])


def test_E17_winter_peak_is_forecast_before_november():
    dates = pd.date_range("2025-11-01", "2026-10-31")
    history = pd.DataFrame({"date": dates, "adjusted_demand": np.where(dates.month.isin([11, 12, 1, 2]), 165.0, 100.0)})
    forecast, _ = forecast_series(history, 30, 0)
    # Broad tolerance: the full 65% need not be learned from one cycle.
    assert forecast.mean() >= 130, f"November forecast mean={forecast.mean():.2f}; October=100, prior winter=165"


def test_E18_sustained_growth_raises_forecast():
    flat, growth = make_data(), make_data()
    growth["sales"]["quantity"] = np.linspace(10, 20, len(growth["sales"]))
    assert calculate(growth)["forecast_lead_time"] > calculate(flat)["forecast_lead_time"]


def test_E19_row_order_does_not_change_results(dataset):
    expected = calculate(dataset)
    dataset["sales"] = dataset["sales"].sample(frac=1, random_state=17).reset_index(drop=True)
    actual = calculate(dataset)
    for field in ["recommended_quantity", "forecast_lead_time", "estimated_lost_demand"]:
        assert actual[field] == expected[field]


@pytest.mark.parametrize("days", [1, 2, 7])
def test_E20_short_history_is_finite(days):
    row = calculate(make_data(days=days))
    for key in ["recommended_quantity", "forecast_lead_time", "safety_stock", "days_of_cover"]:
        assert np.isfinite(row[key]) and row[key] >= 0


def test_E21_no_sales_is_safe(dataset):
    dataset["sales"] = dataset["sales"].iloc[:0]
    assert calculate_recommendations(dataset) == ([], [])


def test_E22_calculation_does_not_mutate_source(dataset):
    original = deepcopy(dataset)
    calculate(dataset)
    for key in dataset:
        pd.testing.assert_frame_equal(dataset[key], original[key])


def test_E23_longer_lead_time_increases_constant_demand_order():
    assert calculate(make_data(lead=20))["recommended_quantity"] > calculate(make_data(lead=10))["recommended_quantity"]


def test_E24_higher_service_factor_increases_safety_stock():
    data = make_data()
    data["sales"]["quantity"] = np.tile([8, 10, 12], 28)
    low = calculate(data, service_factor=0)
    high = calculate(data, service_factor=1.65)
    assert low["safety_stock"] == 0
    assert high["safety_stock"] > 0
    assert high["recommended_quantity"] >= low["recommended_quantity"]
