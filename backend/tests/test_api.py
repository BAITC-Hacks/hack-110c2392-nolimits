from io import BytesIO

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app


def test_health_and_recommendations_api_are_available():
    with TestClient(app) as client:
        health = client.get('/health')
        recommendations = client.get('/api/recommendations')

    assert health.status_code == 200
    assert health.json()['status'] == 'ok'
    assert recommendations.status_code == 200
    body = recommendations.json()
    assert body['recommendations']
    assert body['summary']['critical_risks'] >= 0


def test_demo_endpoint_returns_calculated_result():
    with TestClient(app) as client:
        response = client.post('/api/data/demo')

    assert response.status_code == 200
    assert response.json()['recommendations'] > 0


def test_ekt_endpoint_loads_bundled_dataset_and_recalculates():
    with TestClient(app) as client:
        response = client.post('/api/data/load-ekt')
    assert response.status_code == 200
    body = response.json()
    assert body['datasets']['sales'] > 0
    assert body['recommendations'] > 0


def test_load_anomalies_endpoint_loads_and_recalculates():
    with TestClient(app) as client:
        response = client.post('/api/data/load-anomalies')
    assert response.status_code == 200
    body = response.json()
    assert body['datasets']['sales'] > 20000
    assert body['recommendations'] > 0
    assert body['outliers'] > 0


def test_orders_export_returns_csv_with_expected_headers():
    with TestClient(app) as client:
        response = client.get('/api/orders/export?format=csv')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/csv')
    assert 'SKU' in response.text
    assert 'Recommended Quantity' in response.text


def test_orders_export_rejects_unknown_format():
    with TestClient(app) as client:
        response = client.get('/api/orders/export?format=json')
    assert response.status_code == 400
    assert "csv" in response.json()['detail']


def test_editor_draft_and_product_crud_are_persistent():
    product = {'sku': 'EDITOR-1', 'product_name': 'Editor product', 'category': 'Tools', 'unit_price': 250, 'active': True}
    with TestClient(app) as client:
        draft = client.post('/api/editor/draft', json={'dataset': 'products', 'row': product})
        draft_read = client.get('/api/editor/draft')
        created = client.post('/api/editor/products/rows', json={'row': product})
        rows = client.get('/api/editor/products?search=EDITOR-1').json()
        row_id = rows['rows'][0]['row_id']
        updated = client.patch(f'/api/editor/products/rows/{row_id}', json={'row': {**product, 'product_name': 'Edited product'}})
        deleted = client.delete(f'/api/editor/products/rows/{row_id}')
        draft_after_save = client.get('/api/editor/draft')
    assert draft.status_code == 200
    assert draft_read.json()['draft']['row']['sku'] == 'EDITOR-1'
    assert created.status_code == 200
    assert updated.status_code == 200
    assert deleted.status_code == 200
    assert draft_after_save.json()['draft'] is None


def test_editor_dataset_export_returns_xlsx():
    with TestClient(app) as client:
        response = client.get('/api/editor/products/export?format=xlsx')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument')


def test_single_dataset_upload_recalculates_recommendations():
    sales_csv = b"date,sku,product_name,quantity,price,customer_id,warehouse,category\n2026-01-01,UPLOAD-1,Uploaded item,12,100,C1,WH-NORTH,Tools\n2026-01-02,UPLOAD-1,Uploaded item,14,100,C2,WH-NORTH,Tools\n"
    with TestClient(app) as client:
        client.post('/api/data/demo')
        response = client.post('/api/data/upload/sales', files={'file': ('sales.csv', sales_csv, 'text/csv')})
    assert response.status_code == 200
    body = response.json()
    assert body['rows_loaded'] == 2
    assert body['recommendations'] > 0


def test_workbook_upload_returns_sheet_validation_report():
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
        pd.DataFrame({'sku': ['BROKEN-1']}).to_excel(writer, index=False, sheet_name='sales')
    with TestClient(app) as client:
        response = client.post('/api/data/upload-workbook', files={'file': ('broken.xlsx', workbook.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 200
    assert any('sales:' in error and 'missing required' in error for error in response.json()['errors'])
