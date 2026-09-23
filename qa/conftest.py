"""Isolated acceptance fixtures; never call a running/shared server."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def make_data(*, days=84, quantity=10.0, stock=0.0, transit=0.0,
              lead=10, moq=0, pack=1, start="2026-01-01"):
    dates = pd.date_range(start, periods=days)
    return {
        "sales": pd.DataFrame({
            "date": dates, "sku": "QA-001", "product_name": "Test cable",
            "category": "Cables", "quantity": quantity, "price": 100,
            "customer_id": "REGULAR", "warehouse": "ASTANA",
        }),
        "stock": pd.DataFrame([{"sku": "QA-001", "warehouse": "ASTANA", "current_stock": stock}]),
        "transit": pd.DataFrame([{
            "sku": "QA-001", "warehouse": "ASTANA", "quantity_in_transit": transit,
            "expected_arrival_date": dates[-1] + pd.Timedelta(days=2),
        }]),
        "suppliers": pd.DataFrame([{
            "sku": "QA-001", "supplier_id": "QA-SUP", "supplier_name": "Test supplier",
            "lead_time_days": lead, "moq": moq, "package_size": pack,
        }]),
        "stockouts": pd.DataFrame(columns=["sku", "warehouse", "start_date", "end_date"]),
    }


@pytest.fixture
def dataset():
    return make_data()


@pytest.fixture
def api_factory(monkeypatch, tmp_path):
    """Use real routes and SQLite, but a tiny dataset and a disposable DB.

    Re-opening TestClient runs the real application startup again, allowing
    restart tests without touching a developer's stockpilot.db.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from app import main
    from app.repositories import database

    engine = create_engine(
        "sqlite:///" + (tmp_path / "qa.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(main, "state", main.AppState())
    monkeypatch.setattr(main, "build_demo_data", lambda: make_data(moq=24, pack=12))

    def create():
        return TestClient(main.app, raise_server_exceptions=False)

    yield create
    engine.dispose()


@pytest.fixture
def client(api_factory):
    with api_factory() as api:
        yield api
