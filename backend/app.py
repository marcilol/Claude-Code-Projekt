"""Portfolio X-Ray backend — FastAPI app.

Run from project root:
    py -m uvicorn app:app --reload --app-dir backend --port 8000
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from baskets import basket_series, list_baskets, load_all_basket_returns, TIMEFRAME_DAYS
from factors import style_factor_series
from portfolio import analyze_portfolio
from zscores import combined_table, quadrant_data, ZSCORE_WINDOWS

app = FastAPI(title="Portfolio X-Ray", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def warm_caches():
    """Load baskets in the background so first user request is fast."""
    def _warm():
        try:
            n = len(load_all_basket_returns())
            print(f"[startup] basket cache primed: {n} baskets")
        except Exception as e:
            print(f"[startup] basket warmup failed: {e}")
    threading.Thread(target=_warm, daemon=True).start()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/factors/timeseries")
def factors_timeseries(timeframe: str = "1Y"):
    if timeframe not in TIMEFRAME_DAYS:
        raise HTTPException(400, f"timeframe must be one of {list(TIMEFRAME_DAYS)}")
    return style_factor_series(timeframe)


@app.get("/api/baskets")
def baskets_list():
    return {"baskets": list_baskets()}


@app.get("/api/baskets/timeseries")
def baskets_timeseries(
    timeframe: str = "1Y",
    keys: list[str] | None = Query(default=None),
):
    if timeframe not in TIMEFRAME_DAYS:
        raise HTTPException(400, f"timeframe must be one of {list(TIMEFRAME_DAYS)}")
    return basket_series(timeframe, keys)


@app.get("/api/zscores")
def zscores(window: int = 252):
    if window not in ZSCORE_WINDOWS:
        raise HTTPException(400, f"window must be one of {list(ZSCORE_WINDOWS)}")
    return combined_table(window)


@app.get("/api/quadrant")
def quadrant(kind: str = "factor"):
    if kind not in ("factor", "basket"):
        raise HTTPException(400, "kind must be 'factor' or 'basket'")
    return quadrant_data(kind)  # type: ignore[arg-type]


@app.get("/api/portfolio")
def portfolio():
    return analyze_portfolio()
