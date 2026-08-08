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
OPTIONS_PAPER_STATE_PATH = DATA_ROOT / "options_paper_trading_state.json"
UPSTOX_INSTRUMENT_CACHE_PATH = DATA_ROOT / "upstox_instrument_cache.json"
UPSTOX_OPTION_INSTRUMENT_CACHE_PATH = DATA_ROOT / "upstox_option_instrument_cache.json"
UPSTOX_TOKEN_FILE = Path(os.getenv("UPSTOX_TOKEN_FILE", str(RUN_ROOT / "upstox-token.json")))

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8774
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"

NSE_HOME = "https://www.nseindia.com"
NSE_HEATMAP_URL = f"{NSE_HOME}/market-data/live-market-indices/heatmap"
NSE_LIVE_EQUITY_URL = f"{NSE_HOME}/market-data/live-equity-market?symbol=NIFTY%2050"
NSE_ALL_INDICES_API = f"{NSE_HOME}/api/allIndices"
NSE_STOCK_INDICES_API = f"{NSE_HOME}/api/NextApi/apiClient/marketWatchApi?functionName=getIndicesData"
NSE_QUOTE_EQUITY_API = f"{NSE_HOME}/api/quote-equity"
NSE_MARKET_STATUS_API = f"{NSE_HOME}/api/marketStatus"
NSE_HOLIDAY_API = f"{NSE_HOME}/api/holiday-master?type=trading"
NSE_TOP_GAINERS_LOSERS_URL = f"{NSE_HOME}/market-data/top-gainers-losers"
NSE_TOP_GAINERS_API = f"{NSE_HOME}/api/live-analysis-variations?index=gainers"
NSE_TOP_LOSERS_API = f"{NSE_HOME}/api/live-analysis-variations?index=loosers"

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
UPSTOX_OPTION_INSTRUMENT_OVERRIDES = os.getenv("UPSTOX_OPTION_INSTRUMENT_OVERRIDES", "").strip()
UPSTOX_MARKET_FEED_MODE = os.getenv("UPSTOX_MARKET_FEED_MODE", "ltpc").strip().lower()
UPSTOX_RECONNECT_SECONDS = int(os.getenv("UPSTOX_RECONNECT_SECONDS", "30") or "30")
MARKET_OPEN_TIME = dt.time(9, 0)
MARKET_CLOSE_TIME = dt.time(15, 31)

SECTOR_PICK_COUNT = 2
STOCKS_PER_SECTOR = 5
BUY_SECTOR_THRESHOLD = 0.5
SELL_SECTOR_THRESHOLD = -0.5

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
PAPER_SQUARE_OFF_MINUTE = 13
DAILY_STOCK_SL_LIMIT = 6
MIN_TRADE_RR = 1.5
PAPER_MOVE_SL_TO_BE = False
PAPER_BE_TRIGGER_RR = 2.0
PAPER_BE_LOCK_RR = 0.20
CLOSING_VOLUME_LOOKBACK_DAYS = int(os.getenv("CLOSING_VOLUME_LOOKBACK_DAYS", "20") or "20")
CLOSING_VOLUME_UNIVERSE = os.getenv("CLOSING_VOLUME_UNIVERSE", "NIFTY 500").strip() or "NIFTY 500"
CLOSING_VOLUME_TOP_COUNT = int(os.getenv("CLOSING_VOLUME_TOP_COUNT", "5") or "5")
CLOSING_VOLUME_SPIKE_MULTIPLE = float(os.getenv("CLOSING_VOLUME_SPIKE_MULTIPLE", "2.50") or "2.50")
CLOSING_VOLUME_MIN_DAILY_VOLUME_PCT = float(os.getenv("CLOSING_VOLUME_MIN_DAILY_VOLUME_PCT", "0.05") or "0.05")
CLOSING_VOLUME_MIN_BODY_PCT = float(os.getenv("CLOSING_VOLUME_MIN_BODY_PCT", "0.0015") or "0.0015")
CLOSING_VOLUME_ENTRY_WINDOW_MINUTES = int(os.getenv("CLOSING_VOLUME_ENTRY_WINDOW_MINUTES", "5") or "5")
CLOSING_VOLUME_MAX_RISK_PCT = float(os.getenv("CLOSING_VOLUME_MAX_RISK_PCT", "0.006") or "0.006")
CLOSING_VOLUME_TARGET_RR = float(os.getenv("CLOSING_VOLUME_TARGET_RR", "2.0") or "2.0")

# Editable defaults (change these values directly in config.py):
# - PAPER_ALLOW_INFLIGHT_CONFIRMATIONS_DEFAULT
#     When True, confirmations are considered valid from the candle start
#     (allows acting on a still-forming M5 candle). When False, confirmations
#     are only valid after the candle completes.
# - PAPER_ALLOW_CONFIRMATION_REUSE_DEFAULT
#     When True, the same M5 confirmation may trigger multiple trades (old behaviour).
#     When False, each confirmation is marked used and won't trigger new trades.
PAPER_ALLOW_INFLIGHT_CONFIRMATIONS_DEFAULT = True
PAPER_ALLOW_CONFIRMATION_REUSE_DEFAULT = True

# Environment-aware parsing helper. If you prefer env vars, set the literal
# strings 'true' or 'false' (case-insensitive). If unset or invalid, the
# defaults above are used.
def _env_bool_strict(key: str, default: bool = False) -> bool:
    """Parse an env var that must be the literal string 'true' or 'false'.

    Any other value (including '1' or '0') falls back to the provided default.
    """
    val = os.getenv(key)
    if val is None:
        return default
    s = str(val).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return default

# Final effective toggles (editable via the DEFAULT constants above or
# overridden at runtime with env vars PAPER_ALLOW_INFLIGHT_CONFIRMATIONS and
# PAPER_ALLOW_CONFIRMATION_REUSE set to 'true' or 'false').
PAPER_ALLOW_INFLIGHT_CONFIRMATIONS = _env_bool_strict(
    "PAPER_ALLOW_INFLIGHT_CONFIRMATIONS", PAPER_ALLOW_INFLIGHT_CONFIRMATIONS_DEFAULT
)

# Allow re-using the same M5 confirmation for multiple trades (old behaviour).
PAPER_ALLOW_CONFIRMATION_REUSE = _env_bool_strict(
    "PAPER_ALLOW_CONFIRMATION_REUSE", PAPER_ALLOW_CONFIRMATION_REUSE_DEFAULT
)

NIFTY_OPTIONS_INITIAL_CAPITAL = 500_000.0
NIFTY_OPTIONS_TRADE_ALLOCATION = float(os.getenv("NIFTY_OPTIONS_TRADE_ALLOCATION", "50000") or "50000")
NIFTY_OPTIONS_LOT_SIZE = int(os.getenv("NIFTY_OPTIONS_LOT_SIZE", "75") or "75")
NIFTY_OPTIONS_STRIKE_INTERVAL = int(os.getenv("NIFTY_OPTIONS_STRIKE_INTERVAL", "50") or "50")
NIFTY_OPTIONS_STRIKE_OFFSET_STEPS = int(os.getenv("NIFTY_OPTIONS_STRIKE_OFFSET_STEPS", "0") or "0")
NIFTY_OPTIONS_EXPIRY_WEEKDAY = int(os.getenv("NIFTY_OPTIONS_EXPIRY_WEEKDAY", "1") or "1")
NIFTY_OPTIONS_EXPIRY_SKIP_HOUR = int(os.getenv("NIFTY_OPTIONS_EXPIRY_SKIP_HOUR", "12") or "12")
NIFTY_OPTIONS_EXPIRY_SKIP_MINUTE = int(os.getenv("NIFTY_OPTIONS_EXPIRY_SKIP_MINUTE", "0") or "0")
NIFTY_OPTIONS_MIN_SECTOR_RATIO = float(os.getenv("NIFTY_OPTIONS_MIN_SECTOR_RATIO", "0.60") or "0.60")
NIFTY_OPTIONS_MIN_BREADTH = float(os.getenv("NIFTY_OPTIONS_MIN_BREADTH", "0.20") or "0.20")
NIFTY_OPTIONS_BREAKOUT_BUFFER = float(os.getenv("NIFTY_OPTIONS_BREAKOUT_BUFFER", "0.0005") or "0.0005")
NIFTY_OPTIONS_PREMIUM_SL_PCT = float(os.getenv("NIFTY_OPTIONS_PREMIUM_SL_PCT", "0.25") or "0.25")
NIFTY_OPTIONS_PREMIUM_TARGET_PCT = float(os.getenv("NIFTY_OPTIONS_PREMIUM_TARGET_PCT", "0.50") or "0.50")
NIFTY_OPTIONS_MIN_PREMIUM = float(os.getenv("NIFTY_OPTIONS_MIN_PREMIUM", "20") or "20")
NIFTY_OPTIONS_MAX_PREMIUM = float(os.getenv("NIFTY_OPTIONS_MAX_PREMIUM", "300") or "300")
NIFTY_OPTIONS_MAX_SPREAD_PCT = float(os.getenv("NIFTY_OPTIONS_MAX_SPREAD_PCT", "0.08") or "0.08")
NIFTY_OPTIONS_MIN_VOLUME = int(os.getenv("NIFTY_OPTIONS_MIN_VOLUME", "1000") or "1000")
NIFTY_OPTIONS_MIN_OI = int(os.getenv("NIFTY_OPTIONS_MIN_OI", "1000") or "1000")
NIFTY_OPTIONS_MAX_NEW_TRADES_PER_REFRESH = int(os.getenv("NIFTY_OPTIONS_MAX_NEW_TRADES_PER_REFRESH", "1") or "1")
NIFTY_OPTIONS_IDEA_RETENTION_SECONDS = int(os.getenv("NIFTY_OPTIONS_IDEA_RETENTION_SECONDS", "900") or "900")
OPENING_MOVER_OPTIONS_ENTRY_HOUR = int(os.getenv("OPENING_MOVER_OPTIONS_ENTRY_HOUR", "9") or "9")
OPENING_MOVER_OPTIONS_ENTRY_MINUTE = int(os.getenv("OPENING_MOVER_OPTIONS_ENTRY_MINUTE", "15") or "15")
OPENING_MOVER_OPTIONS_ENTRY_SECOND = int(os.getenv("OPENING_MOVER_OPTIONS_ENTRY_SECOND", "30") or "30")
OPENING_MOVER_OPTIONS_ENTRY_WINDOW_SECONDS = int(os.getenv("OPENING_MOVER_OPTIONS_ENTRY_WINDOW_SECONDS", "30") or "30")
OPENING_MOVER_OPTIONS_MAX_HOLD_MINUTES = int(os.getenv("OPENING_MOVER_OPTIONS_MAX_HOLD_MINUTES", "15") or "15")
OPENING_MOVER_OPTIONS_TOP_COUNT = int(os.getenv("OPENING_MOVER_OPTIONS_TOP_COUNT", "5") or "5")
OPENING_MOVER_OPTIONS_MAX_TRADES = int(os.getenv("OPENING_MOVER_OPTIONS_MAX_TRADES", "6") or "6")
OPENING_MOVER_OPTIONS_SL_PCT = float(os.getenv("OPENING_MOVER_OPTIONS_SL_PCT", "0.50") or "0.50")
OPENING_MOVER_OPTIONS_TARGET_MULTIPLE = float(os.getenv("OPENING_MOVER_OPTIONS_TARGET_MULTIPLE", "2.0") or "2.0")
NIFTY_OPTIONS_INDEXES = (
    {
        "symbol": "NIFTY",
        "name": "NIFTY 50",
        "nseSymbol": "NIFTY 50",
        "lotSize": 65,
        "strikeInterval": 50,
        "sectorSymbols": (),
        "enabled": True,
    },
    {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK",
        "nseSymbol": "NIFTY BANK",
        "lotSize": 30,
        "strikeInterval": 100,
        "sectorSymbols": ("NIFTY BANK", "NIFTY PVT BANK", "NIFTY PSU BANK"),
        "enabled": True,
    },
    {
        "symbol": "FINNIFTY",
        "name": "NIFTY FIN SERVICE",
        "nseSymbol": "NIFTY FIN SERVICE",
        "lotSize": 60,
        "strikeInterval": 50,
        "sectorSymbols": ("NIFTY FIN SERVICE", "NIFTY FINSRV25 50", "NIFTY FINSEREXBNK", "NIFTY MS FIN SERV"),
        "enabled": True,
    },
    {
        "symbol": "MIDCPNIFTY",
        "name": "NIFTY MIDCAP SELECT",
        "nseSymbol": "NIFTY MID SELECT",
        "lotSize": 120,
        "strikeInterval": 25,
        "sectorSymbols": ("NIFTY MID SELECT", "NIFTY MIDSML HLTH", "NIFTY MS FIN SERV", "NIFTY MS IT TELCM"),
        "enabled": True,
    },
    {
        "symbol": "NIFTYNXT50",
        "name": "NIFTY NEXT 50",
        "nseSymbol": "NIFTY NEXT 50",
        "lotSize": 25,
        "strikeInterval": 100,
        "sectorSymbols": ("NIFTY NEXT 50",),
        "enabled": True,
    },
)

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
