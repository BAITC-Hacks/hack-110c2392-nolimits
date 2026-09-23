import pandas as pd
import numpy as np

from app.main import _json_safe
from app.services.replenishment import calculate_recommendations


def make_data(stock=20, transit=0):
    dates = pd.date_range('2026-01-01', periods=70, freq='D')
    return {
        'sales': pd.DataFrame({'date': dates, 'sku': ['SKU-1'] * len(dates), 'product_name': ['Widget'] * len(dates), 'quantity': [10 + (i % 3) for i in range(len(dates))], 'price': [100] * len(dates), 'customer_id': ['C1'] * len(dates), 'warehouse': ['WH1'] * len(dates), 'category': ['Tools'] * len(dates)}),
        'stock': pd.DataFrame([{'sku': 'SKU-1', 'warehouse': 'WH1', 'current_stock': stock}]),
        'transit': pd.DataFrame([{'sku': 'SKU-1', 'warehouse': 'WH1', 'quantity_in_transit': transit, 'expected_arrival_date': '2026-03-20'}]),
        'stockouts': pd.DataFrame(columns=['sku', 'warehouse', 'start_date', 'end_date']),
        'suppliers': pd.DataFrame([{'supplier_id': 'SUP-1', 'supplier_name': 'Supplier', 'sku': 'SKU-1', 'lead_time_days': 14, 'moq': 0, 'package_size': 1}]),
    }


def test_current_stock_reduces_recommendation():
    low = calculate_recommendations(make_data(stock=10))[0][0]['recommended_quantity']
    high = calculate_recommendations(make_data(stock=100))[0][0]['recommended_quantity']
    assert high < low


def test_transit_reduces_recommendation():
    without = calculate_recommendations(make_data(transit=0))[0][0]['recommended_quantity']
    with_transit = calculate_recommendations(make_data(transit=50))[0][0]['recommended_quantity']
    assert with_transit < without


def test_outlier_is_excluded_but_preserved():
    data = make_data()
    data['sales'].loc[30, 'quantity'] = 1000
    rows, outliers = calculate_recommendations(data)
    assert rows[0]['outliers_removed'] == 1
    assert outliers[0]['quantity'] == 1000


def test_normal_volume_variation_is_not_marked_as_one_off():
    data = make_data()
    data['sales'].loc[30, 'quantity'] = 18
    _, outliers = calculate_recommendations(data)
    assert outliers == []


def test_recommendation_never_negative():
    row = calculate_recommendations(make_data(stock=10000))[0][0]
    assert row['recommended_quantity'] >= 0


def test_moq_and_package_rounding_are_applied():
    data = make_data(stock=0)
    data['suppliers'].loc[0, 'moq'] = 25
    data['suppliers'].loc[0, 'package_size'] = 10
    row = calculate_recommendations(data)[0][0]
    assert row['recommended_quantity'] >= 25
    assert row['recommended_quantity'] % 10 == 0
    assert 'rounded up to a package multiple' in row['explanation']


def test_stockout_zeroes_are_replaced_with_lost_demand():
    data = make_data(stock=20)
    data['stockouts'] = pd.DataFrame([{'sku': 'SKU-1', 'warehouse': 'WH1', 'start_date': '2026-02-05', 'end_date': '2026-02-08'}])
    rows, _ = calculate_recommendations(data)
    row = rows[0]
    assert row['estimated_lost_demand'] > 0
    assert 'Estimated lost demand' in row['explanation']


def test_calculation_payload_is_json_safe():
    payload = _json_safe({'units': np.int64(4), 'nested': [np.float64(2.5)]})
    assert payload == {'units': 4, 'nested': [2.5]}
