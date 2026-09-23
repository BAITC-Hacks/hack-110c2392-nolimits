"""Regressions for procurement failures found in the independent audit."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from conftest import make_data
from app.services.forecasting import forecast_series
from app.services.replenishment import calculate_recommendations, prepare_demand, resolve_as_of


def calculate(data, **kwargs):
    return calculate_recommendations(data, **{'service_factor': 0, 'safety_days': 0, **kwargs})[0][0]


def test_recurring_wholesale_orders_survive_but_one_project_order_does_not():
    data = make_data()
    weekly = data['sales'][data['sales']['date'].dt.dayofweek == 1].copy()
    weekly['quantity'], weekly['customer_id'] = 100, 'RECURRING-B2B'
    project = data['sales'].iloc[[70]].copy()
    project['quantity'], project['customer_id'] = 10000, 'RECURRING-B2B'
    data['sales'] = pd.concat([data['sales'], weekly, project], ignore_index=True)
    daily, audit = prepare_demand(data)
    assert daily['adjusted_demand'].sum() == 2040
    assert len(audit) == 1
    assert audit[0]['quantity'] == 10000
    assert calculate(data)['forecast_lead_time'] > 100


def test_tail_stockout_without_transactions_matches_explicit_zeroes():
    explicit = make_data()
    end = explicit['sales']['date'].max()
    start = end - pd.Timedelta(days=15)
    explicit['stockouts'] = pd.DataFrame([{'sku': 'QA-001', 'warehouse': 'ASTANA', 'start_date': start, 'end_date': end}])
    explicit['sales'].loc[explicit['sales']['date'] >= start, 'quantity'] = 0
    absent = deepcopy(explicit)
    absent['sales'] = absent['sales'][absent['sales']['date'] < start]
    expected, actual = calculate(explicit), calculate(absent)
    assert actual['estimated_lost_demand'] == expected['estimated_lost_demand'] == 160
    assert actual['forecast_lead_time'] == expected['forecast_lead_time']
    assert actual['metadata']['as_of'] == end.strftime('%Y-%m-%d')
    assert any('inferred' in warning for warning in actual['metadata']['warnings'])


def test_explicit_snapshot_prevents_future_sales_or_stockouts_from_leaking():
    data = make_data()
    cutoff = pd.Timestamp('2026-02-01')
    data['stock']['as_of'] = cutoff
    data['stockouts'] = pd.DataFrame([{'sku': 'QA-001', 'warehouse': 'ASTANA', 'start_date': '2026-03-01', 'end_date': '2026-03-25'}])
    daily, _ = prepare_demand(data)
    assert daily['date'].max() == cutoff
    assert daily['estimated_lost_demand'].sum() == 0
    assert resolve_as_of(data, '2026-01-20') == pd.Timestamp('2026-01-20')


def test_future_stockout_never_extends_inferred_snapshot():
    data = make_data()
    data['stockouts'] = pd.DataFrame([{'sku': 'QA-001', 'warehouse': 'ASTANA', 'start_date': '2099-01-01', 'end_date': '2099-01-10'}])
    assert resolve_as_of(data) == data['sales']['date'].max()


def test_all_warehouse_and_single_warehouse_views_share_the_same_calendar():
    data = make_data()
    old = data['sales'][data['sales']['date'] < '2026-03-10'].copy()
    other = data['sales'].assign(warehouse='ALMATY')
    data['sales'] = pd.concat([old, other], ignore_index=True)
    all_daily, _ = prepare_demand(data)
    warehouse_daily, _ = prepare_demand(data, warehouse='ASTANA')
    pd.testing.assert_frame_equal(
        all_daily[all_daily['warehouse'] == 'ASTANA'].reset_index(drop=True),
        warehouse_daily.reset_index(drop=True),
    )


def test_small_early_receipt_does_not_hide_later_supply_gap():
    data = make_data(stock=10)
    cutoff = data['sales']['date'].max()
    data['transit'] = pd.DataFrame([
        {'sku': 'QA-001', 'warehouse': 'ASTANA', 'quantity_in_transit': 1, 'expected_arrival_date': cutoff + pd.Timedelta(days=1)},
        {'sku': 'QA-001', 'warehouse': 'ASTANA', 'quantity_in_transit': 100, 'expected_arrival_date': cutoff + pd.Timedelta(days=10)},
    ])
    row = calculate(data)
    assert row['recommended_quantity'] == 0
    assert row['urgency'] == 'CRITICAL'
    assert row['metadata']['first_shortage_date'] == (cutoff + pd.Timedelta(days=2)).strftime('%Y-%m-%d')


def test_delivery_on_last_day_arrives_before_that_days_demand():
    data = make_data(stock=90, transit=10)
    data['transit']['expected_arrival_date'] = data['sales']['date'].max() + pd.Timedelta(days=10)
    row = calculate(data)
    assert row['recommended_quantity'] == 0
    assert row['urgency'] == 'LOW'
    assert row['metadata']['first_shortage_date'] is None


@pytest.mark.parametrize('arrival', ['2026-02-01', None])
def test_overdue_and_unknown_inbound_do_not_replace_actual_stock(arrival):
    data = make_data(transit=100)
    data['transit']['expected_arrival_date'] = arrival
    row = calculate(data)
    assert row['in_transit'] == 0
    assert row['recommended_quantity'] == 100
    assert row['urgency'] == 'CRITICAL'
    assert any('excluded' in warning for warning in row['metadata']['warnings'])


@pytest.mark.parametrize('days', list(range(28, 36)))
def test_flat_demand_does_not_decline_due_to_partial_week(days):
    row = calculate(make_data(days=days))
    assert row['trend_direction'] == 'stable'
    assert row['trend_percent'] == 0
    assert row['forecast_lead_time'] == 100


def test_longer_display_horizon_does_not_change_earlier_forecast():
    history = pd.DataFrame({'date': pd.date_range('2025-01-01', periods=84), 'adjusted_demand': np.linspace(10, 20, 84)})
    short, _ = forecast_series(history, 10, 0)
    extended, _ = forecast_series(history, 100, 90)
    np.testing.assert_allclose(short, extended[:10], rtol=0, atol=0)
    data = make_data()
    data['sales']['quantity'] = np.linspace(10, 20, 84)
    assert calculate(data, safety_days=0)['recommended_quantity'] == calculate(data, safety_days=90)['recommended_quantity']


@pytest.mark.parametrize('pack,stock,expected', [(0.25, 99.6, 0.5), (0.005, 99.993, 0.01), (1, 99.6, 1)])
def test_fractional_pack_rounding_respects_the_actual_supplier_quantum(pack, stock, expected):
    row = calculate(make_data(stock=stock, pack=pack))
    assert row['recommended_quantity'] == pytest.approx(expected)
    assert row['recommended_quantity'] / pack == pytest.approx(round(row['recommended_quantity'] / pack))


def test_signatures_ignore_row_order_and_internal_ids_but_track_calculation_options():
    data = make_data()
    a = calculate(data)
    changed = deepcopy(data)
    changed['sales'] = changed['sales'].sample(frac=1, random_state=8).reset_index(drop=True)
    changed['sales']['__row_id'] = np.arange(len(changed['sales']))
    b = calculate(changed)
    assert a['metadata']['dataset_signature'] == b['metadata']['dataset_signature']
    assert a['metadata']['calculation_signature'] == b['metadata']['calculation_signature']
    c = calculate(data, outlier_threshold=5)
    assert a['metadata']['calculation_signature'] != c['metadata']['calculation_signature']


def test_unknown_client_does_not_become_one_customer_or_reconcile_unrelated_returns():
    data = make_data()
    data['sales']['customer_id'] = 'UNKNOWN'
    data['sales']['customer_id_unknown'] = True
    data['sales']['transaction_type'] = 'sale'
    bulk = data['sales'].iloc[[70]].copy()
    bulk['quantity'] = 10000
    returned = data['sales'].iloc[[71]].copy()
    returned['quantity'], returned['transaction_type'] = -500, 'return'
    data['sales'] = pd.concat([data['sales'], bulk, returned], ignore_index=True)
    daily, audit = prepare_demand(data)
    assert audit == []
    assert daily['actual_sales'].sum() == 10840
    assert daily['adjusted_demand'].sum() == 10840
    row = calculate(data)
    assert row['metadata']['unreconciled_returns'] == 500
    assert any('Customer identity is missing' in warning for warning in row['metadata']['data_quality_warnings'])


def test_stale_stock_and_unknown_price_provenance_reaches_recommendation():
    data = make_data()
    data['stock']['as_of'] = '2026-03-25'
    data['stock']['balance_is_stale'] = True
    data['stock']['source_warning'] = 'Balance is from month start, refresh it.'
    data['suppliers']['cost_unknown'] = True
    row = calculate(data)
    assert row['metadata']['as_of_source'] == 'stock_snapshot'
    assert row['metadata']['balance_is_stale'] is True
    assert row['metadata']['cost_unknown'] is True
    assert row['metadata']['source_warning'] in row['explanation']
    assert 'unknown' in ' '.join(row['metadata']['data_quality_warnings']).lower()


def test_year_of_linear_growth_is_not_mislabelled_as_annual_seasonality():
    dates = pd.date_range('2025-01-01', periods=400)
    history = pd.DataFrame({'date': dates, 'adjusted_demand': 10 + np.arange(400) * 0.035})
    forecast, details = forecast_series(history, 14)
    assert details['seasonality_detected'] is False
    np.testing.assert_allclose(forecast, 10 + np.arange(400, 414) * 0.035, rtol=0.01)
