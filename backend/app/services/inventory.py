"""Apply a complete stock operation to copies of the planning datasets."""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

import pandas as pd


class InventoryError(ValueError):
    pass


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InventoryError('Количество и цена должны быть числами') from exc
    if not isfinite(number):
        raise InventoryError('Количество и цена должны быть конечными числами')
    return number


def apply_movement(datasets: dict[str, pd.DataFrame], operation: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Validate every line before returning a changed snapshot; never mutate input."""
    result = {name: frame.copy(deep=True) for name, frame in datasets.items()}
    kind = operation['kind']
    warehouse = str(operation['warehouse']).strip()
    destination = str(operation.get('destination_warehouse') or '').strip()
    partner = str(operation.get('partner') or '').strip()
    lines = operation['lines']
    if not warehouse:
        raise InventoryError('Выберите склад')
    if not lines:
        raise InventoryError('Добавьте хотя бы один товар')
    if kind == 'TRANSFER' and (not destination or destination == warehouse):
        raise InventoryError('Выберите другой склад назначения')
    if kind in {'PURCHASE', 'SALE'} and not partner:
        raise InventoryError('Укажите поставщика или покупателя')
    if kind == 'PURCHASE' and not operation.get('expected_arrival_date'):
        raise InventoryError('Укажите ожидаемую дату поставки')
    if kind == 'PURCHASE' and date.fromisoformat(operation['expected_arrival_date']) < date.fromisoformat(operation['date']):
        raise InventoryError('Дата поставки не может быть раньше даты заказа')

    products = result.get('products', pd.DataFrame()).copy()
    stock = result.get('stock', pd.DataFrame()).copy()
    transit = result.get('transit', pd.DataFrame()).copy()
    sales = result.get('sales', pd.DataFrame()).copy()
    suppliers = result.get('suppliers', pd.DataFrame()).copy()
    stock_columns = ['sku', 'warehouse', 'current_stock']
    transit_columns = ['sku', 'warehouse', 'quantity_in_transit', 'expected_arrival_date']
    product_columns = ['sku', 'product_name', 'category', 'unit_price', 'active']
    sales_columns = ['date', 'sku', 'product_name', 'category', 'quantity', 'price', 'customer_id', 'warehouse', 'transaction_type']
    if stock.empty and not len(stock.columns):
        stock = pd.DataFrame(columns=stock_columns)
    if transit.empty and not len(transit.columns):
        transit = pd.DataFrame(columns=transit_columns)
    if products.empty and not len(products.columns):
        products = pd.DataFrame(columns=product_columns)
    if sales.empty and not len(sales.columns):
        sales = pd.DataFrame(columns=sales_columns)

    def change_stock(sku: str, wh: str, delta: float) -> None:
        nonlocal stock
        matching = stock.index[(stock['sku'].astype(str) == sku) & (stock['warehouse'].astype(str) == wh)]
        if len(matching) > 1:
            raise InventoryError(f'Дублирующийся остаток {sku} на складе {wh}')
        current = _number(stock.at[matching[0], 'current_stock']) if len(matching) else 0.0
        updated = round(current + delta, 8)
        if updated < -1e-8:
            raise InventoryError(f'Недостаточно {sku} на складе {wh}: доступно {current:g}, нужно {-delta:g}')
        if len(matching):
            stock.at[matching[0], 'current_stock'] = max(0.0, updated)
        else:
            stock = pd.concat([stock, pd.DataFrame([{'sku': sku, 'warehouse': wh,
                                                     'current_stock': max(0.0, updated)}])], ignore_index=True)

    def consume_transit(sku: str, quantity: float) -> None:
        nonlocal transit
        matching = transit.index[(transit['sku'].astype(str) == sku) &
                                 (transit['warehouse'].astype(str) == warehouse)].tolist()
        available = sum(_number(transit.at[index, 'quantity_in_transit']) for index in matching)
        if available + 1e-8 < quantity:
            raise InventoryError(f'Для поступления {sku} в пути только {available:g}, запрошено {quantity:g}')
        remaining = quantity
        for index in matching:
            take = min(remaining, _number(transit.at[index, 'quantity_in_transit']))
            transit.at[index, 'quantity_in_transit'] = round(_number(transit.at[index, 'quantity_in_transit']) - take, 8)
            remaining -= take
            if remaining <= 1e-8:
                break
        transit = transit[pd.to_numeric(transit['quantity_in_transit'], errors='coerce') > 1e-8].reset_index(drop=True)

    for line in lines:
        sku = str(line.get('sku') or '').strip()
        if not sku:
            raise InventoryError('У каждой позиции должен быть артикул SKU')
        quantity = _number(line.get('quantity'))
        price = _number(line.get('unit_price', 0))
        if quantity == 0 or (quantity < 0 and kind != 'ADJUSTMENT'):
            raise InventoryError('Количество должно быть положительным; в корректировке допустим минус')
        if price < 0:
            raise InventoryError('Цена не может быть отрицательной')
        known = products[products['sku'].astype(str) == sku] if 'sku' in products else pd.DataFrame()
        name = str(line.get('product_name') or (known.iloc[0].get('product_name') if not known.empty else '') or '').strip()
        category = str(line.get('category') or (known.iloc[0].get('category') if not known.empty else '') or 'Other').strip()
        if not name:
            raise InventoryError(f'Укажите название нового товара {sku}')
        if known.empty:
            products = pd.concat([products, pd.DataFrame([{'sku': sku, 'product_name': name,
                'category': category, 'unit_price': price, 'active': True}])], ignore_index=True)
        elif line.get('product_name'):
            products.loc[known.index, 'product_name'] = name

        if kind == 'PURCHASE':
            transit = pd.concat([transit, pd.DataFrame([{'sku': sku, 'warehouse': warehouse,
                'quantity_in_transit': quantity, 'expected_arrival_date': pd.Timestamp(operation['expected_arrival_date'])}])], ignore_index=True)
            if suppliers.empty or 'sku' not in suppliers or not (suppliers['sku'].astype(str) == sku).any():
                supplier = {'sku': sku, 'supplier_id': partner, 'supplier_name': partner,
                            'lead_time_days': max(1, (date.fromisoformat(operation['expected_arrival_date']) -
                                date.fromisoformat(operation['date'])).days), 'moq': 0,
                            'package_size': 1, 'unit_cost': price}
                suppliers = pd.concat([suppliers, pd.DataFrame([supplier])], ignore_index=True)
        elif kind == 'RECEIPT':
            consume_transit(sku, quantity)
            change_stock(sku, warehouse, quantity)
        elif kind == 'SALE':
            change_stock(sku, warehouse, -quantity)
            sales = pd.concat([sales, pd.DataFrame([{'date': pd.Timestamp(operation['date']), 'sku': sku,
                'product_name': name, 'category': category, 'quantity': quantity, 'price': price,
                'customer_id': partner, 'warehouse': warehouse, 'transaction_type': 'regular'}])], ignore_index=True)
        elif kind == 'RETURN':
            change_stock(sku, warehouse, quantity)
            sales = pd.concat([sales, pd.DataFrame([{'date': pd.Timestamp(operation['date']), 'sku': sku,
                'product_name': name, 'category': category, 'quantity': -quantity, 'price': price,
                'customer_id': partner or 'RETURN', 'warehouse': warehouse,
                'transaction_type': 'return'}])], ignore_index=True)
        elif kind == 'TRANSFER':
            change_stock(sku, warehouse, -quantity)
            change_stock(sku, destination, quantity)
        elif kind == 'ADJUSTMENT':
            change_stock(sku, warehouse, quantity)
        else:
            raise InventoryError('Неизвестный вид операции')

    result.update({'products': products.reset_index(drop=True), 'stock': stock.reset_index(drop=True),
                   'transit': transit.reset_index(drop=True), 'sales': sales.reset_index(drop=True),
                   'suppliers': suppliers.reset_index(drop=True)})
    return result
