"""Real API routes against a disposable in-process application and database."""
from io import BytesIO
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook


def first_order(client):
    response = client.get("/api/recommendations")
    assert response.status_code == 200, response.text
    return response.json()["recommendations"][0]


def path(row, action):
    return f'/api/orders/{quote(row["id"], safe="")}/{action}'


def test_A01_health_and_startup(client):
    assert client.get("/health").status_code == 200
    assert first_order(client)["status"] == "DRAFT"


@pytest.mark.parametrize("payload", [
    {"service_factor": -1}, {"safety_days": -1}, {"safety_days": 1000}, {"outlier_threshold": 0},
])
def test_A02_invalid_calculation_options_return_422(client, payload):
    assert client.post("/api/recommendations/calculate", json=payload).status_code == 422


def test_A03_all_invalid_upload_does_not_replace_good_data(client):
    from app import main
    before = main.state.datasets["stock"].copy(deep=True)
    response = client.post("/api/data/upload/stock", files={"file": ("bad.csv", b"sku,warehouse,current_stock\nQA-001,ASTANA,-100\n", "text/csv")})
    assert response.status_code < 500
    pd.testing.assert_frame_equal(main.state.datasets["stock"], before, check_dtype=False)


def test_A04_malformed_file_preserves_state(client):
    before = client.get("/api/data/status").json()
    response = client.post("/api/data/upload/stock", files={"file": ("broken.xlsx", b"not an xlsx", "application/octet-stream")})
    assert response.status_code == 400
    assert client.get("/api/data/status").json() == before


def test_A05_unknown_dataset_returns_404(client):
    assert client.post("/api/data/upload/unknown", files={"file": ("x.csv", b"sku\nx\n")}).status_code == 404


def test_A06_recalculation_preserves_approved_decision(client):
    row = first_order(client)
    assert client.post(path(row, "adjust"), json={"final_quantity": 36}).status_code == 200
    assert client.post(path(row, "approve")).status_code == 200
    assert client.post("/api/recommendations/calculate", json={}).status_code == 200
    after = first_order(client)
    assert (after["status"], after["final_quantity"]) == ("APPROVED", 36), after


def test_A07_restart_restores_approved_decision(api_factory):
    with api_factory() as client:
        row = first_order(client)
        assert client.post(path(row, "adjust"), json={"final_quantity": 36}).status_code == 200
        assert client.post(path(row, "approve")).status_code == 200
    with api_factory() as restarted:
        row = first_order(restarted)
        assert (row["status"], row["final_quantity"]) == ("APPROVED", 36), row


@pytest.mark.parametrize("quantity", [-1, 1, 25, 24.5])
def test_A08_final_order_constraints_are_enforced(client, quantity):
    row = first_order(client)
    response = client.post(path(row, "adjust"), json={"final_quantity": quantity})
    # An invalid draft is allowed if approval is blocked. The final order must
    # respect MOQ=24, pack=12; a non-negative input alone is insufficient.
    if response.status_code in {400, 409, 422}:
        return
    assert response.status_code == 200, response.text
    approved = client.post(path(row, "approve"))
    assert approved.status_code in {400, 409, 422}, approved.text


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_A09_export_uses_final_approved_quantity(client, fmt):
    row = first_order(client)
    client.post(path(row, "adjust"), json={"final_quantity": 36})
    client.post(path(row, "approve"))
    response = client.get("/api/orders/export", params={"format": fmt})
    assert response.status_code == 200, response.text[:300]
    frame = pd.read_csv(BytesIO(response.content)) if fmt == "csv" else pd.read_excel(BytesIO(response.content))
    assert frame.iloc[0]["Recommended Quantity"] == 36
    assert frame.iloc[0]["Status"] == "APPROVED"


def test_A10_order_kpi_matches_final_quantities(client):
    row = first_order(client)
    client.post(path(row, "adjust"), json={"final_quantity": 36})
    body = client.get("/api/recommendations").json()
    assert body["summary"]["total_recommended_units"] == sum(r["final_quantity"] for r in body["recommendations"])


def test_A11_excel_product_name_is_literal_not_formula(client):
    from app import main
    main.state.recommendations[0]["product_name"] = "=1+1"
    response = client.get("/api/orders/export?format=xlsx")
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content), data_only=False)
    assert book.active["B2"].data_type != "f", "User-supplied product name became an Excel formula"


def test_A12_unknown_order_returns_404(client):
    assert client.post("/api/orders/not-found/approve").status_code == 404


def test_A13_approval_is_idempotent(client):
    row = first_order(client)
    first = client.post(path(row, "approve"))
    second = client.post(path(row, "approve"))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_A14_chart_forecast_reconciles_with_engine(client):
    from app import main
    sales = main.state.datasets["sales"]
    sales["quantity"] = np.linspace(10, 40, len(sales))
    response = client.post("/api/recommendations/calculate", json={})
    assert response.status_code == 200, response.text
    row = first_order(client)
    response = client.get(f'/api/analytics/{row["sku"]}', params={"warehouse": row["warehouse"]})
    assert response.status_code == 200, response.text
    forecast = [point["forecast"] for point in response.json()["points"] if point.get("forecast") is not None]
    assert sum(forecast[:row["lead_time_days"]]) == pytest.approx(row["forecast_lead_time"], abs=0.2)


def test_A15_chart_contains_missing_stockout_dates(client):
    from app import main
    sales = main.state.datasets["sales"]
    affected = sales["date"].between("2026-03-01", "2026-03-16")
    main.state.datasets["sales"] = sales.loc[~affected].reset_index(drop=True)
    main.state.datasets["stockouts"] = pd.DataFrame([{
        "sku": "QA-001", "warehouse": "ASTANA", "start_date": "2026-03-01", "end_date": "2026-03-16",
    }])
    client.post("/api/recommendations/calculate", json={})
    response = client.get("/api/analytics/QA-001?warehouse=ASTANA")
    assert response.status_code == 200, response.text
    marked = [p for p in response.json()["points"] if p.get("is_stockout")]
    assert len(marked) == 16
    assert all(p["adjusted_demand"] > 0 for p in marked)


def test_A16_duplicate_approval_does_not_create_extra_export_rows(client):
    row = first_order(client)
    for _ in range(3):
        assert client.post(path(row, "approve")).status_code == 200
    exported = pd.read_csv(BytesIO(client.get("/api/orders/export?format=csv").content))
    assert len(exported) == 1


def test_A17_russian_sales_csv_is_supported(client):
    stock = pd.DataFrame([{
        "Артикул": "EKT-CBL-001", "Склад": "Склад Астана (Главный РЦ)",
        "Доступный_остаток": 20,
    }])
    prepared = client.post("/api/data/upload/stock", files={
        "file": ("current_stock.csv", stock.to_csv(index=False).encode("utf-8-sig"), "text/csv"),
    })
    assert prepared.status_code == 200 and prepared.json()["rows_loaded"] == 1, prepared.text
    frame = pd.DataFrame([{
        "Дата_продажи": "2026-08-31", "Артикул": "EKT-CBL-001",
        "Наименование_товара": "Кабель", "Категория": "Кабель и провод",
        "Количество": 10, "Цена_за_ед_KZT": 100, "ID_Клиента": "CLNT-1000",
        "Склад_отгрузки": "Склад Астана (Главный РЦ)",
    }])
    response = client.post("/api/data/upload/sales", files={
        "file": ("sales_history.csv", frame.to_csv(index=False).encode("utf-8-sig"), "text/csv"),
    })
    assert response.status_code == 200, response.text
    assert response.json()["rows_loaded"] == 1, response.text
    assert not response.json()["errors"], response.text


def test_A18_invalid_numeric_upload_cannot_break_calculation(client):
    response = client.post("/api/data/upload/stock", files={
        "file": ("bad.csv", b"sku,warehouse,current_stock\nQA-001,ASTANA,inf\n", "text/csv"),
    })
    assert response.status_code < 500
    calculated = client.post("/api/recommendations/calculate", json={})
    assert calculated.status_code < 500, calculated.text


def test_A19_empty_stockout_upload_clears_previous_windows(client):
    from app import main
    main.state.datasets["stockouts"] = pd.DataFrame([{
        "sku": "QA-001", "warehouse": "ASTANA", "start_date": "2026-03-01", "end_date": "2026-03-16",
    }])
    response = client.post("/api/data/upload/stockouts", files={
        "file": ("stockouts.csv", b"sku,warehouse,start_date,end_date\n", "text/csv"),
    })
    assert response.status_code == 200, response.text
    assert not response.json()["errors"], response.text
    assert main.state.datasets["stockouts"].empty, "Successful empty replacement kept the previous stockout windows"


def test_A21_budget_tracks_final_order_quantity(client):
    from app import main

    main.state.datasets["suppliers"].loc[0, "unit_cost"] = 1000
    calculated = client.post("/api/recommendations/calculate", json={})
    assert calculated.status_code == 200, calculated.text
    row = first_order(client)
    assert row["unit_cost"] == 1000
    assert row["total_cost_kzt"] == row["recommended_quantity"] * 1000

    changed = client.post(path(row, "adjust"), json={"final_quantity": 36})
    assert changed.status_code == 200, changed.text
    body = client.get("/api/recommendations").json()
    assert body["recommendations"][0]["total_cost_kzt"] == 36000
    assert body["summary"]["total_budget_kzt"] == 36000
