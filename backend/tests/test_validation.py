import pandas as pd

from app.services.validation import validate_table


def test_validation_keeps_valid_rows_and_reports_bad_dates_and_negative_stock():
    frame = pd.DataFrame([
        {'sku': 'SKU-1', 'warehouse': 'WH1', 'current_stock': 10},
        {'sku': 'SKU-2', 'warehouse': 'WH1', 'current_stock': -4},
        {'sku': 'SKU-3', 'warehouse': 'WH1', 'current_stock': 'not-a-number'},
    ])
    cleaned, errors, _ = validate_table('stock', frame, {'WH1'}, {'SKU-1', 'SKU-2', 'SKU-3'})
    assert len(cleaned) == 1
    assert any('negative value' in error for error in errors)
    assert any('non-numeric' in error for error in errors)


def test_validation_rejects_unknown_warehouse_without_crashing():
    frame = pd.DataFrame([{
        'date': '2026-01-01', 'sku': 'SKU-1', 'product_name': 'Widget', 'quantity': 5,
        'price': 100, 'customer_id': 'C1', 'warehouse': 'WH-UNKNOWN', 'category': 'Tools',
    }])
    cleaned, errors, _ = validate_table('sales', frame, {'WH1'}, {'SKU-1'})
    assert cleaned.empty
    assert any('unknown warehouse' in error for error in errors)


def test_validation_drops_invalid_supplier_lead_time_and_deduplicates_mapping():
    frame = pd.DataFrame([
        {'supplier_id': 'SUP-1', 'supplier_name': 'Supplier', 'sku': 'SKU-1', 'lead_time_days': 10},
        {'supplier_id': 'SUP-1', 'supplier_name': 'Supplier', 'sku': 'SKU-1', 'lead_time_days': 10},
        {'supplier_id': 'SUP-2', 'supplier_name': 'Supplier 2', 'sku': 'SKU-1', 'lead_time_days': 0},
    ])
    cleaned, errors, warnings = validate_table('suppliers', frame, {'WH1'}, {'SKU-1'})
    assert len(cleaned) == 1
    assert any('greater than zero' in error for error in errors)
    assert any('duplicate' in warning.lower() for warning in warnings)
