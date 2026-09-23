from __future__ import annotations

import numpy as np
import pandas as pd


def mad_outliers(values: pd.Series, threshold: float = 3.5) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0).astype(float)
    median = float(numeric.median())
    mad = float(np.median(np.abs(numeric - median)))
    if mad < 1e-9:
        return numeric > max(median * 4, median + 15)
    robust_z = 0.6745 * (numeric - median) / mad
    # A robust score is the primary signal; the size gate prevents ordinary
    # Poisson variation in low-volume SKUs from filling the audit trail.
    # A candidate must be both statistically extreme and materially larger
    # than the normal transaction scale (roughly 3.5x median or +4 MAD).
    size_gate = numeric > max(median * 3.5, median + max(10, 4 * mad))
    return (robust_z.abs() > threshold) & size_gate


def trend(values: pd.Series) -> tuple[str, float]:
    clean = pd.to_numeric(values, errors="coerce").fillna(0).astype(float)
    if len(clean) < 28 or clean.mean() <= 0:
        return "stable", 0.0
    weeks = clean.groupby(np.arange(len(clean)) // 7).sum()
    if len(weeks) < 4:
        return "stable", 0.0
    x = np.arange(len(weeks), dtype=float)
    slope = float(np.polyfit(x, weeks.to_numpy(), 1)[0])
    recent = float(weeks.tail(4).mean())
    prior = float(weeks.head(max(4, len(weeks) // 3)).mean())
    percent = ((recent / prior) - 1) * 100 if prior else 0
    if abs(percent) < 6 or abs(slope) < 0.01:
        return "stable", round(percent, 1)
    return ("growing" if slope > 0 else "declining"), round(percent, 1)


def forecast_series(history: pd.DataFrame, horizon: int, safety_days: int = 7) -> tuple[np.ndarray, dict]:
    values = history["adjusted_demand"].to_numpy(dtype=float)
    values = np.nan_to_num(values, nan=0.0)
    recent = values[-min(28, len(values)):]
    weights = np.linspace(1, 2, len(recent))
    base = float(np.average(recent, weights=weights)) if len(recent) else 0.0
    direction, trend_percent = trend(history["adjusted_demand"])
    
    seasonal_detected = False
    seasonal_dow_factor: dict[int, float] = {}
    seasonal_month_factor: dict[int, float] = {}
    
    work = history.copy()
    work["date"] = pd.to_datetime(work["date"])
    overall = float(work["adjusted_demand"].mean())
    
    # 1. Weekly seasonality (day of week)
    if len(history) >= 56 and overall > 0:
        work["dow"] = work["date"].dt.dayofweek
        by_day = work.groupby("dow")["adjusted_demand"].mean()
        if (by_day.max() - by_day.min()) / overall >= 0.15:
            seasonal_detected = True
            seasonal_dow_factor = {int(k): float(v / overall) for k, v in by_day.items()}
            
    # 2. Monthly / Annual seasonality (e.g. winter lighting spike, summer construction peak)
    if len(history) >= 120 and overall > 0:
        work["month"] = work["date"].dt.month
        by_month = work.groupby("month")["adjusted_demand"].mean()
        if len(by_month) >= 4 and (by_month.max() - by_month.min()) / overall >= 0.20:
            seasonal_detected = True
            seasonal_month_factor = {int(k): float(v / overall) for k, v in by_month.items()}

    if seasonal_month_factor:
        # Estimate trend after removing the calendar wave; otherwise an October
        # baseline incorrectly treats last winter's peak as a long decline.
        deseasonalized = work["adjusted_demand"] / work["date"].dt.month.map(seasonal_month_factor).fillna(1)
        direction, trend_percent = trend(deseasonalized)
    trend_factor = 1 + np.clip(trend_percent, -25, 35) / 100 * np.arange(1, horizon + 1) / max(horizon, 1)
            
    future_dates = pd.date_range(pd.to_datetime(history["date"].max()) + pd.Timedelta(days=1), periods=horizon, freq="D")
    forecast = base * trend_factor
    
    if seasonal_dow_factor:
        recent_factor = np.array([seasonal_dow_factor.get(int(d.dayofweek), 1.0) for d in work["date"].tail(len(recent))])
        forecast = forecast * np.array([seasonal_dow_factor.get(int(d.dayofweek), 1.0) for d in future_dates]) / max(float(np.average(recent_factor, weights=weights)), 0.01)
        
    if seasonal_month_factor:
        recent_factor = np.array([seasonal_month_factor.get(int(d.month), 1.0) for d in work["date"].tail(len(recent))])
        forecast = forecast * np.array([seasonal_month_factor.get(int(d.month), 1.0) for d in future_dates]) / max(float(np.average(recent_factor, weights=weights)), 0.01)
        
    model = "weighted_moving_average"
    if len(history) >= 180:
        model = "seasonal_weighted_moving_average" if seasonal_detected else "trend_weighted_moving_average"
        
    return np.maximum(forecast, 0), {
        "model": model,
        "trend_direction": direction,
        "trend_percent": trend_percent,
        "seasonality_detected": seasonal_detected,
        "average_daily_demand": round(base, 2),
    }
