from __future__ import annotations

import numpy as np
import pandas as pd


def mad_outliers(values: pd.Series, threshold: float = 3.5) -> pd.Series:
    numeric = pd.to_numeric(values, errors='coerce').fillna(0).astype(float)
    median = float(numeric.median())
    mad = float(np.median(np.abs(numeric - median)))
    if mad < 1e-9:
        return (numeric > np.maximum(median * 4, median + 10))
    robust_z = 0.6745 * (numeric - median) / mad
    # A robust score is the primary signal; the size gate prevents ordinary
    # Poisson variation in low-volume SKUs from filling the audit trail.
    size_gate = (numeric > median * 2.5) | (numeric > median + max(5, 3 * mad))
    return (robust_z.abs() > threshold) & size_gate


def trend(values: pd.Series) -> tuple[str, float]:
    clean = pd.to_numeric(values, errors='coerce').fillna(0).astype(float)
    if len(clean) < 28 or clean.mean() <= 0:
        return 'stable', 0.0
    weeks = clean.groupby(np.arange(len(clean)) // 7).sum()
    if len(weeks) < 4:
        return 'stable', 0.0
    x = np.arange(len(weeks), dtype=float)
    slope = float(np.polyfit(x, weeks.to_numpy(), 1)[0])
    recent = float(weeks.tail(4).mean())
    prior = float(weeks.head(max(4, len(weeks) // 3)).mean())
    percent = ((recent / prior) - 1) * 100 if prior else 0
    if abs(percent) < 6 or abs(slope) < 0.01:
        return 'stable', round(percent, 1)
    return ('growing' if slope > 0 else 'declining'), round(percent, 1)


def forecast_series(history: pd.DataFrame, horizon: int, safety_days: int = 7) -> tuple[np.ndarray, dict]:
    values = history['adjusted_demand'].to_numpy(dtype=float)
    values = np.nan_to_num(values, nan=0.0)
    recent = values[-min(28, len(values)):]
    weights = np.linspace(1, 2, len(recent))
    base = float(np.average(recent, weights=weights)) if len(recent) else 0.0
    direction, trend_percent = trend(history['adjusted_demand'])
    trend_factor = 1 + np.clip(trend_percent, -25, 35) / 100 * np.arange(1, horizon + 1) / max(horizon, 1)
    seasonal_detected = False
    seasonal_factor: dict[int, float] = {}
    if len(history) >= 56:
        work = history.copy()
        work['dow'] = pd.to_datetime(work['date']).dt.dayofweek
        by_day = work.groupby('dow')['adjusted_demand'].mean()
        overall = float(work['adjusted_demand'].mean())
        if overall > 0 and (by_day.max() - by_day.min()) / overall >= 0.15:
            seasonal_detected = True
            seasonal_factor = {int(k): float(v / overall) for k, v in by_day.items()}
    future_dates = pd.date_range(pd.to_datetime(history['date'].max()) + pd.Timedelta(days=1), periods=horizon, freq='D')
    forecast = base * trend_factor
    if seasonal_detected:
        forecast = forecast * np.array([seasonal_factor.get(int(d.dayofweek), 1.0) for d in future_dates])
    model = 'weighted_moving_average'
    if len(history) >= 180:
        model = 'seasonal_weighted_moving_average' if seasonal_detected else 'trend_weighted_moving_average'
    return np.maximum(forecast, 0), {'model': model, 'trend_direction': direction, 'trend_percent': trend_percent, 'seasonality_detected': seasonal_detected, 'average_daily_demand': round(base, 2)}
