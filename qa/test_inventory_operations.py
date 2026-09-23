"""A real multi-item checkout through the API, using a disposable SQLite DB."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from io import BytesIO
from threading import Event

import pandas as pd


def operation(kind, lines, *, request_id, warehouse='ASTANA', partner='', destination=None, arrival=None, date='2026-09-23'):
    return {'kind': kind, 'date': date, 'warehouse': warehouse,
            'destination_warehouse': destination, 'partner': partner,
            'expected_arrival_date': arrival, 'reference': request_id,
            'client_request_id': request_id, 'lines': lines}


def line(sku, quantity):
    return {'sku': sku, 'product_name': f'Test {sku}', 'category': 'Cables',
            'quantity': quantity, 'unit_price': 100}


def balance(client, sku, warehouse):
    rows = client.get('/api/inventory/stock').json()['rows']
    return next(row for row in rows if row['sku'] == sku and row['warehouse'] == warehouse)


def test_purchase_receipt_sale_transfer_and_export_survive_restart(api_factory):
    with api_factory() as client:
        purchase = operation('PURCHASE', [line('NEW-A', 10), line('NEW-B', 4)],
                             request_id='purchase-1', partner='SUP-1', arrival='2026-10-01')
        response = client.post('/api/inventory/movements', json=purchase)
        assert response.status_code == 200, response.text
        assert balance(client, 'NEW-A', 'ASTANA')['in_transit'] == 10
        assert balance(client, 'NEW-A', 'ASTANA')['current_stock'] == 0
        assert client.post('/api/inventory/movements', json=purchase).json()['replayed'] is True
        assert len(client.get('/api/inventory/movements').json()['movements']) == 1

        receipt = operation('RECEIPT', [line('NEW-A', 10), line('NEW-B', 4)], request_id='receipt-1')
        assert client.post('/api/inventory/movements', json=receipt).status_code == 200
        assert balance(client, 'NEW-A', 'ASTANA')['in_transit'] == 0
        assert balance(client, 'NEW-A', 'ASTANA')['current_stock'] == 10

        oversell = operation('SALE', [line('NEW-A', 11)], request_id='bad-sale', partner='CUSTOMER')
        assert client.post('/api/inventory/movements', json=oversell).status_code == 422
        assert balance(client, 'NEW-A', 'ASTANA')['current_stock'] == 10
        assert len(client.get('/api/inventory/movements').json()['movements']) == 2

        assert client.post('/api/inventory/movements', json=operation('SALE', [line('NEW-A', 3), line('NEW-B', 1)], request_id='sale-1', partner='CUSTOMER')).status_code == 200
        assert client.post('/api/inventory/movements', json=operation('TRANSFER', [line('NEW-A', 2)], request_id='transfer-1', destination='ALMATY')).status_code == 200
        assert client.post('/api/inventory/movements', json=operation('ADJUSTMENT', [line('NEW-A', -1)], request_id='adjust-1')).status_code == 200
        assert client.post('/api/inventory/movements', json=operation('RETURN', [line('NEW-A', 1)], request_id='return-1', partner='CUSTOMER')).status_code == 200
        assert balance(client, 'NEW-A', 'ASTANA')['current_stock'] == 5
        assert balance(client, 'NEW-A', 'ALMATY')['current_stock'] == 2
        assert balance(client, 'NEW-B', 'ASTANA')['current_stock'] == 3
        assert len(client.get('/api/inventory/movements').json()['movements']) == 6

        workbook = client.get('/api/inventory/export')
        assert workbook.status_code == 200
        excel = pd.ExcelFile(BytesIO(workbook.content))
        assert {'products', 'sales', 'stock', 'transit', 'movements'} <= set(excel.sheet_names)
        assert len(excel.parse('movements')) == 9
        assert 'NEW-A' in set(excel.parse('products')['sku'])

    with api_factory() as client:
        assert balance(client, 'NEW-A', 'ASTANA')['current_stock'] == 5
        assert 'NEW-A' in {item['sku'] for item in client.get('/api/inventory/catalog').json()['products']}
        assert len(client.get('/api/inventory/movements').json()['movements']) == 6
        client.post('/api/data/demo')
        assert 'NEW-A' in {item['sku'] for item in client.get('/api/inventory/catalog').json()['products']}


def test_purchase_reduces_recommendation_before_receipt(api_factory):
    with api_factory() as client:
        before = next(row for row in client.get('/api/recommendations').json()['recommendations'] if row['sku'] == 'QA-001')
        response = client.post('/api/inventory/movements', json=operation(
            'PURCHASE', [line('QA-001', 1000)], request_id='inbound-qa', partner='QA-SUP',
            arrival='2026-03-27', date='2026-03-26'))
        assert response.status_code == 200, response.text
        after = next(row for row in client.get('/api/recommendations').json()['recommendations'] if row['sku'] == 'QA-001')
        assert after['recommended_quantity'] < before['recommended_quantity']
        assert balance(client, 'QA-001', 'ASTANA')['current_stock'] == 0
        assert balance(client, 'QA-001', 'ASTANA')['in_transit'] == 1000


def test_reused_request_id_with_changed_cart_is_rejected(api_factory):
    with api_factory() as client:
        first = operation('PURCHASE', [line('IDEMPOTENT', 2)], request_id='same-id',
                          partner='SUP-1', arrival='2026-10-01')
        assert client.post('/api/inventory/movements', json=first).status_code == 200
        changed = operation('PURCHASE', [line('IDEMPOTENT', 9)], request_id='same-id',
                            partner='SUP-1', arrival='2026-10-01')
        response = client.post('/api/inventory/movements', json=changed)
        assert response.status_code == 409, response.text
        assert balance(client, 'IDEMPOTENT', 'ASTANA')['in_transit'] == 2
        assert len(client.get('/api/inventory/movements').json()['movements']) == 1


def test_editor_cannot_overwrite_a_concurrent_stock_movement(api_factory, monkeypatch):
    from app import main

    with api_factory() as client:
        main.state.datasets['stock'].at[0, 'current_stock'] = 10
        monkeypatch.setattr(main, 'calculate_recommendations', lambda *_args, **_kwargs: ([], []))
        real_editor_frame = main._editor_frame
        editor_paused = Event()
        release_editor = Event()

        def pause_after_snapshot(dataset, rows):
            editor_paused.set()
            assert release_editor.wait(10)
            return real_editor_frame(dataset, rows)

        monkeypatch.setattr(main, '_editor_frame', pause_after_snapshot)
        with ThreadPoolExecutor(max_workers=2) as executor:
            editor = executor.submit(client.post, '/api/editor/stock/rows', json={
                'row': {'sku': 'QA-001', 'warehouse': 'ALMATY', 'current_stock': 0}})
            assert editor_paused.wait(5)
            movement = executor.submit(client.post, '/api/inventory/movements', json=operation(
                'ADJUSTMENT', [line('QA-001', -1)], request_id='concurrent-adjust'))
            try:
                movement.result(timeout=2)
            except TimeoutError:
                pass
            finally:
                release_editor.set()
            assert editor.result(timeout=10).status_code == 200
            assert movement.result(timeout=10).status_code == 200
        assert balance(client, 'QA-001', 'ASTANA')['current_stock'] == 9
