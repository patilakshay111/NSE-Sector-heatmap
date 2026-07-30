from __future__ import annotations

import datetime as dt
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
DATA_ROOT = ROOT / "data"
PAPER_STATE_PATH = DATA_ROOT / "paper_trading_state.json"

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
MARKET_OPEN_TIME = dt.time(9, 0)
MARKET_CLOSE_TIME = dt.time(15, 31)

SECTOR_PICK_COUNT = 2
STOCKS_PER_SECTOR = 5
BUY_SECTOR_THRESHOLD = 1.0
SELL_SECTOR_THRESHOLD = -1.0

PAPER_INITIAL_CAPITAL = 1_000_000.0
PAPER_TRADE_ALLOCATION = 50_000.0
M5_SECONDS = 300
FRESH_CONFIRMATION_SECONDS = 10
VWAP_RETEST_TOLERANCE = 0.003
PAPER_START_HOUR = 9
PAPER_START_MINUTE = 20
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
