# StockPilot — explainable warehouse replenishment

Hackathon-ready MVP for purchasing managers. StockPilot combines sales history, inventory, inbound goods, supplier lead times and stockout windows to answer one question: **what should we order right now, and why?**

## Run locally

### Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API and Swagger UI are available at `http://localhost:8000/docs`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The backend starts with a deterministic demo dataset; use **Run demo scenario** to regenerate and calculate it.

## What is implemented

- CSV/XLSX import with required-column, date, numeric, duplicate, missing-SKU and constraint validation.
- Deterministic demo dataset: 105 SKUs, 3 warehouses, 5 suppliers, 15 months of history, seasonal/growing/declining/stable demand, stockouts, inbound goods and a deliberate one-off order.
- Robust MAD outlier detection preserves raw transactions and produces adjusted quantities and an audit trail.
- Stockout correction estimates lost demand from comparable non-stockout demand instead of treating stockout zeros as a decline.
- Forecast engine uses weighted recent demand, detects weekday seasonality with a minimum history threshold and applies a sustained trend signal.
- Replenishment formula: `target = forecast during lead time + service factor × demand std × √lead time`; `order = max(0, target − stock − inbound)`, then MOQ and package rounding.
- Deterministic explanations, audit metadata, urgency, days of cover and supplier grouping data.
- SQLite/SQLAlchemy audit repository stores calculation metadata plus draft/adjusted/approved order state.
- Dashboard with KPI cards, filters, sorting, demand chart, calculation trace, outlier audit page, drag-and-drop imports, CSV/XLSX export and explicit draft/adjust/approve workflow.
- Orders are never sent to suppliers automatically. Approval is an internal state change only.

## Tests

```powershell
cd backend
py -m pytest
```

Tests cover the monotonic impact of current stock and inbound goods, robust outlier handling and non-negative recommendations.

## API overview

`GET /health`, `POST /api/data/demo`, `POST /api/data/upload/{dataset}`, `POST /api/recommendations/calculate`, `GET /api/recommendations`, `GET /api/analytics/{sku}`, `GET /api/outliers`, `POST /api/orders/{id}/adjust`, `POST /api/orders/{id}/approve`, and `GET /api/orders/export?format=csv|xlsx`.
