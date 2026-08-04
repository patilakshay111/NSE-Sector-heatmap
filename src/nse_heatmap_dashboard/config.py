from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path


# ============================================================
# PRICE DATA PROVIDER - change this first when switching mode.
#
# "nse"    = original mode. NSE polling prices decide entry/SL/TP.
# "upstox" = NSE only selects sectors/stocks; Upstox prices decide
#            entry, candles, SL/TP, and active trade monitoring.
#
# You can also override this for one terminal session:
#   $env:PRICE_DATA_PROVIDER = "upstox"
# ============================================================
PRICE_DATA_PROVIDER = os.getenv(
    "PRICE_DATA_PROVIDER",
    os.getenv("PRICE_STREAM_PROVIDER", "upstox"),
).strip().lower()
if PRICE_DATA_PROVIDER in {"nse_polling", "polling"}:
    PRICE_DATA_PROVIDER = "nse"
if PRICE_DATA_PROVIDER in {"upstox_websocket", "websocket"}:
    PRICE_DATA_PROVIDER = "upstox"
USE_UPSTOX_PRICE_DATA = PRICE_DATA_PROVIDER == "upstox"
PRICE_STREAM_PROVIDER = "upstox_websocket" if USE_UPSTOX_PRICE_DATA else "nse_polling"
UPSTOX_WEBSOCKET_ENABLED = USE_UPSTOX_PRICE_DATA


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
DATA_ROOT = ROOT / "data"
RUN_ROOT = ROOT / ".run"
PAPER_STATE_PATH = DATA_ROOT / "paper_trading_state.json"
UPSTOX_INSTRUMENT_CACHE_PATH = DATA_ROOT / "upstox_instrument_cache.json"
UPSTOX_TOKEN_FILE = Path(os.getenv("UPSTOX_TOKEN_FILE", str(RUN_ROOT / "upstox-token.json")))

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8775
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"

NSE_HOME = "https://www.nseindia.com"
NSE_HEATMAP_URL = f"{NSE_HOME}/market-data/live-market-indices/heatmap"
NSE_LIVE_EQUITY_URL = f"{NSE_HOME}/market-data/live-equity-market?symbol=NIFTY%2050"
NSE_ALL_INDICES_API = f"{NSE_HOME}/api/allIndices"
NSE_STOCK_INDICES_API = f"{NSE_HOME}/api/NextApi/apiClient/marketWatchApi?functionName=getIndicesData"
NSE_QUOTE_EQUITY_API = f"{NSE_HOME}/api/quote-equity"
NSE_MARKET_STATUS_API = f"{NSE_HOME}/api/marketStatus"
NSE_HOLIDAY_API = f"{NSE_HOME}/api/holiday-master?type=trading"

POLL_SECONDS = 3
IDLE_POLL_SECONDS = 300
UPSTOX_MAX_STREAM_SYMBOLS = int(os.getenv("UPSTOX_MAX_STREAM_SYMBOLS", "20") or "20")
UPSTOX_TOKEN_PREFERENCE = os.getenv("UPSTOX_TOKEN_PREFERENCE", "analytics").strip().lower()


def _upstox_token_file_value(*keys: str) -> str:
    try:
        payload = json.loads(UPSTOX_TOKEN_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


UPSTOX_ACCESS_TOKEN = (
    os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    or os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
    or (
        _upstox_token_file_value("analytics_token", "access_token")
        if UPSTOX_TOKEN_PREFERENCE == "analytics"
        else _upstox_token_file_value("access_token", "analytics_token")
    )
)
UPSTOX_API_BASE_URL = os.getenv("UPSTOX_API_BASE_URL", "https://api.upstox.com/v2").strip().rstrip("/")
UPSTOX_INSTRUMENT_OVERRIDES = os.getenv("UPSTOX_INSTRUMENT_OVERRIDES", "").strip()
UPSTOX_MARKET_FEED_MODE = os.getenv("UPSTOX_MARKET_FEED_MODE", "ltpc").strip().lower()
UPSTOX_RECONNECT_SECONDS = int(os.getenv("UPSTOX_RECONNECT_SECONDS", "30") or "30")
MARKET_OPEN_TIME = dt.time(9, 0)
MARKET_CLOSE_TIME = dt.time(15, 31)

SECTOR_PICK_COUNT = 2
STOCKS_PER_SECTOR = 5
BUY_SECTOR_THRESHOLD = 0.9
SELL_SECTOR_THRESHOLD = -0.9

PAPER_INITIAL_CAPITAL = 1_000_000.0
PAPER_TRADE_ALLOCATION = 50_000.0
M5_SECONDS = 300
FRESH_CONFIRMATION_SECONDS = 10
VWAP_RETEST_TOLERANCE = 0.003
SECTOR_MOMENTUM_BREAKOUT_BUFFER = 0.001
SECTOR_MOMENTUM_TARGET_RR = 2.0
SECTOR_MOMENTUM_MAX_RISK_PCT = 0.006
SECTOR_MOMENTUM_MAX_ENTRY_EXTENSION = 0.0015
SECTOR_MOMENTUM_RUNNER_ENABLED = True
SECTOR_MOMENTUM_PARTIAL_EXIT_RR = 2.0
SECTOR_MOMENTUM_PARTIAL_EXIT_PCT = 0.50
SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR = 0.25
PAPER_START_HOUR = 9
PAPER_START_MINUTE = 15
PAPER_SQUARE_OFF_HOUR = 15
PAPER_SQUARE_OFF_MINUTE = 30
DAILY_STOCK_SL_LIMIT = 3
MIN_TRADE_RR = 1.5
PAPER_MOVE_SL_TO_BE = False
PAPER_BE_TRIGGER_RR = 2.0
PAPER_BE_LOCK_RR = 0.20

SECTOR_KEYWORDS = {
    "AUTO",
    "BANK",
    "CAPITAL GOODS",
    "CEMENT",
    "CHEMICALS",
    "COMMERCIAL & TRANSPORT SERVICES",
    "CONSTRUCTION",
    "CONSUMER DURABLES",
    "CONSUMER SERVICES",
    "FINANCIAL SERVICES",
    "FMCG",
    "HEALTHCARE",
    "HOSPITALS",
    "HOUSING FINANCE",
    "INSURANCE",
    "IT",
    "MEDIA",
    "METAL",
    "MIDSML IT & TELECOM",
    "MIDSMALL FINANCIAL SERVICES",
    "MIDSMALL HEALTHCARE",
    "NBFC",
    "OIL & GAS",
    "PHARMA",
    "POWER",
    "PRIVATE BANK",
    "PSU BANK",
    "REALTY",
    "REITS & REALTY",
    "RETAIL",
    "TELECOMMUNICATION",
}
