"""Generate small CSV packs for manual imports; contains no real customer data."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from conftest import make_data


def main():
    destination = Path(__file__).resolve().parent / "fixtures"
    cases = {}
    baseline = make_data(stock=20, transit=30, moq=24, pack=12)
    cases["01-baseline"] = (baseline, "Forecast 100; available 20; timely inbound 30; raw order 50; MOQ 24, pack 12; final order 60.")
    incoming = make_data(stock=20, transit=42, moq=24, pack=12)
    cases["02-more-inbound"] = (incoming, "Compared with baseline: raw order 38; final order 48.")
    lost = make_data(stock=20, transit=30, moq=24, pack=12)
    mask = lost["sales"]["date"].between("2026-03-01", "2026-03-16")
    lost["sales"] = lost["sales"].loc[~mask].reset_index(drop=True)
    lost["stockouts"] = pd.DataFrame([{
        "sku": "QA-001", "warehouse": "ASTANA", "start_date": "2026-03-01", "end_date": "2026-03-16",
    }])
    cases["03-missing-stockout"] = (lost, "No sales rows during 16 stockout days. Reconstruct lost demand 160; restored regular rate 10/day.")
    anomaly = make_data(stock=20, transit=30, moq=24, pack=12)
    anomaly["sales"].loc[70, ["quantity", "customer_id"]] = [4800, "PROJECT-CLIENT"]
    cases["04-project-order"] = (anomaly, "4800-unit order must be flagged, source preserved, regular forecast near 100 per 10 days.")
    late = make_data(stock=20, transit=1000, moq=24, pack=12)
    late["transit"]["expected_arrival_date"] = "2027-03-25"
    cases["05-late-inbound"] = (late, "Inbound arrives a year later; cannot cover next 10 days. Forecast 100, raw need 80, pack-rounded order 84.")
    invalid = make_data(stock=-100, transit=30, moq=24, pack=12)
    cases["06-invalid-stock"] = (invalid, "Load ONLY stock.csv over a valid baseline. Reject negative stock and preserve existing valid dataset.")
    for name, (tables, expected) in cases.items():
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        for key, frame in tables.items():
            frame.to_csv(folder / f"{key}.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
        manifest = {"as_of": "2026-03-26", "scenario": name, "expected": expected,
                    "rows": {key: len(frame) for key, frame in tables.items()},
                    "note": "Synthetic QA data. Use a disposable test instance; do not mix packs or demo tables."}
        (folder / "expected.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(folder)


if __name__ == "__main__":
    main()
