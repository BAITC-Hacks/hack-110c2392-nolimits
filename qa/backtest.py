"""Bounded walk-forward check on synthetic series, not a production accuracy claim.

Run from the repo root: python qa/backtest.py
Each forecast is fitted only on the prefix before its cutoff. Compare the model
against a plain trailing-28-day mean on exactly the same withheld dates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.forecasting import forecast_series


def evaluate() -> dict:
    dates = pd.date_range('2024-01-01', periods=730)
    time = np.arange(len(dates))
    cases = {
        'constant': np.full(len(dates), 20.0),
        'weekly': np.where(dates.dayofweek < 5, 30.0, 8.0),
        'gradual_growth': 10.0 + time * 0.035,
        'winter_season': np.where(dates.month.isin([11, 12, 1, 2]), 165.0, 100.0),
    }
    horizon = 14
    cutoffs = [120, 210, 300, 390, 480, 570, 660]
    records = []
    for name, demand in cases.items():
        actuals, predictions, baselines = [], [], []
        for cutoff in cutoffs:
            history = pd.DataFrame({'date': dates[:cutoff], 'adjusted_demand': demand[:cutoff]})
            prediction, _ = forecast_series(history, horizon)
            actuals.extend(demand[cutoff:cutoff + horizon])
            predictions.extend(prediction)
            baselines.extend([float(demand[max(0, cutoff - 28):cutoff].mean())] * horizon)
        actual = np.array(actuals)
        def metrics(pred):
            errors = np.array(pred) - actual
            return {
                'mae': round(float(np.abs(errors).mean()), 4),
                'wape_percent': round(float(np.abs(errors).sum() / actual.sum() * 100), 4),
                'bias_percent': round(float(errors.sum() / actual.sum() * 100), 4),
            }
        records.append({'scenario': name, 'forecast_points': len(actual), 'model': metrics(predictions), 'trailing_mean_baseline': metrics(baselines)})
    return {
        'data': 'deterministic synthetic series; no real customer data',
        'method': '7 walk-forward cutoffs per series, 14 held-out days; training uses only earlier dates',
        'limitation': 'Diagnostic only. No guarantee on partner data; annual seasonality before an observed cycle remains uncertain.',
        'results': records,
    }


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2))
