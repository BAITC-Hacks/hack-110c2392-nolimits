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
    assert body['datasets']['sales'] > 0
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
