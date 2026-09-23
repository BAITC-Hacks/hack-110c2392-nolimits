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
