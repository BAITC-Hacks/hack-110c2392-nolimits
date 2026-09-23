from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def build_demo_data(seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    end = datetime.now().date()
    start = end - timedelta(days=450)
    dates = pd.date_range(start=start, end=end, freq='D')
    warehouses = ['WH-NORTH', 'WH-CENTRAL', 'WH-SOUTH']
    suppliers = [
        ('SUP-01', 'Nordic Components', 7, 24, 5),
        ('SUP-02', 'Volga Industrial', 14, 40, 10),
        ('SUP-03', 'Atlas Trade', 21, 30, 5),
        ('SUP-04', 'Steppe Supply', 10, 20, 10),
        ('SUP-05', 'Orion Wholesale', 5, 15, 5),
    ]
    patterns = ['stable'] * 45 + ['growing'] * 25 + ['declining'] * 15 + ['seasonal'] * 15
    rng.shuffle(patterns)
    special = {'SKU-SEASONAL': 'seasonal', 'SKU-GROWTH': 'growing', 'SKU-OUTLIER': 'stable', 'SKU-STOCKOUT': 'stable', 'SKU-CRITICAL': 'growing'}
    products: list[dict] = []
    for i in range(100):
        sku = f'SKU-{i + 1:03d}'
        products.append({'sku': sku, 'product_name': f'Warehouse item {i + 1:03d}', 'category': ['Cables', 'Hardware', 'Safety', 'Tools'][i % 4], 'pattern': patterns[i]})
    products += [
        {'sku': 'SKU-SEASONAL', 'product_name': 'Seasonal outdoor cable', 'category': 'Cables', 'pattern': 'seasonal'},
        {'sku': 'SKU-GROWTH', 'product_name': 'Fast growing connector', 'category': 'Hardware', 'pattern': 'growing'},
        {'sku': 'SKU-OUTLIER', 'product_name': 'Industrial cable reel', 'category': 'Cables', 'pattern': 'stable'},
        {'sku': 'SKU-STOCKOUT', 'product_name': 'Protective gloves', 'category': 'Safety', 'pattern': 'stable'},
        {'sku': 'SKU-CRITICAL', 'product_name': 'High-turnover drill bit', 'category': 'Tools', 'pattern': 'growing'},
    ]
    sales: list[dict] = []
    stock: list[dict] = []
    transit: list[dict] = []
    stockouts: list[dict] = []
    supplier_rows: list[dict] = []
    for idx, product in enumerate(products):
        supplier = suppliers[idx % len(suppliers)]
        supplier_rows.append({'supplier_id': supplier[0], 'supplier_name': supplier[1], 'sku': product['sku'], 'lead_time_days': supplier[2], 'moq': supplier[3], 'package_size': supplier[4]})
        base = 8 + (idx % 13) * 1.8
        for warehouse_index, warehouse in enumerate(warehouses):
            warehouse_factor = [1.0, 0.85, 1.15][warehouse_index]
            stock_level = base * warehouse_factor * supplier[2] * (0.65 if product['sku'] == 'SKU-CRITICAL' else 1.8)
            stock.append({'sku': product['sku'], 'warehouse': warehouse, 'current_stock': round(stock_level, 1)})
            if idx % 4 == warehouse_index % 4:
                transit.append({'sku': product['sku'], 'warehouse': warehouse, 'quantity_in_transit': round(base * 1.7, 1), 'expected_arrival_date': end + timedelta(days=supplier[2] // 2)})
            if product['sku'] == 'SKU-STOCKOUT' and warehouse == 'WH-CENTRAL':
                stockouts.append({'sku': product['sku'], 'warehouse': warehouse, 'start_date': end - timedelta(days=83), 'end_date': end - timedelta(days=76)})
            for date_index, date in enumerate(dates):
                weekly = 1 + 0.12 * np.sin(2 * np.pi * date.dayofweek / 7)
                if product['pattern'] == 'seasonal':
                    seasonal = 1 + 0.45 * np.sin(2 * np.pi * date.dayofyear / 365)
                else:
                    seasonal = 1.0
                if product['pattern'] == 'growing':
                    trend = 0.7 + 0.75 * (date_index / len(dates))
                elif product['pattern'] == 'declining':
                    trend = 1.2 - 0.55 * (date_index / len(dates))
                else:
                    trend = 1.0
                quantity = max(0, rng.poisson(base * warehouse_factor * weekly * seasonal * trend))
                if product['sku'] == 'SKU-STOCKOUT' and warehouse == 'WH-CENTRAL' and end - timedelta(days=83) <= date.date() <= end - timedelta(days=76):
                    quantity = 0
                customer_id = f'C{int(rng.integers(1, 80)):04d}'
                sales.append({'date': date, 'sku': product['sku'], 'product_name': product['product_name'], 'quantity': int(quantity), 'price': round(300 + (idx % 17) * 37.5, 2), 'customer_id': customer_id, 'warehouse': warehouse, 'category': product['category']})
                if product['sku'] == 'SKU-OUTLIER' and warehouse == 'WH-NORTH' and date.date() == end - timedelta(days=35):
                    sales[-1]['quantity'] = 650
                    sales[-1]['customer_id'] = 'C9999'
    return {
        'sales': pd.DataFrame(sales),
        'stock': pd.DataFrame(stock),
        'transit': pd.DataFrame(transit),
        'stockouts': pd.DataFrame(stockouts),
        'suppliers': pd.DataFrame(supplier_rows),
    }
