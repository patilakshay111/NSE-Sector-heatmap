from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import datetime as dt
from http import cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import threading
import time
from typing import Any
from urllib import error, parse, request
import webbrowser

from .config import (
    BUY_SECTOR_THRESHOLD,
    CLOSING_VOLUME_ENTRY_WINDOW_MINUTES,
    CLOSING_VOLUME_LOOKBACK_DAYS,
    CLOSING_VOLUME_MAX_RISK_PCT,
    CLOSING_VOLUME_MIN_BODY_PCT,
    CLOSING_VOLUME_MIN_DAILY_VOLUME_PCT,
    CLOSING_VOLUME_SPIKE_MULTIPLE,
    CLOSING_VOLUME_TARGET_RR,
    CLOSING_VOLUME_TOP_COUNT,
    CLOSING_VOLUME_UNIVERSE,
    DAILY_STOCK_SL_LIMIT,
    DATA_ROOT,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_URL,
    FRESH_CONFIRMATION_SECONDS,
    IDLE_POLL_SECONDS,
    M5_SECONDS,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
    MIN_TRADE_RR,
    NIFTY_OPTIONS_BREAKOUT_BUFFER,
    NIFTY_OPTIONS_EXPIRY_SKIP_HOUR,
    NIFTY_OPTIONS_EXPIRY_SKIP_MINUTE,
    NIFTY_OPTIONS_EXPIRY_WEEKDAY,
    NIFTY_OPTIONS_INITIAL_CAPITAL,
    NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
    NIFTY_OPTIONS_LOT_SIZE,
    NIFTY_OPTIONS_MAX_PREMIUM,
    NIFTY_OPTIONS_MAX_NEW_TRADES_PER_REFRESH,
    NIFTY_OPTIONS_MAX_SPREAD_PCT,
    NIFTY_OPTIONS_INDEXES,
    NIFTY_OPTIONS_MIN_BREADTH,
    NIFTY_OPTIONS_MIN_OI,
    NIFTY_OPTIONS_MIN_PREMIUM,
    NIFTY_OPTIONS_MIN_SECTOR_RATIO,
    NIFTY_OPTIONS_MIN_VOLUME,
    NIFTY_OPTIONS_PREMIUM_SL_PCT,
    NIFTY_OPTIONS_PREMIUM_TARGET_PCT,
    NIFTY_OPTIONS_STRIKE_INTERVAL,
    NIFTY_OPTIONS_STRIKE_OFFSET_STEPS,
    NIFTY_OPTIONS_TRADE_ALLOCATION,
    OPENING_MOVER_OPTIONS_ENTRY_HOUR,
    OPENING_MOVER_OPTIONS_ENTRY_MINUTE,
    OPENING_MOVER_OPTIONS_ENTRY_SECOND,
    OPENING_MOVER_OPTIONS_ENTRY_WINDOW_SECONDS,
    OPENING_MOVER_OPTIONS_MAX_HOLD_MINUTES,
    OPENING_MOVER_OPTIONS_MAX_TRADES,
    OPENING_MOVER_OPTIONS_SL_PCT,
    OPENING_MOVER_OPTIONS_TARGET_MULTIPLE,
    OPENING_MOVER_OPTIONS_TOP_COUNT,
    NSE_ALL_INDICES_API,
    NSE_HEATMAP_URL,
    NSE_HOLIDAY_API,
    NSE_HOME,
    NSE_LIVE_EQUITY_URL,
    NSE_MARKET_STATUS_API,
    NSE_QUOTE_EQUITY_API,
    NSE_STOCK_INDICES_API,
    NSE_TOP_GAINERS_API,
    NSE_TOP_GAINERS_LOSERS_URL,
    NSE_TOP_LOSERS_API,
    PAPER_BE_LOCK_RR,
    PAPER_BE_TRIGGER_RR,
    PAPER_INITIAL_CAPITAL,
    PAPER_MOVE_SL_TO_BE,
    PAPER_SQUARE_OFF_HOUR,
    PAPER_SQUARE_OFF_MINUTE,
    PAPER_START_HOUR,
    PAPER_START_MINUTE,
    PAPER_STATE_PATH,
    PAPER_TRADE_ALLOCATION,
    OPTIONS_PAPER_STATE_PATH,
    PRICE_DATA_PROVIDER,
    POLL_SECONDS,
    PRICE_STREAM_PROVIDER,
    SECTOR_MOMENTUM_BREAKOUT_BUFFER,
    SECTOR_MOMENTUM_MAX_ENTRY_EXTENSION,
    SECTOR_MOMENTUM_MAX_RISK_PCT,
    SECTOR_MOMENTUM_PARTIAL_EXIT_PCT,
    SECTOR_MOMENTUM_PARTIAL_EXIT_RR,
    SECTOR_MOMENTUM_RUNNER_ENABLED,
    SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR,
    SECTOR_MOMENTUM_TARGET_RR,
    SECTOR_KEYWORDS,
    SECTOR_PICK_COUNT,
    SELL_SECTOR_THRESHOLD,
    STATIC_ROOT,
    STOCKS_PER_SECTOR,
    UPSTOX_ACCESS_TOKEN,
    UPSTOX_API_BASE_URL,
    UPSTOX_INSTRUMENT_CACHE_PATH,
    UPSTOX_INSTRUMENT_OVERRIDES,
    UPSTOX_MAX_STREAM_SYMBOLS,
    UPSTOX_MARKET_FEED_MODE,
    UPSTOX_OPTION_INSTRUMENT_CACHE_PATH,
    UPSTOX_OPTION_INSTRUMENT_OVERRIDES,
    UPSTOX_RECONNECT_SECONDS,
    UPSTOX_WEBSOCKET_ENABLED,
    USE_UPSTOX_PRICE_DATA,
    VWAP_RETEST_TOLERANCE,
)


def _now_label() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


def _date_key(value: dt.date) -> str:
    return value.isoformat()


def _trade_date_key(trade: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = str(trade.get(field) or "")
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return value[:10]
    return ""


def _valid_date_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _parse_nse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_iso_datetime(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _candle_row(candle: Any) -> dict[str, Any] | None:
    if not isinstance(candle, list) or len(candle) < 6:
        return None
    candle_dt = _parse_iso_datetime(candle[0])
    open_price = _to_float(candle[1])
    high = _to_float(candle[2])
    low = _to_float(candle[3])
    close = _to_float(candle[4])
    volume = _to_float(candle[5])
    if candle_dt is None or open_price is None or high is None or low is None or close is None or volume is None:
        return None
    return {
        "timestamp": str(candle[0] or ""),
        "datetime": candle_dt,
        "date": candle_dt.date(),
        "time": candle_dt.time(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text.lower() in {"-", "none", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _to_float(value)
        if number is not None:
            return number
    return None


class AppLog:
    def __init__(self, limit: int = 300) -> None:
        self.rows: deque[dict[str, Any]] = deque(maxlen=limit)
        self.lock = threading.RLock()

    def info(self, message: str, **fields: Any) -> None:
        self.add("INFO", message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        self.add("WARN", message, **fields)

    def add(self, level: str, message: str, **fields: Any) -> None:
        with self.lock:
            self.rows.appendleft(
                {
                    "time": _now_label(),
                    "level": level,
                    "message": message,
                    "fields": fields,
                }
            )

    def latest(self, limit: int = 120) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.rows)[:limit]


def _clean_index_symbol(symbol: str) -> str:
    return " ".join(str(symbol or "").replace("NIFTY", "NIFTY ").split())


def _is_sector_index(item: dict[str, Any]) -> bool:
    key = str(item.get("key") or item.get("indexType") or "").upper()
    symbol = _clean_index_symbol(str(item.get("indexSymbol") or item.get("index") or "")).upper()
    if key == "SECTORAL INDICES":
        return True
    return symbol in {"NIFTY BANK", "NIFTY FIN SERVICE"}

def _sector_row(item: dict[str, Any]) -> dict[str, Any]:
    percent = _to_float(item.get("percentChange") or item.get("perChange") or item.get("pChange"))
    change = _to_float(item.get("variation") or item.get("change"))
    last = _to_float(item.get("last") or item.get("lastPrice") or item.get("ltp"))
    previous = _to_float(item.get("previousClose") or item.get("previous"))
    advances = _to_float(item.get("advances"))
    declines = _to_float(item.get("declines"))
    unchanged = _to_float(item.get("unchanged"))
    total = (advances or 0) + (declines or 0) + (unchanged or 0)
    breadth = ((advances or 0) - (declines or 0)) / total if total else None
    return {
        "symbol": _clean_index_symbol(str(item.get("indexSymbol") or item.get("index") or "-")),
        "last": last,
        "change": change,
        "percentChange": percent,
        "previousClose": previous,
        "open": _to_float(item.get("open")),
        "high": _to_float(item.get("high")),
        "low": _to_float(item.get("low")),
        "advances": int(advances or 0),
        "declines": int(declines or 0),
        "unchanged": int(unchanged or 0),
        "breadth": breadth,
        "rawKey": item.get("key") or item.get("indexType") or "",
    }


def _index_row(item: dict[str, Any], fallback_symbol: str = "-") -> dict[str, Any]:
    return {
        "symbol": _clean_index_symbol(str(item.get("indexSymbol") or item.get("index") or fallback_symbol)),
        "last": _first_float(item.get("last"), item.get("lastPrice"), item.get("ltp")),
        "change": _first_float(item.get("variation"), item.get("change")),
        "percentChange": _first_float(item.get("percentChange"), item.get("perChange"), item.get("pChange")),
        "previousClose": _first_float(item.get("previousClose"), item.get("previous")),
        "open": _first_float(item.get("open")),
        "high": _first_float(item.get("high")),
        "low": _first_float(item.get("low")),
        "vwap": _first_float(item.get("vwap"), item.get("averagePrice")),
        "lastUpdateTime": item.get("lastUpdateTime") or item.get("lastUpdate") or "",
    }


def _quote_price_info(quote_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(quote_payload, dict):
        return {}
    price_info = quote_payload.get("priceInfo")
    return price_info if isinstance(price_info, dict) else {}


def _derived_vwap(item: dict[str, Any]) -> float | None:
    traded_value = _to_float(item.get("totalTradedValue") or item.get("tradedValue"))
    volume = _to_float(item.get("totalTradedVolume") or item.get("volume"))
    if not traded_value or not volume:
        return None
    vwap = traded_value / volume
    return vwap if 0 < vwap < 1_000_000 else None


def _stock_row(
    item: dict[str, Any],
    sector_symbol: str,
    direction: str,
    quote_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    price_info = _quote_price_info(quote_payload)
    high_low = price_info.get("intraDayHighLow") if isinstance(price_info.get("intraDayHighLow"), dict) else {}
    symbol = str(item.get("symbol") or item.get("identifier") or "-").strip()
    last_price = _first_float(price_info.get("lastPrice"), item.get("lastPrice"), item.get("ltp"), item.get("last"))
    change = _first_float(price_info.get("change"), item.get("change"), item.get("netChange"))
    percent_change = _first_float(price_info.get("pChange"), item.get("pChange"), item.get("perChange"), item.get("percentChange"))
    return {
        "sector": sector_symbol,
        "direction": direction,
        "symbol": symbol,
        "name": item.get("meta", {}).get("companyName") if isinstance(item.get("meta"), dict) else item.get("companyName") or "",
        "open": _first_float(price_info.get("open"), item.get("open")),
        "current": last_price,
        "vwap": _first_float(price_info.get("vwap"), item.get("vwap"), item.get("averagePrice"), _derived_vwap(item)),
        "change": change,
        "percentChange": percent_change,
        "previousClose": _first_float(price_info.get("previousClose"), item.get("previousClose")),
        "high": _first_float(high_low.get("max"), item.get("dayHigh"), item.get("high")),
        "low": _first_float(high_low.get("min"), item.get("dayLow"), item.get("low")),
        "volume": _first_float(item.get("totalTradedVolume"), item.get("volume")),
        "lastUpdateTime": item.get("lastUpdateTime") or item.get("lastUpdate") or "",
        "dataSource": "NSE quote-equity" if quote_payload else "NSE sector constituent feed",
        "priceIsMock": False,
    }


def _stock_row_from_quote(symbol: str, quote_payload: dict[str, Any]) -> dict[str, Any]:
    info = quote_payload.get("info") if isinstance(quote_payload.get("info"), dict) else {}
    price_info = _quote_price_info(quote_payload)
    return _stock_row(
        {
            "symbol": info.get("symbol") or symbol,
            "companyName": info.get("companyName") or info.get("companyName2") or "",
            "lastUpdateTime": quote_payload.get("lastUpdateTime") or price_info.get("lastUpdateTime") or "",
        },
        "ACTIVE PAPER TRADE",
        "mark",
        quote_payload,
    )


def _round_price(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _risk_reward(side: str, entry: float, stop_loss: float, target: float) -> float | None:
    if side == "BUY":
        risk = entry - stop_loss
        reward = target - entry
    else:
        risk = stop_loss - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _trade_pnl(side: str, entry: float, price: float, quantity: int) -> float:
    if side == "BUY":
        return (price - entry) * quantity
    return (entry - price) * quantity


def _long_pnl(entry: float, price: float, quantity: int) -> float:
    return (price - entry) * quantity


def _is_transient_socket_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException) and reason is not exc:
        return _is_transient_socket_error(reason)
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    return winerror in {10053, 10054, 10060} or errno in {10053, 10054, 10060}


class PaperTradingEngine:
    def __init__(self) -> None:
        self.initial_capital = PAPER_INITIAL_CAPITAL
        self.trade_allocation = PAPER_TRADE_ALLOCATION
        self.realized_pnl = 0.0
        self.candles: dict[str, list[dict[str, Any]]] = {}
        self.active_trades: dict[str, dict[str, Any]] = {}
        self.closed_trades: list[dict[str, Any]] = []
        self.fib_watch: dict[str, dict[str, Any]] = {}
        self.closing_volume_shortlist: dict[str, Any] = {}
        self.used_confirmations: dict[str, int] = {}
        self.next_trade_id = 1
        self.last_ideas: list[dict[str, Any]] = []
        self.last_ideas_date: str | None = None
        self.last_saved_at: str | None = None
        self.persistence_error: str | None = None
        self._load()

    def update(
        self,
        stock_groups: list[dict[str, Any]],
        market_open: bool = True,
        mark_stocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        stocks = self._selected_stocks(stock_groups)
        mark_stocks = self._merge_mark_stocks(stocks, mark_stocks or [])
        closing_volume_stocks = self._closing_volume_live_stocks(mark_stocks)
        now = time.time()
        entry_session_open = self._entry_session_is_open(now)
        square_off_due = self._square_off_due(now)
        if market_open:
            self._mark_active_trades(mark_stocks)
            if square_off_due:
                self._square_off_open_trades()
        if not market_open or not entry_session_open:
            self._clear_last_ideas()
            self._persist()
            return self.snapshot()
        for stock in stocks:
            self._update_candle(stock, now)
        self._mark_active_trades(mark_stocks)
        ideas = self._build_ideas(stocks, now)
        ideas.extend(self._closing_volume_ideas(closing_volume_stocks, now))
        self._activate_ready_ideas(ideas)
        self._mark_active_trades(mark_stocks)
        self.last_ideas = ideas
        self.last_ideas_date = _today_key()
        self._persist()
        return self.snapshot()

    def active_symbols(self) -> set[str]:
        return {str(trade.get("symbol") or "").strip() for trade in self.active_trades.values() if trade.get("symbol")}

    def active_mark_targets(self) -> dict[str, str]:
        return {
            str(trade.get("symbol") or "").strip(): str(trade.get("sector") or "").strip()
            for trade in self.active_trades.values()
            if trade.get("symbol")
        }

    def set_closing_volume_shortlist(self, shortlist: dict[str, Any]) -> None:
        if not isinstance(shortlist, dict):
            return
        self.closing_volume_shortlist = shortlist
        self._persist()

    def closing_volume_mark_targets(self, target_date: dt.date | None = None) -> dict[str, str]:
        target_key = _date_key(target_date or dt.date.today())
        if self.closing_volume_shortlist.get("targetDate") != target_key:
            return {}
        if self.closing_volume_shortlist.get("universe") != CLOSING_VOLUME_UNIVERSE:
            return {}
        rows = self.closing_volume_shortlist.get("selected")
        if not isinstance(rows, list):
            return {}
        return {
            str(row.get("symbol") or "").strip().upper(): f"Closing Volume {CLOSING_VOLUME_UNIVERSE}"
            for row in rows
            if str(row.get("symbol") or "").strip()
            and (_to_float(row.get("volumeSpike")) or 0) >= CLOSING_VOLUME_SPIKE_MULTIPLE
        }

    def snapshot(self) -> dict[str, Any]:
        active = list(self.active_trades.values())
        active_allocated = sum(trade["allocation"] for trade in active)
        unrealized_pnl = sum(trade.get("unrealizedPnl") or 0 for trade in active)
        equity = self.initial_capital + self.realized_pnl + unrealized_pnl
        closed_count = len(self.closed_trades)
        winning_trades = [trade for trade in self.closed_trades if (_to_float(trade.get("realizedPnl")) or 0) > 0]
        losing_trades = [trade for trade in self.closed_trades if (_to_float(trade.get("realizedPnl")) or 0) < 0]
        gross_profit = sum(_to_float(trade.get("realizedPnl")) or 0 for trade in winning_trades)
        gross_loss = abs(sum(_to_float(trade.get("realizedPnl")) or 0 for trade in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss else None
        return {
            "initialCapital": self.initial_capital,
            "allocationPerTrade": self.trade_allocation,
            "availableCapital": self.initial_capital + self.realized_pnl - active_allocated,
            "allocatedCapital": active_allocated,
            "realizedPnl": self.realized_pnl,
            "unrealizedPnl": unrealized_pnl,
            "equity": equity,
            "activeCount": len(active),
            "closedCount": closed_count,
            "totalTrades": len(active) + closed_count,
            "winningTrades": len(winning_trades),
            "losingTrades": len(losing_trades),
            "winRate": (len(winning_trades) / closed_count) * 100 if closed_count else None,
            "profitFactor": profit_factor,
            "profitFactorLabel": f"{profit_factor:.2f}" if profit_factor is not None else "No losses" if gross_profit > 0 else "-",
            "dailyReport": self.daily_report(active=active),
            "dataPolicy": {
                "allowMockPrices": False,
                "priceDataProvider": PRICE_DATA_PROVIDER,
                "priceSource": (
                    "Upstox prices for selected stocks and active trades; NSE is used for sector shortlisting"
                    if USE_UPSTOX_PRICE_DATA
                    else "NSE live endpoints only"
                ),
                "paperEntryPrice": (
                    "current Upstox last traded price at signal time"
                    if USE_UPSTOX_PRICE_DATA
                    else "current NSE last traded price at signal time"
                ),
                "m5Confirmation": "last completed 5-minute bucket only",
                "freshConfirmationWindowSeconds": FRESH_CONFIRMATION_SECONDS,
                "lookAheadBiasGuard": "paper signals never use a still-forming M5 candle",
                "activeTradeMonitoring": (
                    "active trades are marked immediately from Upstox websocket ticks when enabled; NSE polling remains the fallback"
                    if UPSTOX_WEBSOCKET_ENABLED
                    else "active trades are marked to live prices whenever the NSE stream is live"
                ),
                "intradaySquareOff": f"open trades auto-close at {PAPER_SQUARE_OFF_HOUR:02d}:{PAPER_SQUARE_OFF_MINUTE:02d}",
                "dailyStockSlLimit": DAILY_STOCK_SL_LIMIT,
            },
            "stopManagement": {
                "moveSlToBreakEven": PAPER_MOVE_SL_TO_BE,
                "breakEvenTriggerRr": PAPER_BE_TRIGGER_RR,
                "profitLockRr": PAPER_BE_LOCK_RR,
                "sectorMomentumRunnerEnabled": SECTOR_MOMENTUM_RUNNER_ENABLED,
                "sectorMomentumPartialExitRr": SECTOR_MOMENTUM_PARTIAL_EXIT_RR,
                "sectorMomentumPartialExitPct": SECTOR_MOMENTUM_PARTIAL_EXIT_PCT,
                "sectorMomentumRunnerSlLockRr": SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR,
            },
            "closingVolumeShortlist": self.closing_volume_shortlist,
            "ideaCount": len(self.last_ideas),
            "ideasDate": self.last_ideas_date,
            "sessionOpen": self._entry_session_is_open(),
            "sessionStart": f"{PAPER_START_HOUR:02d}:{PAPER_START_MINUTE:02d}",
            "squareOffTime": f"{PAPER_SQUARE_OFF_HOUR:02d}:{PAPER_SQUARE_OFF_MINUTE:02d}",
            "sessionStatus": self._session_status(),
            "lastSavedAt": self.last_saved_at,
            "persistencePath": str(PAPER_STATE_PATH),
            "persistenceError": self.persistence_error,
            "ideas": self.last_ideas,
            "openTrades": active,
            "activeTrades": active,
            "closedTrades": self.closed_trades[-12:],
            "allTrades": self._all_trades_newest_first(active),
        }

    def _all_trades_newest_first(self, active: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trades = [*active, *self.closed_trades]
        return sorted(
            trades,
            key=lambda trade: str(trade.get("entryTime") or trade.get("openedAt") or ""),
            reverse=True,
        )

    def daily_report(self, date_key: str | None = None, active: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        day_key = _valid_date_key(date_key) or _today_key()
        active_trades = list(self.active_trades.values()) if active is None else active
        closed_today = [
            trade for trade in self.closed_trades
            if _trade_date_key(trade, "exitTime", "closedAt") == day_key
        ]
        active_for_day = active_trades if day_key == _today_key() else [
            trade for trade in active_trades
            if _trade_date_key(trade, "entryTime", "openedAt") == day_key
        ]
        closed_stats = self._closed_stats(closed_today)
        open_pnl = sum(_to_float(trade.get("unrealizedPnl")) or 0 for trade in active_for_day)
        realized_pnl = closed_stats["pnl"]
        return {
            "date": day_key,
            "today": _today_key(),
            "realizedPnl": _round_price(realized_pnl),
            "unrealizedPnl": _round_price(open_pnl),
            "totalPnl": _round_price(realized_pnl + open_pnl),
            "closedTrades": len(closed_today),
            "slTrades": self._daily_sl_count(day_key),
            "dailyStockSlLimit": DAILY_STOCK_SL_LIMIT,
            "openTrades": len(active_for_day),
            "totalTrades": len(closed_today) + len(active_for_day),
            "winningTrades": closed_stats["wins"],
            "losingTrades": closed_stats["losses"],
            "winRate": closed_stats["winRate"],
            "profitFactor": closed_stats["profitFactor"],
            "profitFactorLabel": closed_stats["profitFactorLabel"],
            "availableDates": self._available_report_dates(active_trades),
            "stockRows": self._group_report_rows(closed_today, active_for_day, "symbol"),
            "thesisRows": self._group_report_rows(closed_today, active_for_day, "thesis"),
            "exitRows": self._exit_report_rows(closed_today),
        }

    def _available_report_dates(self, active: list[dict[str, Any]]) -> list[str]:
        dates = {_today_key()}
        for trade in self.closed_trades:
            day = _trade_date_key(trade, "exitTime", "closedAt", "entryTime", "openedAt")
            if day:
                dates.add(day)
        for trade in active:
            day = _trade_date_key(trade, "entryTime", "openedAt")
            if day:
                dates.add(day)
        return sorted(dates)

    @staticmethod
    def _closed_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [_to_float(trade.get("realizedPnl")) or 0 for trade in trades]
        wins = len([pnl for pnl in pnls if pnl > 0])
        losses = len([pnl for pnl in pnls if pnl < 0])
        gross_profit = sum(pnl for pnl in pnls if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss else None
        return {
            "pnl": sum(pnls),
            "wins": wins,
            "losses": losses,
            "winRate": (wins / len(trades)) * 100 if trades else None,
            "profitFactor": profit_factor,
            "profitFactorLabel": f"{profit_factor:.2f}" if profit_factor is not None else "No losses" if gross_profit > 0 else "-",
        }

    def _group_report_rows(
        self,
        closed_trades: list[dict[str, Any]],
        active_trades: list[dict[str, Any]],
        group_key: str,
    ) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for trade in closed_trades:
            label = str(trade.get(group_key) or "-")
            row = groups.setdefault(label, {"name": label, "closed": [], "open": []})
            row["closed"].append(trade)
        for trade in active_trades:
            label = str(trade.get(group_key) or "-")
            row = groups.setdefault(label, {"name": label, "closed": [], "open": []})
            row["open"].append(trade)

        rows = []
        for label, group in groups.items():
            stats = self._closed_stats(group["closed"])
            open_pnl = sum(_to_float(trade.get("unrealizedPnl")) or 0 for trade in group["open"])
            rows.append({
                "name": label,
                "realizedPnl": _round_price(stats["pnl"]),
                "unrealizedPnl": _round_price(open_pnl),
                "totalPnl": _round_price(stats["pnl"] + open_pnl),
                "closedTrades": len(group["closed"]),
                "openTrades": len(group["open"]),
                "totalTrades": len(group["closed"]) + len(group["open"]),
                "winningTrades": stats["wins"],
                "losingTrades": stats["losses"],
                "winRate": stats["winRate"],
                "profitFactorLabel": stats["profitFactorLabel"],
            })
        rows.sort(key=lambda row: row["totalPnl"] or 0, reverse=True)
        return rows

    def _exit_report_rows(self, closed_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for trade in closed_trades:
            reason = str(trade.get("exitReason") or "UNKNOWN")
            grouped.setdefault(reason, []).append(trade)
        rows = []
        for reason, trades in grouped.items():
            stats = self._closed_stats(trades)
            rows.append({
                "name": reason,
                "realizedPnl": _round_price(stats["pnl"]),
                "closedTrades": len(trades),
                "winningTrades": stats["wins"],
                "losingTrades": stats["losses"],
                "winRate": stats["winRate"],
                "profitFactorLabel": stats["profitFactorLabel"],
            })
        rows.sort(key=lambda row: row["realizedPnl"] or 0, reverse=True)
        return rows

    def _daily_sl_count(self, day_key: str | None = None) -> int:
        day = _valid_date_key(day_key) or _today_key()
        return len([
            trade for trade in self.closed_trades
            if _trade_date_key(trade, "exitTime", "closedAt") == day
            and str(trade.get("exitReason") or trade.get("status") or "").upper() == "SL"
        ])

    def _daily_stock_sl_count(self, symbol: str, day_key: str | None = None) -> int:
        day = _valid_date_key(day_key) or _today_key()
        stock_symbol = str(symbol or "").strip().upper()
        if not stock_symbol:
            return 0
        return len([
            trade for trade in self.closed_trades
            if str(trade.get("symbol") or "").strip().upper() == stock_symbol
            and _trade_date_key(trade, "exitTime", "closedAt") == day
            and str(trade.get("exitReason") or trade.get("status") or "").upper() == "SL"
        ])

    def _daily_stock_sl_limit_reached(self, symbol: str) -> bool:
        return self._daily_stock_sl_count(symbol) >= DAILY_STOCK_SL_LIMIT

    def _load(self) -> None:
        if not PAPER_STATE_PATH.exists():
            return
        try:
            payload = json.loads(PAPER_STATE_PATH.read_text(encoding="utf-8"))
            self.initial_capital = _to_float(payload.get("initialCapital")) or PAPER_INITIAL_CAPITAL
            self.trade_allocation = _to_float(payload.get("allocationPerTrade")) or PAPER_TRADE_ALLOCATION
            self.realized_pnl = _to_float(payload.get("realizedPnl")) or 0.0
            self.candles = payload.get("candles") if isinstance(payload.get("candles"), dict) else {}
            self.fib_watch = payload.get("fibWatch") if isinstance(payload.get("fibWatch"), dict) else {}
            self.closing_volume_shortlist = (
                payload.get("closingVolumeShortlist")
                if isinstance(payload.get("closingVolumeShortlist"), dict)
                else {}
            )
            self.used_confirmations = self._normalize_used_confirmations(payload.get("usedConfirmations"))
            open_trades = payload.get("openTrades") or payload.get("activeTrades")
            self.active_trades = open_trades if isinstance(open_trades, dict) else {}
            self.closed_trades = payload.get("closedTrades") if isinstance(payload.get("closedTrades"), list) else []
            self._normalize_loaded_trades()
            self.last_ideas_date = _valid_date_key(payload.get("ideasDate"))
            if self.last_ideas_date == _today_key() and isinstance(payload.get("ideas"), list):
                self.last_ideas = payload["ideas"]
            else:
                self._clear_last_ideas()
            self.next_trade_id = int(payload.get("nextTradeId") or self._next_trade_id_from_history())
            self.last_saved_at = payload.get("lastSavedAt") or payload.get("savedAt")
            self.persistence_error = None
        except Exception as exc:  # noqa: BLE001 - keep dashboard usable and surface persistence trouble
            self.persistence_error = f"Could not load paper trading state: {exc}"

    def _persist(self) -> None:
        payload = {
            "schemaVersion": 1,
            "savedAt": _now_label(),
            "initialCapital": self.initial_capital,
            "allocationPerTrade": self.trade_allocation,
            "realizedPnl": self.realized_pnl,
            "nextTradeId": self.next_trade_id,
            "candles": self.candles,
            "fibWatch": self.fib_watch,
            "closingVolumeShortlist": self.closing_volume_shortlist,
            "usedConfirmations": self.used_confirmations,
            "openTrades": self.active_trades,
            "activeTrades": self.active_trades,
            "closedTrades": self.closed_trades,
            "ideasDate": self.last_ideas_date,
            "ideas": self.last_ideas,
        }
        try:
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            temp_path = PAPER_STATE_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            temp_path.replace(PAPER_STATE_PATH)
            self.last_saved_at = payload["savedAt"]
            self.persistence_error = None
        except Exception as exc:  # noqa: BLE001 - surface persistence trouble to the UI
            self.persistence_error = f"Could not save paper trading state: {exc}"

    def _clear_last_ideas(self) -> None:
        self.last_ideas = []
        self.last_ideas_date = None

    def _next_trade_id_from_history(self) -> int:
        max_id = 0
        trades = [*self.active_trades.values(), *self.closed_trades]
        for trade in trades:
            text = str(trade.get("id") or "")
            if text.startswith("PT") and text[2:].isdigit():
                max_id = max(max_id, int(text[2:]))
        return max_id + 1

    def _normalize_loaded_trades(self) -> None:
        for trade in self.active_trades.values():
            trade["entryTime"] = trade.get("entryTime") or trade.get("openedAt") or "-"
            trade["openedAt"] = trade["entryTime"]
            trade["quantity"] = int(_to_float(trade.get("quantity")) or 0)
            trade["initialStopLoss"] = trade.get("initialStopLoss") or trade.get("stopLoss")
            trade["stopMovedToBe"] = bool(trade.get("stopMovedToBe"))
        for trade in self.closed_trades:
            trade["entryTime"] = trade.get("entryTime") or trade.get("openedAt") or "-"
            trade["openedAt"] = trade["entryTime"]
            trade["exitTime"] = trade.get("exitTime") or trade.get("closedAt") or "-"
            trade["closedAt"] = trade["exitTime"]
            trade["quantity"] = int(_to_float(trade.get("quantity")) or 0)

    @staticmethod
    def _normalize_used_confirmations(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, int] = {}
        for key, bucket in value.items():
            if not isinstance(key, str):
                continue
            number = _to_float(bucket)
            if number is not None:
                normalized[key] = int(number)
        return normalized

    @staticmethod
    def _session_is_open(now: float | None = None) -> bool:
        local_time = time.localtime(now or time.time())
        if local_time.tm_hour > PAPER_START_HOUR:
            return True
        return local_time.tm_hour == PAPER_START_HOUR and local_time.tm_min >= PAPER_START_MINUTE

    @staticmethod
    def _square_off_due(now: float | None = None) -> bool:
        local_time = time.localtime(now or time.time())
        if local_time.tm_hour > PAPER_SQUARE_OFF_HOUR:
            return True
        return local_time.tm_hour == PAPER_SQUARE_OFF_HOUR and local_time.tm_min >= PAPER_SQUARE_OFF_MINUTE

    def _entry_session_is_open(self, now: float | None = None) -> bool:
        return self._session_is_open(now) and not self._square_off_due(now)

    def _session_status(self) -> str:
        if self._square_off_due():
            return f"Intraday square-off active after {PAPER_SQUARE_OFF_HOUR:02d}:{PAPER_SQUARE_OFF_MINUTE:02d}"
        if self._session_is_open():
            return "Paper engine active"
        return f"Waiting until {PAPER_START_HOUR:02d}:{PAPER_START_MINUTE:02d} to start paper trading"

    @staticmethod
    def _selected_stocks(stock_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stocks = []
        for group in stock_groups:
            if group.get("noSetup"):
                continue
            for stock in group.get("stocks") or []:
                merged = {**stock, "sector": group.get("sector") or stock.get("sector"), "direction": group.get("direction") or stock.get("direction")}
                if merged.get("symbol") and _to_float(merged.get("current")) is not None:
                    stocks.append(merged)
        return stocks

    @staticmethod
    def _merge_mark_stocks(
        selected_stocks: list[dict[str, Any]],
        active_quote_stocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_symbol: dict[str, dict[str, Any]] = {}
        for stock in selected_stocks:
            by_symbol[str(stock.get("symbol") or "")] = stock
        for stock in active_quote_stocks:
            symbol = str(stock.get("symbol") or "")
            if symbol and _to_float(stock.get("current")) is not None:
                by_symbol[symbol] = stock
        return list(by_symbol.values())

    def _closing_volume_live_stocks(self, mark_stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        targets = self.closing_volume_mark_targets()
        if not targets:
            return []
        setup_rows = self.closing_volume_shortlist.get("selected")
        if not isinstance(setup_rows, list):
            return []
        setup_by_symbol = {
            str(row.get("symbol") or "").strip().upper(): row
            for row in setup_rows
            if str(row.get("symbol") or "").strip()
            and (_to_float(row.get("volumeSpike")) or 0) >= CLOSING_VOLUME_SPIKE_MULTIPLE
        }
        mark_by_symbol = {
            str(stock.get("symbol") or "").strip().upper(): stock
            for stock in mark_stocks
            if str(stock.get("symbol") or "").strip()
        }
        stocks = []
        for symbol, setup in setup_by_symbol.items():
            mark = mark_by_symbol.get(symbol)
            if not mark or _to_float(mark.get("current")) is None:
                continue
            stocks.append(
                {
                    **mark,
                    "symbol": symbol,
                    "sector": f"Closing Volume {CLOSING_VOLUME_UNIVERSE}",
                    "direction": "gain" if setup.get("side") == "BUY" else "loss",
                    "closingVolumeSetup": setup,
                }
            )
        return stocks

    def _update_candle(self, stock: dict[str, Any], now: float) -> None:
        symbol = stock["symbol"]
        price = _to_float(stock.get("current"))
        if price is None:
            return
        bucket = int(now // M5_SECONDS) * M5_SECONDS
        candles = self.candles.setdefault(symbol, [])
        if not candles or candles[-1]["bucket"] != bucket:
            candles.append(
                {
                    "bucket": bucket,
                    "startedAt": time.strftime("%H:%M:%S", time.localtime(bucket)),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "ticks": 1,
                }
            )
            del candles[:-12]
            return
        candle = candles[-1]
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price
        candle["ticks"] += 1

    def _latest_candle(self, symbol: str) -> dict[str, Any] | None:
        candles = self.candles.get(symbol) or []
        return candles[-2] if len(candles) >= 2 else None

    def _build_ideas(self, stocks: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        ideas = []
        for stock in stocks:
            side = "BUY" if stock.get("direction") == "gain" else "SHORT"
            ideas.append(self._sector_momentum_idea(stock, side, now))
            ideas.append(self._vwap_idea(stock, side, now))
            ideas.append(self._fib_idea(stock, side, now))
        return [idea for idea in ideas if idea]

    def _closing_volume_ideas(self, stocks: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        return [idea for stock in stocks if (idea := self._closing_volume_idea(stock, now))]

    def _closing_volume_idea(self, stock: dict[str, Any], now: float) -> dict[str, Any] | None:
        setup = stock.get("closingVolumeSetup")
        if not isinstance(setup, dict):
            return None
        symbol = str(stock.get("symbol") or setup.get("symbol") or "").strip().upper()
        side = str(setup.get("side") or "").strip().upper()
        price = _to_float(stock.get("current"))
        final_close = _to_float(setup.get("final15Close"))
        final_low = _to_float(setup.get("final15Low"))
        final_high = _to_float(setup.get("final15High"))
        if not symbol or side not in {"BUY", "SHORT"} or price is None or final_close is None or final_low is None or final_high is None:
            return None

        now_dt = dt.datetime.fromtimestamp(now)
        entry_start = dt.datetime.combine(now_dt.date(), dt.time(PAPER_START_HOUR, PAPER_START_MINUTE))
        entry_end = entry_start + dt.timedelta(minutes=max(1, CLOSING_VOLUME_ENTRY_WINDOW_MINUTES))
        confirmation_key = self._confirmation_key(symbol, side, "Closing Volume Institutional Followthrough")
        confirmation_bucket = int(now_dt.strftime("%Y%m%d"))
        confirmation_used = self.used_confirmations.get(confirmation_key) == confirmation_bucket
        active_key = self._trade_key(symbol, "Closing Volume Institutional Followthrough")
        opening_reference = _first_float(stock.get("open"), price)

        if now_dt < entry_start:
            status = f"Waiting until {entry_start.strftime('%H:%M')} for closing-volume followthrough entry"
            time_ok = False
        elif now_dt >= entry_end:
            status = f"Opening followthrough window closed after {entry_end.strftime('%H:%M')}"
            time_ok = False
        else:
            status = "Opening followthrough window active"
            time_ok = True

        if side == "BUY":
            direction_ok = opening_reference is not None and opening_reference >= final_close and price >= final_close
            stop_loss = max(final_low, price * (1 - CLOSING_VOLUME_MAX_RISK_PCT))
            if stop_loss >= price:
                stop_loss = price * (1 - CLOSING_VOLUME_MAX_RISK_PCT)
            risk = price - stop_loss
            target = price + (risk * CLOSING_VOLUME_TARGET_RR)
        else:
            direction_ok = opening_reference is not None and opening_reference <= final_close and price <= final_close
            stop_loss = min(final_high, price * (1 + CLOSING_VOLUME_MAX_RISK_PCT))
            if stop_loss <= price:
                stop_loss = price * (1 + CLOSING_VOLUME_MAX_RISK_PCT)
            risk = stop_loss - price
            target = price - (risk * CLOSING_VOLUME_TARGET_RR)

        rr = _risk_reward(side, price, stop_loss, target)
        quantity = max(1, int(self.trade_allocation // price)) if price > 0 else 0
        ready = bool(
            time_ok
            and direction_ok
            and not confirmation_used
            and active_key not in self.active_trades
            and rr is not None
            and rr > MIN_TRADE_RR
            and quantity > 0
        )
        if active_key in self.active_trades:
            status = "Already active"
        elif confirmation_used:
            status = "Opening followthrough already traded today"
        elif time_ok and not direction_ok:
            direction_text = "above" if side == "BUY" else "below"
            status = f"Rejected: open/current is not {direction_text} Friday final 15m close {final_close:.2f}"
        elif ready:
            status = "Ready: closing-volume institutional followthrough at open"

        loss_if_sl = abs(_trade_pnl(side, price, stop_loss, quantity))
        profit_if_tp = max(0.0, _trade_pnl(side, price, target, quantity))
        return {
            "symbol": symbol,
            "sector": f"Closing Volume {CLOSING_VOLUME_UNIVERSE}",
            "side": side,
            "thesis": "Closing Volume Institutional Followthrough",
            "thesisDetail": f"After market close, shortlist {CLOSING_VOLUME_UNIVERSE} stocks with institutional-style final 15-minute volume; next session, enter at the open only if price follows that direction.",
            "entry": _round_price(price),
            "stopLoss": _round_price(stop_loss),
            "target": _round_price(target),
            "currentPrice": _round_price(price),
            "rr": round(rr, 2) if rr is not None else None,
            "lossIfSl": _round_price(loss_if_sl),
            "profitIfTp": _round_price(profit_if_tp),
            "allocation": self.trade_allocation,
            "quantity": quantity,
            "ready": ready,
            "status": status,
            "confirmationKey": confirmation_key,
            "confirmationBucket": confirmation_bucket,
            "confirmationFresh": time_ok,
            "confirmationUsed": confirmation_used,
            "m5": {
                "bucket": confirmation_bucket,
                "open": _round_price(_to_float(setup.get("final15Open"))),
                "high": _round_price(final_high),
                "low": _round_price(final_low),
                "close": _round_price(final_close),
                "ticks": 1,
                "startedAt": str(setup.get("final15Start") or "-"),
            },
            "sourceSessionDate": setup.get("sessionDate"),
            "targetDate": setup.get("targetDate"),
            "volumeSpike": setup.get("volumeSpike"),
            "dailyVolumeSharePct": setup.get("dailyVolumeSharePct"),
            "avgDailyVolume": setup.get("avgDailyVolume"),
            "avgFinal15Volume": setup.get("avgFinal15Volume"),
            "final15Volume": setup.get("final15Volume"),
            "final15BodyPct": setup.get("final15BodyPct"),
            "openingReference": _round_price(opening_reference),
            "closingVolumeSetup": setup,
        }

    def _sector_momentum_idea(self, stock: dict[str, Any], side: str, now: float) -> dict[str, Any] | None:
        price = _to_float(stock.get("current"))
        vwap = _to_float(stock.get("vwap"))
        day_open = _to_float(stock.get("open"))
        day_high = _to_float(stock.get("high"))
        day_low = _to_float(stock.get("low"))
        stock_change = _to_float(stock.get("percentChange"))
        candle = self._latest_candle(stock["symbol"])
        if (
            price is None
            or vwap is None
            or day_open is None
            or day_high is None
            or day_low is None
            or stock_change is None
            or not candle
        ):
            return None

        if side == "BUY":
            trend_aligned = stock.get("direction") == "gain" and stock_change > 0 and price > day_open and price > vwap
            breakout_price = candle["high"] * (1 + SECTOR_MOMENTUM_BREAKOUT_BUFFER)
            continuation = price >= breakout_price
            entry_near_breakout = price <= breakout_price * (1 + SECTOR_MOMENTUM_MAX_ENTRY_EXTENSION)
        else:
            trend_aligned = stock.get("direction") == "loss" and stock_change < 0 and price < day_open and price < vwap
            breakout_price = candle["low"] * (1 - SECTOR_MOMENTUM_BREAKOUT_BUFFER)
            continuation = price <= breakout_price
            entry_near_breakout = price >= breakout_price * (1 - SECTOR_MOMENTUM_MAX_ENTRY_EXTENSION)

        confirm = self._candle_confirms(candle, side)
        entry, stop_loss, target = self._momentum_levels(side, price, candle)
        risk_pct = abs(entry - stop_loss) / entry if entry > 0 else None
        risk_ok = risk_pct is not None and risk_pct <= SECTOR_MOMENTUM_MAX_RISK_PCT
        ready = trend_aligned and continuation and entry_near_breakout and confirm and risk_ok
        if ready:
            status = "Ready: sector momentum continuation with M5 breakout"
        elif not trend_aligned:
            status = "Waiting for stock to align with sector, VWAP, and day open"
        elif not continuation:
            status = "Waiting for live price to break the completed M5 candle"
        elif not entry_near_breakout:
            status = "Rejected: entry is too far from the M5 breakout"
        elif not risk_ok:
            status = f"Rejected: momentum SL risk is above {SECTOR_MOMENTUM_MAX_RISK_PCT * 100:.2f}%"
        else:
            status = f"Waiting for M5 {'bullish' if side == 'BUY' else 'bearish'} continuation candle"

        return self._idea(
            stock,
            side,
            "Sector Momentum",
            "Trade the strongest sector continuation only after stock direction, VWAP, day open, and completed M5 breakout agree.",
            entry,
            stop_loss,
            target,
            ready,
            status,
            candle,
            now,
            {
                "breakoutPrice": breakout_price,
                "riskPct": risk_pct * 100 if risk_pct is not None else None,
                "targetRr": SECTOR_MOMENTUM_TARGET_RR,
                "runnerEnabled": SECTOR_MOMENTUM_RUNNER_ENABLED,
                "partialExitRr": SECTOR_MOMENTUM_PARTIAL_EXIT_RR,
                "partialExitPct": SECTOR_MOMENTUM_PARTIAL_EXIT_PCT,
                "runnerSlLockRr": SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR,
            },
        )

    def _vwap_idea(self, stock: dict[str, Any], side: str, now: float) -> dict[str, Any] | None:
        price = _to_float(stock.get("current"))
        vwap = _to_float(stock.get("vwap"))
        day_high = _to_float(stock.get("high"))
        day_low = _to_float(stock.get("low"))
        candle = self._latest_candle(stock["symbol"])
        if price is None or vwap is None or day_high is None or day_low is None or not candle:
            return None
        retest = abs(price - vwap) / vwap <= VWAP_RETEST_TOLERANCE
        confirm = self._candle_confirms(candle, side)
        entry, stop_loss, target = self._levels(side, price, day_low, day_high, candle)
        return self._idea(
            stock,
            side,
            "VWAP M5 Retest",
            "Price retraces to VWAP, then a 5-minute confirmation candle triggers the trade.",
            entry,
            stop_loss,
            target,
            retest and confirm,
            "Ready: VWAP retest with M5 confirmation"
            if retest and confirm
            else "Waiting for VWAP retest"
            if not retest
            else f"Waiting for M5 {'bullish' if side == 'BUY' else 'bearish'} candle",
            candle,
            now,
        )

    def _fib_idea(self, stock: dict[str, Any], side: str, now: float) -> dict[str, Any] | None:
        price = _to_float(stock.get("current"))
        day_high = _to_float(stock.get("high"))
        day_low = _to_float(stock.get("low"))
        candle = self._latest_candle(stock["symbol"])
        if price is None or day_high is None or day_low is None or day_high <= day_low or not candle:
            return None
        zone_low, zone_high = self._fib_zone(side, day_low, day_high)
        in_zone = zone_low <= price <= zone_high
        key = f"{stock['symbol']}|{side}|FIB"
        watch = self.fib_watch.get(key)
        if in_zone and not watch:
            watch = {"seenAt": _now_label()}
            self.fib_watch[key] = watch
        if not in_zone and watch and self._price_invalidates_fib(side, price, day_low, day_high):
            self.fib_watch.pop(key, None)
            watch = None
        confirm = bool(watch) and self._candle_confirms(candle, side)
        entry, stop_loss, target = self._levels(side, price, day_low, day_high, candle)
        status = "Ready: Fib zone held and next M5 candle confirmed" if confirm else f"Waiting for 38.2-61.8% retracement ({_round_price(zone_low)}-{_round_price(zone_high)})"
        if watch and not confirm:
            status = f"Fib zone touched at {watch['seenAt']}; waiting for next M5 confirmation"
        return self._idea(
            stock,
            side,
            "Fib Retracement Confirm",
            "Price enters the 38.2-61.8% intraday retracement zone, then the next 5-minute candle confirms.",
            entry,
            stop_loss,
            target,
            confirm,
            status,
            candle,
            now,
            {"zoneLow": zone_low, "zoneHigh": zone_high},
        )

    def _idea(
        self,
        stock: dict[str, Any],
        side: str,
        thesis: str,
        thesisDetail: str,
        entry: float,
        stop_loss: float,
        target: float,
        ready: bool,
        status: str,
        candle: dict[str, Any],
        now: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        quantity = max(1, int(self.trade_allocation // entry)) if entry > 0 else 0
        rr = _risk_reward(side, entry, stop_loss, target)
        loss_if_sl = abs(_trade_pnl(side, entry, stop_loss, quantity))
        profit_if_tp = max(0.0, _trade_pnl(side, entry, target, quantity))
        active_key = self._trade_key(stock["symbol"], thesis)
        confirmation_key = self._confirmation_key(stock["symbol"], side, thesis)
        confirmation_bucket = int(_to_float(candle.get("bucket")) or 0)
        confirmation_fresh = self._confirmation_is_fresh(candle, now)
        confirmation_used = self.used_confirmations.get(confirmation_key) == confirmation_bucket
        ready_status = status
        if active_key in self.active_trades:
            ready_status = "Already active"
        elif ready and confirmation_used:
            ready_status = "Waiting for next M5 confirmation candle"
        elif ready and not confirmation_fresh:
            ready_status = f"Confirmation older than {FRESH_CONFIRMATION_SECONDS}s; waiting for next M5 candle"
        elif ready and (rr is None or rr <= MIN_TRADE_RR):
            ready_status = f"Rejected: RR must be above {MIN_TRADE_RR}"
        ready_to_trade = (
            ready
            and confirmation_fresh
            and not confirmation_used
            and rr is not None
            and rr > MIN_TRADE_RR
            and quantity > 0
            and active_key not in self.active_trades
        )
        idea = {
            "symbol": stock["symbol"],
            "sector": stock.get("sector") or "-",
            "side": side,
            "thesis": thesis,
            "thesisDetail": thesisDetail,
            "entry": _round_price(entry),
            "stopLoss": _round_price(stop_loss),
            "target": _round_price(target),
            "currentPrice": _round_price(entry),
            "rr": round(rr, 2) if rr is not None else None,
            "lossIfSl": _round_price(loss_if_sl),
            "profitIfTp": _round_price(profit_if_tp),
            "allocation": self.trade_allocation,
            "quantity": quantity,
            "ready": bool(ready_to_trade),
            "status": ready_status,
            "confirmationKey": confirmation_key,
            "confirmationBucket": confirmation_bucket,
            "confirmationFresh": confirmation_fresh,
            "confirmationUsed": confirmation_used,
            "m5": {
                "bucket": confirmation_bucket,
                "open": _round_price(candle["open"]),
                "high": _round_price(candle["high"]),
                "low": _round_price(candle["low"]),
                "close": _round_price(candle["close"]),
                "ticks": candle["ticks"],
                "startedAt": candle["startedAt"],
            },
        }
        if extra:
            idea.update({key: _round_price(value) if isinstance(value, float) else value for key, value in extra.items()})
        return idea

    @staticmethod
    def _confirmation_key(symbol: str, side: str, thesis: str) -> str:
        return f"{symbol}|{side}|{thesis}"

    @staticmethod
    def _confirmation_is_fresh(candle: dict[str, Any], now: float) -> bool:
        bucket = _to_float(candle.get("bucket"))
        if bucket is None:
            return False
        confirmed_at = bucket + M5_SECONDS
        return 0 <= now - confirmed_at <= FRESH_CONFIRMATION_SECONDS

    @staticmethod
    def _candle_confirms(candle: dict[str, Any], side: str) -> bool:
        if candle.get("ticks", 0) < 2:
            return False
        if side == "BUY":
            return candle["close"] > candle["open"]
        return candle["close"] < candle["open"]

    @staticmethod
    def _levels(side: str, price: float, day_low: float, day_high: float, candle: dict[str, Any]) -> tuple[float, float, float]:
        buffer = max(price * 0.001, 0.05)
        if side == "BUY":
            return price, candle["low"] - buffer, day_high
        return price, candle["high"] + buffer, day_low

    @staticmethod
    def _momentum_levels(side: str, price: float, candle: dict[str, Any]) -> tuple[float, float, float]:
        buffer = max(price * 0.001, 0.05)
        if side == "BUY":
            stop_loss = candle["low"] - buffer
            risk = price - stop_loss
            return price, stop_loss, price + (risk * SECTOR_MOMENTUM_TARGET_RR)
        stop_loss = candle["high"] + buffer
        risk = stop_loss - price
        return price, stop_loss, price - (risk * SECTOR_MOMENTUM_TARGET_RR)

    @staticmethod
    def _fib_zone(side: str, day_low: float, day_high: float) -> tuple[float, float]:
        span = day_high - day_low
        if side == "BUY":
            lower = day_high - (span * 0.618)
            upper = day_high - (span * 0.382)
        else:
            lower = day_low + (span * 0.382)
            upper = day_low + (span * 0.618)
        return min(lower, upper), max(lower, upper)

    @staticmethod
    def _price_invalidates_fib(side: str, price: float, day_low: float, day_high: float) -> bool:
        return price < day_low if side == "BUY" else price > day_high

    def _activate_ready_ideas(self, ideas: list[dict[str, Any]]) -> None:
        for idea in ideas:
            if not idea.get("ready"):
                continue
            symbol = str(idea.get("symbol") or "")
            if self._daily_stock_sl_limit_reached(symbol):
                idea["ready"] = False
                idea["status"] = f"{symbol} daily SL limit reached ({DAILY_STOCK_SL_LIMIT}); no new trades for this stock today"
                continue
            if self.snapshot()["availableCapital"] < self.trade_allocation:
                idea["ready"] = False
                idea["status"] = "Ready but capital is fully allocated"
                continue
            trade = self._trade_from_idea(idea)
            self.active_trades[trade["key"]] = trade
            self._mark_confirmation_used(idea)
            idea["status"] = "Trade placed"
            idea["ready"] = False

    def _mark_confirmation_used(self, idea: dict[str, Any]) -> None:
        confirmation_key = str(idea.get("confirmationKey") or "")
        confirmation_bucket = _to_float(idea.get("confirmationBucket"))
        if confirmation_key and confirmation_bucket is not None:
            self.used_confirmations[confirmation_key] = int(confirmation_bucket)

    def _trade_from_idea(self, idea: dict[str, Any]) -> dict[str, Any]:
        trade_id = f"PT{self.next_trade_id:04d}"
        self.next_trade_id += 1
        entry_time = _now_label()
        return {
            "id": trade_id,
            "key": self._trade_key(idea["symbol"], idea["thesis"]),
            "symbol": idea["symbol"],
            "sector": idea["sector"],
            "side": idea["side"],
            "thesis": idea["thesis"],
            "entry": idea["entry"],
            "stopLoss": idea["stopLoss"],
            "initialStopLoss": idea["stopLoss"],
            "target": idea["target"],
            "quantity": idea["quantity"],
            "allocation": self.trade_allocation,
            "currentPrice": idea["currentPrice"],
            "rr": idea["rr"],
            "lossIfSl": idea["lossIfSl"],
            "profitIfTp": idea["profitIfTp"],
            "confirmationKey": idea.get("confirmationKey"),
            "confirmationBucket": idea.get("confirmationBucket"),
            "originalQuantity": idea["quantity"],
            "runnerEnabled": bool(idea["thesis"] == "Sector Momentum" and SECTOR_MOMENTUM_RUNNER_ENABLED),
            "runnerActive": False,
            "partialExitDone": False,
            "partialExitRr": idea.get("partialExitRr"),
            "partialExitPct": idea.get("partialExitPct"),
            "runnerSlLockRr": idea.get("runnerSlLockRr"),
            "tp1": idea["target"],
            "sourceSessionDate": idea.get("sourceSessionDate"),
            "targetDate": idea.get("targetDate"),
            "volumeSpike": idea.get("volumeSpike"),
            "dailyVolumeSharePct": idea.get("dailyVolumeSharePct"),
            "avgDailyVolume": idea.get("avgDailyVolume"),
            "avgFinal15Volume": idea.get("avgFinal15Volume"),
            "final15Volume": idea.get("final15Volume"),
            "final15BodyPct": idea.get("final15BodyPct"),
            "openingReference": idea.get("openingReference"),
            "closingVolumeSetup": idea.get("closingVolumeSetup"),
            "unrealizedPnl": 0.0,
            "stopMovedToBe": False,
            "stopMoveReason": "",
            "entryTime": entry_time,
            "openedAt": entry_time,
            "status": "ACTIVE",
        }

    @staticmethod
    def _trade_key(symbol: str, thesis: str) -> str:
        return f"{symbol}|{thesis}"

    def _mark_active_trades(self, stocks: list[dict[str, Any]]) -> None:
        by_symbol = {stock["symbol"]: stock for stock in stocks}
        for key, trade in list(self.active_trades.items()):
            stock = by_symbol.get(trade["symbol"])
            if not stock:
                continue
            price = _to_float(stock.get("current"))
            if price is None:
                continue
            trade["currentPrice"] = _round_price(price)
            trade["unrealizedPnl"] = _round_price(_trade_pnl(trade["side"], trade["entry"], price, trade["quantity"]))
            current_rr = self._current_trade_rr(trade, price)
            trade["currentRr"] = round(current_rr, 2) if current_rr is not None else None
            self._move_stop_to_break_even(trade, price)
            exit_reason = None
            exit_price = None
            stop_loss = _to_float(trade.get("stopLoss"))
            target = _to_float(trade.get("target"))
            if stop_loss is None:
                continue
            if trade["side"] == "BUY":
                if price <= stop_loss:
                    exit_reason, exit_price = "SL", stop_loss
                elif target is not None and price >= target:
                    exit_reason, exit_price = "TP", target
            else:
                if price >= stop_loss:
                    exit_reason, exit_price = "SL", stop_loss
                elif target is not None and price <= target:
                    exit_reason, exit_price = "TP", target
            if exit_reason:
                if exit_reason == "TP" and self._sector_momentum_runner_pending(trade):
                    self._take_sector_momentum_partial(trade, exit_price, price)
                    continue
                self._close_trade(key, trade, exit_reason, exit_price)

    def mark_stream_prices(self, stocks: list[dict[str, Any]]) -> dict[str, Any]:
        self._mark_active_trades(stocks)
        self._persist()
        return self.snapshot()

    def _square_off_open_trades(self) -> None:
        for key, trade in list(self.active_trades.items()):
            exit_price = _to_float(trade.get("currentPrice")) or _to_float(trade.get("entry"))
            if exit_price is None:
                continue
            self._close_trade(key, trade, "EOD", exit_price)

    def _move_stop_to_break_even(self, trade: dict[str, Any], price: float) -> None:
        if not PAPER_MOVE_SL_TO_BE or trade.get("stopMovedToBe"):
            return
        current_rr = self._current_trade_rr(trade, price)
        if current_rr is None or current_rr < PAPER_BE_TRIGGER_RR:
            return
        entry = _to_float(trade.get("entry"))
        initial_stop = _to_float(trade.get("initialStopLoss") or trade.get("stopLoss"))
        current_stop = _to_float(trade.get("stopLoss"))
        if entry is None or initial_stop is None or current_stop is None:
            return
        initial_risk = abs(entry - initial_stop)
        if initial_risk <= 0:
            return
        if trade["side"] == "BUY":
            new_stop = entry + (initial_risk * PAPER_BE_LOCK_RR)
            if new_stop <= current_stop or new_stop >= price:
                return
        else:
            new_stop = entry - (initial_risk * PAPER_BE_LOCK_RR)
            if new_stop >= current_stop or new_stop <= price:
                return
        trade["stopLoss"] = _round_price(new_stop)
        trade["stopMovedToBe"] = True
        trade["stopMoveReason"] = f"Moved to BE+{PAPER_BE_LOCK_RR}R after {PAPER_BE_TRIGGER_RR}R"

    @staticmethod
    def _sector_momentum_runner_pending(trade: dict[str, Any]) -> bool:
        return (
            str(trade.get("thesis") or "") == "Sector Momentum"
            and bool(trade.get("runnerEnabled"))
            and not bool(trade.get("partialExitDone"))
        )

    def _take_sector_momentum_partial(self, trade: dict[str, Any], exit_price: float, mark_price: float) -> None:
        quantity = int(_to_float(trade.get("quantity")) or 0)
        if quantity <= 0:
            return
        partial_quantity = int(quantity * SECTOR_MOMENTUM_PARTIAL_EXIT_PCT)
        partial_quantity = max(1, partial_quantity)
        if partial_quantity >= quantity:
            partial_quantity = quantity - 1

        if partial_quantity > 0:
            pnl = _trade_pnl(trade["side"], trade["entry"], exit_price, partial_quantity)
            self.realized_pnl += pnl
            exit_time = _now_label()
            allocation = _to_float(trade.get("allocation")) or 0.0
            closed = {
                **trade,
                "id": f"{trade.get('id')}-P1",
                "parentTradeId": trade.get("id"),
                "quantity": partial_quantity,
                "allocation": _round_price((allocation / quantity) * partial_quantity) if quantity else 0,
                "exitReason": "TP",
                "exitPrice": _round_price(exit_price),
                "realizedPnl": _round_price(pnl),
                "entryTime": trade.get("entryTime") or trade.get("openedAt") or "-",
                "closedAt": exit_time,
                "exitTime": exit_time,
                "status": "TP",
                "partialExit": True,
            }
            self.closed_trades.append(closed)
            remaining_quantity = quantity - partial_quantity
            trade["quantity"] = remaining_quantity
            trade["allocation"] = _round_price((allocation / quantity) * remaining_quantity) if quantity else 0

        trade["partialExitDone"] = True
        trade["runnerActive"] = True
        trade["target"] = None
        self._lock_sector_momentum_runner_stop(trade)
        trade["unrealizedPnl"] = _round_price(_trade_pnl(trade["side"], trade["entry"], mark_price, trade["quantity"]))

    def _lock_sector_momentum_runner_stop(self, trade: dict[str, Any]) -> None:
        entry = _to_float(trade.get("entry"))
        initial_stop = _to_float(trade.get("initialStopLoss") or trade.get("stopLoss"))
        if entry is None or initial_stop is None:
            return
        initial_risk = abs(entry - initial_stop)
        if initial_risk <= 0:
            return
        if trade["side"] == "BUY":
            locked_stop = entry + (initial_risk * SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR)
        else:
            locked_stop = entry - (initial_risk * SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR)
        trade["stopLoss"] = _round_price(locked_stop)
        trade["stopMovedToBe"] = True
        trade["stopMoveReason"] = (
            f"Momentum TP1 hit; booked {SECTOR_MOMENTUM_PARTIAL_EXIT_PCT * 100:.0f}% "
            f"and locked runner SL at +{SECTOR_MOMENTUM_RUNNER_SL_LOCK_RR}R"
        )
        trade["status"] = "RUNNER"

    @staticmethod
    def _current_trade_rr(trade: dict[str, Any], price: float) -> float | None:
        entry = _to_float(trade.get("entry"))
        initial_stop = _to_float(trade.get("initialStopLoss") or trade.get("stopLoss"))
        if entry is None or initial_stop is None:
            return None
        risk = abs(entry - initial_stop)
        if risk <= 0:
            return None
        move = price - entry if trade.get("side") == "BUY" else entry - price
        return move / risk

    def close_trade_by_id(self, trade_id: str) -> dict[str, Any]:
        requested = str(trade_id or "").strip().upper()
        for key, trade in list(self.active_trades.items()):
            if str(trade.get("id") or "").upper() != requested:
                continue
            exit_price = _to_float(trade.get("currentPrice")) or _to_float(trade.get("entry"))
            if exit_price is None:
                return {"ok": False, "error": f"No current price available for {requested}."}
            closed = self._close_trade(key, trade, "MANUAL", exit_price)
            self._persist()
            return {"ok": True, "trade": closed}
        return {"ok": False, "error": f"Active trade {requested or '-'} was not found."}

    def _close_trade(self, key: str, trade: dict[str, Any], exit_reason: str, exit_price: float) -> dict[str, Any]:
        pnl = _trade_pnl(trade["side"], trade["entry"], exit_price, trade["quantity"])
        self.realized_pnl += pnl
        exit_time = _now_label()
        closed = {
            **trade,
            "exitReason": exit_reason,
            "exitPrice": _round_price(exit_price),
            "realizedPnl": _round_price(pnl),
            "entryTime": trade.get("entryTime") or trade.get("openedAt") or "-",
            "closedAt": exit_time,
            "exitTime": exit_time,
            "status": exit_reason,
        }
        self.closed_trades.append(closed)
        self.active_trades.pop(key, None)
        return closed


class NiftyOptionsPaperEngine:
    def __init__(self) -> None:
        self.initial_capital = NIFTY_OPTIONS_INITIAL_CAPITAL
        self.trade_allocation = NIFTY_OPTIONS_TRADE_ALLOCATION
        self.realized_pnl = 0.0
        self.candles: dict[str, list[dict[str, Any]]] = {}
        self.active_trades: dict[str, dict[str, Any]] = {}
        self.closed_trades: list[dict[str, Any]] = []
        self.used_confirmations: dict[str, int] = {}
        self.next_trade_id = 1
        self.last_ideas: list[dict[str, Any]] = []
        self.last_option_tiles: list[dict[str, Any]] = []
        self.last_idea_date: str | None = None
        self.last_saved_at: str | None = None
        self.persistence_error: str | None = None
        self._load()

    def update(
        self,
        sector_rows: list[dict[str, Any]],
        index_spots: dict[str, dict[str, Any]],
        option_quote_provider,
        market_open: bool = True,
        top_movers: dict[str, Any] | None = None,
        equity_key_provider=None,
        previous_m15_close_provider=None,
    ) -> dict[str, Any]:
        now = time.time()

        quote_cache: dict[str, dict[str, Any]] = {}

        def cached_option_quote(contract: dict[str, Any]) -> dict[str, Any]:
            key = self._trade_key(contract)
            if key not in quote_cache:
                quote_cache[key] = option_quote_provider(contract)
            return quote_cache[key]

        if market_open:
            self._mark_active_trades(cached_option_quote)
            if self._square_off_due(now):
                self._square_off_open_trades()

        for config in self._enabled_indexes():
            spot = self._spot_for_index(index_spots, config)
            if market_open:
                self._update_index_candle(config, spot, now)
        self.last_option_tiles = self._build_option_tiles(index_spots, cached_option_quote, now)

        if not market_open or not self._entry_session_is_open(now):
            self.last_ideas = self._retained_ideas([], now, self._session_status())
            if not self.last_ideas:
                self.last_idea_date = None
            self._persist()
            return self.snapshot()
        self._mark_active_trades(cached_option_quote)
        ideas = self._build_ideas(sector_rows, index_spots, cached_option_quote, now)
        opening_ideas = self._build_opening_mover_ideas(
            top_movers or {},
            cached_option_quote,
            equity_key_provider,
            previous_m15_close_provider,
            now,
        )
        ideas.extend(opening_ideas)
        ideas.sort(key=lambda idea: (bool(idea.get("ready")), _to_float(idea.get("score")) or 0), reverse=True)
        self._activate_ideas(ideas)
        self.last_ideas = self._retained_ideas(ideas, now)
        self.last_idea_date = _today_key() if ideas else None
        self._persist()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        active = list(self.active_trades.values())
        active_allocated = sum(_to_float(trade.get("allocation")) or 0 for trade in active)
        unrealized_pnl = sum(_to_float(trade.get("unrealizedPnl")) or 0 for trade in active)
        equity = self.initial_capital + self.realized_pnl + unrealized_pnl
        closed_count = len(self.closed_trades)
        winning_trades = [trade for trade in self.closed_trades if (_to_float(trade.get("realizedPnl")) or 0) > 0]
        losing_trades = [trade for trade in self.closed_trades if (_to_float(trade.get("realizedPnl")) or 0) < 0]
        gross_profit = sum(_to_float(trade.get("realizedPnl")) or 0 for trade in winning_trades)
        gross_loss = abs(sum(_to_float(trade.get("realizedPnl")) or 0 for trade in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss else None
        return {
            "initialCapital": self.initial_capital,
            "allocationPerTrade": self.trade_allocation,
            "availableCapital": self.initial_capital + self.realized_pnl - active_allocated,
            "allocatedCapital": active_allocated,
            "realizedPnl": _round_price(self.realized_pnl),
            "unrealizedPnl": _round_price(unrealized_pnl),
            "equity": _round_price(equity),
            "activeCount": len(active),
            "closedCount": closed_count,
            "totalTrades": len(active) + closed_count,
            "winningTrades": len(winning_trades),
            "losingTrades": len(losing_trades),
            "winRate": (len(winning_trades) / closed_count) * 100 if closed_count else None,
            "profitFactor": profit_factor,
            "profitFactorLabel": f"{profit_factor:.2f}" if profit_factor is not None else "No losses" if gross_profit > 0 else "-",
            "strategy": self._strategy_config(),
            "dataPolicy": {
                "priceSource": "Upstox option quotes only; options are never marked from NSE or mock prices",
                "signalSource": "NSE sector heatmap plus tradable index spot M5 confirmation",
                "entryPolicy": "paper option entry requires a resolved Upstox option instrument and live option LTP",
                "intradaySquareOff": f"open options auto-close at {PAPER_SQUARE_OFF_HOUR:02d}:{PAPER_SQUARE_OFF_MINUTE:02d}",
            },
            "sessionOpen": self._entry_session_is_open(),
            "sessionStatus": self._session_status(),
            "ideasDate": self.last_idea_date,
            "lastSavedAt": self.last_saved_at,
            "persistencePath": str(OPTIONS_PAPER_STATE_PATH),
            "persistenceError": self.persistence_error,
            "idea": self.last_ideas[0] if self.last_ideas else None,
            "ideas": self.last_ideas,
            "optionTiles": self.last_option_tiles,
            "openTrades": active,
            "activeTrades": active,
            "closedTrades": self.closed_trades[-12:],
            "allTrades": self._all_trades_newest_first(active),
        }

    def close_trade_by_id(self, trade_id: str, option_quote_provider) -> dict[str, Any]:
        requested = str(trade_id or "").strip().upper()
        for key, trade in list(self.active_trades.items()):
            if str(trade.get("id") or "").upper() != requested:
                continue
            self._mark_trade(trade, option_quote_provider)
            exit_price = _to_float(trade.get("currentPrice")) or _to_float(trade.get("entry"))
            if exit_price is None:
                return {"ok": False, "error": f"No current option premium available for {requested}."}
            closed = self._close_trade(key, trade, "MANUAL", exit_price)
            self._persist()
            return {"ok": True, "trade": closed}
        return {"ok": False, "error": f"Active options trade {requested or '-'} was not found."}

    def _build_ideas(
        self,
        sector_rows: list[dict[str, Any]],
        index_spots: dict[str, dict[str, Any]],
        option_quote_provider,
        now: float,
    ) -> list[dict[str, Any]]:
        ideas = [
            self._build_idea(config, sector_rows, index_spots, option_quote_provider, now)
            for config in self._enabled_indexes()
        ]
        ideas = [idea for idea in ideas if idea]
        ideas.sort(key=lambda idea: (bool(idea.get("ready")), _to_float(idea.get("score")) or 0), reverse=True)
        return ideas

    def _build_option_tiles(
        self,
        index_spots: dict[str, dict[str, Any]],
        option_quote_provider,
        now: float,
    ) -> list[dict[str, Any]]:
        tiles = []
        for config in self._enabled_indexes():
            index_symbol = str(config.get("symbol") or "NIFTY")
            index_name = str(config.get("name") or index_symbol)
            spot_row = self._spot_for_index(index_spots, config)
            spot = _to_float((spot_row or {}).get("last") or (spot_row or {}).get("current"))
            if spot is None:
                tiles.append(
                    {
                        "underlying": index_name,
                        "underlyingSymbol": index_symbol,
                        "spot": None,
                        "status": f"Waiting for {index_name} spot.",
                        "contracts": [],
                        "checkedAt": time.strftime("%H:%M:%S", time.localtime(now)),
                    }
                )
                continue
            contracts = []
            for option_type in ("CE", "PE"):
                contract = self._contract_for(config, option_type, spot)
                quote = option_quote_provider(contract)
                contracts.append(self._option_tile_contract(contract, quote))
            tiles.append(
                {
                    "underlying": index_name,
                    "underlyingSymbol": index_symbol,
                    "spot": _round_price(spot),
                    "status": "Upstox option quotes loaded" if any(c.get("ltp") is not None for c in contracts) else "Waiting for Upstox option quotes",
                    "contracts": contracts,
                    "checkedAt": time.strftime("%H:%M:%S", time.localtime(now)),
                }
            )
        return tiles

    @staticmethod
    def _option_tile_contract(contract: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": contract.get("symbol"),
            "underlying": contract.get("underlying"),
            "underlyingSymbol": contract.get("underlyingSymbol") or contract.get("underlying"),
            "expiry": quote.get("expiry") or contract.get("expiry"),
            "strike": contract.get("strike"),
            "optionType": contract.get("optionType"),
            "instrumentKey": quote.get("instrumentKey") or contract.get("instrumentKey"),
            "ltp": _round_price(_to_float(quote.get("ltp"))),
            "change": _round_price(_to_float(quote.get("change"))),
            "percentChange": _round_price(_to_float(quote.get("percentChange"))),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "spreadPct": quote.get("spreadPct"),
            "volume": quote.get("volume"),
            "oi": quote.get("oi"),
            "iv": quote.get("iv"),
            "quoteError": quote.get("quoteError"),
            "dataSource": quote.get("dataSource"),
        }

    def _build_idea(
        self,
        index_config: dict[str, Any],
        sector_rows: list[dict[str, Any]],
        index_spots: dict[str, dict[str, Any]],
        option_quote_provider,
        now: float,
    ) -> dict[str, Any] | None:
        index_symbol = str(index_config.get("symbol") or "NIFTY")
        index_name = str(index_config.get("name") or index_symbol)
        index_spot = self._spot_for_index(index_spots, index_config)
        if not sector_rows:
            return self._waiting_idea(index_config, "WAIT", "Waiting for sector heatmap rows.", None, None, now)
        if not index_spot:
            return self._waiting_idea(index_config, "WAIT", f"Waiting for {index_name} spot row.", None, None, now)

        spot = _to_float(index_spot.get("last") or index_spot.get("current"))
        day_open = _to_float(index_spot.get("open"))
        day_high = _to_float(index_spot.get("high"))
        day_low = _to_float(index_spot.get("low"))
        if spot is None or day_open is None or day_high is None or day_low is None:
            return self._waiting_idea(index_config, "WAIT", f"Waiting for complete {index_name} open/high/low/LTP.", index_spot, None, now)

        candle = self._latest_candle(index_symbol)
        if not candle:
            return self._waiting_idea(index_config, "WAIT", f"Waiting for the first completed {index_symbol} M5 candle.", index_spot, None, now)

        bias = self._heatmap_bias(self._sector_universe_rows(sector_rows, index_config))
        side = self._direction_from_bias(bias, spot, day_open, candle)
        if not side:
            return self._waiting_idea(index_config, "WAIT", f"No trade: {index_symbol} heatmap, breadth, spot, and M5 candle are not aligned.", index_spot, bias, now)

        option_type = "CE" if side == "BULLISH" else "PE"
        confirmation_key = f"INDEX_OPTIONS|{index_symbol}|{option_type}|Heatmap M5"
        confirmation_bucket = int(_to_float(candle.get("bucket")) or 0)
        ready_signal = self._spot_breaks_candle(side, spot, candle)
        confirmation_fresh = PaperTradingEngine._confirmation_is_fresh(candle, now)
        confirmation_used = self.used_confirmations.get(confirmation_key) == confirmation_bucket
        contract = self._contract_for(index_config, option_type, spot)
        quote = option_quote_provider(contract)
        premium = _to_float(quote.get("ltp"))
        stop_loss = premium * (1 - NIFTY_OPTIONS_PREMIUM_SL_PCT) if premium is not None else None
        target = premium * (1 + NIFTY_OPTIONS_PREMIUM_TARGET_PCT) if premium is not None else None
        lot_size = int(_to_float(index_config.get("lotSize")) or NIFTY_OPTIONS_LOT_SIZE)
        lots = int(self.trade_allocation // (premium * lot_size)) if premium and premium > 0 else 0
        quantity = lots * lot_size
        liquidity_ok, liquidity_status = self._liquidity_status(quote)
        active_key = self._trade_key(contract)
        if active_key in self.active_trades:
            status = "Already active"
        elif not ready_signal:
            status = f"Waiting for {index_symbol} to break the completed M5 candle."
        elif not confirmation_fresh:
            status = f"Confirmation older than {FRESH_CONFIRMATION_SECONDS}s; waiting for next M5 candle."
        elif confirmation_used:
            status = "Waiting for next M5 confirmation candle."
        elif not liquidity_ok:
            status = liquidity_status
        elif quantity <= 0:
            status = "Option premium is too high for configured allocation."
        elif self.snapshot()["availableCapital"] < self.trade_allocation:
            status = "Ready but options capital is fully allocated."
        else:
            status = f"Ready: {index_symbol} heatmap options buyer."

        ready = (
            active_key not in self.active_trades
            and ready_signal
            and confirmation_fresh
            and not confirmation_used
            and liquidity_ok
            and quantity > 0
            and self.snapshot()["availableCapital"] >= self.trade_allocation
        )
        score = self._idea_score(bias, ready_signal)
        generated_at = _now_label()
        return {
            "symbol": contract["symbol"],
            "underlying": index_name,
            "underlyingSymbol": index_symbol,
            "side": "BUY",
            "direction": side,
            "optionType": option_type,
            "thesis": "Index Heatmap Options Buyer",
            "thesisDetail": "Buy index CE/PE only when related heatmap breadth, index spot, and a completed M5 breakout agree.",
            "expiry": quote.get("expiry") or contract["expiry"],
            "strike": contract["strike"],
            "instrumentKey": quote.get("instrumentKey") or contract.get("instrumentKey"),
            "entry": _round_price(premium),
            "currentPrice": _round_price(premium),
            "stopLoss": _round_price(stop_loss),
            "target": _round_price(target),
            "lots": lots,
            "lotSize": lot_size,
            "quantity": quantity,
            "allocation": self.trade_allocation,
            "lossIfSl": _round_price((premium - stop_loss) * quantity) if premium is not None and stop_loss is not None else None,
            "profitIfTp": _round_price((target - premium) * quantity) if premium is not None and target is not None else None,
            "ready": ready,
            "status": status,
            "originalStatus": status,
            "fresh": True,
            "stale": False,
            "generatedAt": generated_at,
            "lastSeenAt": generated_at,
            "expiresAfterSeconds": NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
            "liquidityStatus": liquidity_status,
            "spreadPct": quote.get("spreadPct"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "volume": quote.get("volume"),
            "oi": quote.get("oi"),
            "quoteError": quote.get("quoteError"),
            "confirmationKey": confirmation_key,
            "confirmationBucket": confirmation_bucket,
            "confirmationFresh": confirmation_fresh,
            "confirmationUsed": confirmation_used,
            "spot": _round_price(spot),
            "spotOpen": _round_price(day_open),
            "spotHigh": _round_price(day_high),
            "spotLow": _round_price(day_low),
            "heatmapBias": bias,
            "score": round(score, 2),
            "m5": {
                "bucket": confirmation_bucket,
                "open": _round_price(candle["open"]),
                "high": _round_price(candle["high"]),
                "low": _round_price(candle["low"]),
                "close": _round_price(candle["close"]),
                "ticks": candle["ticks"],
                "startedAt": candle["startedAt"],
            },
        }

    def _build_opening_mover_ideas(
        self,
        top_movers: dict[str, Any],
        option_quote_provider,
        equity_key_provider,
        previous_m15_close_provider,
        now: float,
    ) -> list[dict[str, Any]]:
        generated_at = _now_label()
        now_dt = dt.datetime.fromtimestamp(now)
        today_key = _date_key(now_dt.date())
        entry_start = dt.datetime.combine(
            now_dt.date(),
            dt.time(
                OPENING_MOVER_OPTIONS_ENTRY_HOUR,
                OPENING_MOVER_OPTIONS_ENTRY_MINUTE,
                OPENING_MOVER_OPTIONS_ENTRY_SECOND,
            ),
        )
        entry_end = entry_start + dt.timedelta(seconds=max(1, OPENING_MOVER_OPTIONS_ENTRY_WINDOW_SECONDS))
        max_exit = dt.datetime.combine(now_dt.date(), dt.time(9, 15)) + dt.timedelta(minutes=OPENING_MOVER_OPTIONS_MAX_HOLD_MINUTES)
        if now_dt < entry_start:
            status = f"Waiting until {entry_start.strftime('%H:%M:%S')} for opening top mover entry."
            ready_time = False
        elif now_dt >= entry_end:
            status = f"Opening top mover entry window closed after {entry_end.strftime('%H:%M:%S')}."
            ready_time = False
        else:
            status = "Opening top mover entry window active."
            ready_time = True

        candidates = self._opening_mover_candidates(top_movers)
        if not candidates:
            return [self._opening_waiting_idea("Waiting for NSE F&O top gainer/loser.", now, generated_at)]

        ideas = [
            self._build_opening_mover_candidate_idea(
                candidate,
                option_quote_provider,
                equity_key_provider,
                previous_m15_close_provider,
                now,
                generated_at,
                today_key,
                status,
                ready_time,
                max_exit,
            )
            for candidate in candidates
        ]
        ideas.sort(key=lambda idea: (bool(idea.get("ready")), _to_float(idea.get("score")) or 0), reverse=True)
        return ideas

    def _build_opening_mover_candidate_idea(
        self,
        candidate: dict[str, Any],
        option_quote_provider,
        equity_key_provider,
        previous_m15_close_provider,
        now: float,
        generated_at: str,
        today_key: str,
        status: str,
        ready_time: bool,
        max_exit: dt.datetime,
    ) -> dict[str, Any]:
        symbol = str(candidate.get("symbol") or "").strip().upper()
        mover_direction = str(candidate.get("direction") or "")
        option_type = "CE" if mover_direction == "gainer" else "PE"
        direction = "BULLISH" if option_type == "CE" else "BEARISH"
        open_price = _to_float(candidate.get("open"))
        spot = _first_float(candidate.get("ltp"), open_price)
        confirmation_key = f"OPENING_MOVER_OPTIONS|{today_key}|{symbol}|{option_type}"
        if not symbol or open_price is None or spot is None:
            return self._opening_waiting_idea("Waiting for complete NSE top mover open/LTP.", now, generated_at, candidate)

        already_traded = self.used_confirmations.get(confirmation_key) == 1 or self._opening_mover_trade_exists(today_key, symbol, option_type)
        daily_count = self._opening_mover_trade_count(today_key)
        if already_traded:
            ready_time = False
            status = f"Opening top mover option trade already placed for {symbol} {option_type} today."
        elif daily_count >= max(1, OPENING_MOVER_OPTIONS_MAX_TRADES):
            ready_time = False
            status = f"Opening top mover max trades reached ({OPENING_MOVER_OPTIONS_MAX_TRADES})."

        equity_key = equity_key_provider(symbol) if equity_key_provider else None
        if not equity_key:
            return self._opening_idea_from_candidate(
                candidate,
                option_type,
                direction,
                None,
                None,
                None,
                None,
                False,
                f"{status} Upstox equity key missing for {symbol}.",
                generated_at,
                now,
                confirmation_key,
                max_exit,
            )

        previous_m15 = previous_m15_close_provider(symbol, equity_key) if previous_m15_close_provider else {}
        previous_close = _to_float((previous_m15 or {}).get("close"))
        if previous_close is None:
            return self._opening_idea_from_candidate(
                candidate,
                option_type,
                direction,
                None,
                None,
                None,
                None,
                False,
                f"{status} Previous final M15 close unavailable: {(previous_m15 or {}).get('error') or '-'}",
                generated_at,
                now,
                confirmation_key,
                max_exit,
                equity_key,
                previous_m15,
            )

        gap_ok = open_price > previous_close if option_type == "CE" else open_price < previous_close
        if not gap_ok:
            side_text = "above" if option_type == "CE" else "below"
            return self._opening_idea_from_candidate(
                candidate,
                option_type,
                direction,
                None,
                None,
                None,
                None,
                False,
                f"{status} Rejected: open {open_price:.2f} is not {side_text} yesterday final M15 close {previous_close:.2f}.",
                generated_at,
                now,
                confirmation_key,
                max_exit,
                equity_key,
                previous_m15,
            )

        contract = {
            "symbol": f"{symbol} ATM {option_type}",
            "underlying": symbol,
            "underlyingSymbol": symbol,
            "underlyingInstrumentKey": equity_key,
            "underlyingType": "EQUITY",
            "spot": spot,
            "optionType": option_type,
        }
        quote = option_quote_provider(contract)
        premium = _to_float(quote.get("ltp"))
        lot_size = int(_to_float(quote.get("lotSize")) or 0)
        quantity = lot_size
        stop_loss = premium * (1 - OPENING_MOVER_OPTIONS_SL_PCT) if premium is not None else None
        target = premium * OPENING_MOVER_OPTIONS_TARGET_MULTIPLE if premium is not None else None
        liquidity_ok, liquidity_status = self._opening_mover_liquidity_status(quote, lot_size)
        score = self._opening_mover_score(candidate, quote, previous_close)
        if not ready_time:
            final_status = status
        elif not liquidity_ok:
            final_status = liquidity_status
        elif quantity <= 0:
            final_status = "Stock option lot size unavailable."
        elif self.snapshot()["availableCapital"] < (premium or 0) * quantity:
            final_status = "Ready but options capital is fully allocated."
        else:
            final_status = f"Ready: opening {mover_direction} {symbol} ATM {option_type} buyer."
        ready = (
            ready_time
            and liquidity_ok
            and premium is not None
            and quantity > 0
            and self.snapshot()["availableCapital"] >= premium * quantity
        )
        return self._opening_idea_from_candidate(
            candidate,
            option_type,
            direction,
            quote,
            premium,
            stop_loss,
            target,
            ready,
            final_status,
            generated_at,
            now,
            confirmation_key,
            max_exit,
            equity_key,
            previous_m15,
            score,
        )

    def _opening_idea_from_candidate(
        self,
        candidate: dict[str, Any],
        option_type: str,
        direction: str,
        quote: dict[str, Any] | None,
        premium: float | None,
        stop_loss: float | None,
        target: float | None,
        ready: bool,
        status: str,
        generated_at: str,
        now: float,
        confirmation_key: str,
        max_exit: dt.datetime,
        equity_key: str | None = None,
        previous_m15: dict[str, Any] | None = None,
        score: float | None = None,
    ) -> dict[str, Any]:
        quote = quote or {}
        symbol = str(candidate.get("symbol") or "").strip().upper()
        lot_size = int(_to_float(quote.get("lotSize")) or 0)
        quantity = lot_size
        allocation = (premium or 0) * quantity
        return {
            "symbol": quote.get("symbol") or f"{symbol} ATM {option_type}",
            "underlying": symbol,
            "underlyingSymbol": symbol,
            "underlyingInstrumentKey": equity_key,
            "side": "BUY",
            "direction": direction,
            "optionType": option_type,
            "thesis": "Opening Top Gainer/Loser Option Buyer",
            "thesisDetail": "Buy one lot of the strongest NSE F&O opening gainer/loser ATM option at 09:15:30 only if today's open crosses yesterday's final M15 close.",
            "expiry": quote.get("expiry"),
            "strike": quote.get("strike"),
            "instrumentKey": quote.get("instrumentKey"),
            "entry": _round_price(premium),
            "currentPrice": _round_price(premium),
            "stopLoss": _round_price(stop_loss),
            "target": _round_price(target),
            "lots": 1 if lot_size else 0,
            "lotSize": lot_size,
            "quantity": quantity,
            "allocation": _round_price(allocation),
            "lossIfSl": _round_price((premium - stop_loss) * quantity) if premium is not None and stop_loss is not None else None,
            "profitIfTp": _round_price((target - premium) * quantity) if premium is not None and target is not None else None,
            "ready": ready,
            "status": status,
            "originalStatus": status,
            "fresh": True,
            "stale": False,
            "generatedAt": generated_at,
            "lastSeenAt": generated_at,
            "expiresAfterSeconds": NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
            "liquidityStatus": quote.get("quoteError") or ("Opening stock option quote OK." if ready else None),
            "spreadPct": quote.get("spreadPct"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "volume": quote.get("volume"),
            "oi": quote.get("oi"),
            "prevOi": quote.get("prevOi"),
            "oiChange": quote.get("oiChange"),
            "oiChangePct": _round_price(_to_float(quote.get("oiChangePct"))),
            "quoteError": quote.get("quoteError"),
            "confirmationKey": confirmation_key,
            "confirmationBucket": 1,
            "confirmationFresh": True,
            "confirmationUsed": self.used_confirmations.get(confirmation_key) == 1,
            "spot": _round_price(_first_float(candidate.get("ltp"), candidate.get("open"))),
            "spotOpen": _round_price(_to_float(candidate.get("open"))),
            "previousM15Close": _round_price(_to_float((previous_m15 or {}).get("close"))),
            "previousM15Candle": previous_m15,
            "maxExitAt": max_exit.strftime("%Y-%m-%d %H:%M:%S"),
            "maxExitTimestamp": max_exit.timestamp(),
            "topMover": candidate,
            "score": round(score if score is not None else 1000 + abs(_to_float(candidate.get("percentChange")) or 0), 2),
            "checkedAt": time.strftime("%H:%M:%S", time.localtime(now)),
        }

    def _opening_waiting_idea(
        self,
        status: str,
        now: float,
        generated_at: str,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "symbol": "-",
            "underlying": str((candidate or {}).get("symbol") or "-"),
            "underlyingSymbol": str((candidate or {}).get("symbol") or "-"),
            "side": "BUY",
            "direction": "WAIT",
            "optionType": "-",
            "thesis": "Opening Top Gainer/Loser Option Buyer",
            "thesisDetail": "Buy one lot of the strongest NSE F&O opening gainer/loser ATM option at 09:15:30 only if today's open crosses yesterday's final M15 close.",
            "ready": False,
            "status": status,
            "originalStatus": status,
            "fresh": True,
            "stale": False,
            "generatedAt": generated_at,
            "lastSeenAt": generated_at,
            "expiresAfterSeconds": NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
            "topMover": candidate,
            "score": 0,
            "checkedAt": time.strftime("%H:%M:%S", time.localtime(now)),
        }

    @staticmethod
    def _opening_mover_candidates(top_movers: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(top_movers, dict):
            return []
        gainers = top_movers.get("gainers")
        losers = top_movers.get("losers")
        if not isinstance(gainers, list):
            gainers = [top_movers.get("gainer")] if isinstance(top_movers.get("gainer"), dict) else []
        if not isinstance(losers, list):
            losers = [top_movers.get("loser")] if isinstance(top_movers.get("loser"), dict) else []
        rows = gainers[:OPENING_MOVER_OPTIONS_TOP_COUNT] + losers[:OPENING_MOVER_OPTIONS_TOP_COUNT]
        candidates = [row for row in rows if isinstance(row, dict) and str(row.get("symbol") or "").strip()]
        candidates.sort(key=lambda row: abs(_to_float(row.get("percentChange")) or 0), reverse=True)
        return candidates

    def _opening_mover_trade_exists(self, date_key: str, symbol: str, option_type: str) -> bool:
        clean_symbol = str(symbol or "").strip().upper()
        clean_type = str(option_type or "").strip().upper()
        for trade in [*self.active_trades.values(), *self.closed_trades]:
            if trade.get("thesis") != "Opening Top Gainer/Loser Option Buyer":
                continue
            if _trade_date_key(trade, "entryTime", "openedAt") == date_key:
                trade_symbol = str(trade.get("underlyingSymbol") or trade.get("underlying") or "").strip().upper()
                trade_type = str(trade.get("optionType") or "").strip().upper()
                if trade_symbol == clean_symbol and trade_type == clean_type:
                    return True
        return False

    def _opening_mover_trade_count(self, date_key: str) -> int:
        return sum(
            1
            for trade in [*self.active_trades.values(), *self.closed_trades]
            if trade.get("thesis") == "Opening Top Gainer/Loser Option Buyer"
            and _trade_date_key(trade, "entryTime", "openedAt") == date_key
        )

    @staticmethod
    def _opening_mover_score(candidate: dict[str, Any], quote: dict[str, Any], previous_close: float) -> float:
        move = abs(_to_float(candidate.get("percentChange")) or 0)
        open_price = _to_float(candidate.get("open"))
        gap_pct = abs(((open_price - previous_close) / previous_close) * 100) if open_price is not None and previous_close else 0
        volume_score = min((_to_float(quote.get("volume")) or 0) / 50000, 25)
        oi_score = min((_to_float(quote.get("oi")) or 0) / 5000, 40)
        oi_change_score = min(max(_to_float(quote.get("oiChange")) or 0, 0) / 2000, 60)
        spread_penalty = min((_to_float(quote.get("spreadPct")) or 0) * 2, 30)
        return (move * 5) + (gap_pct * 5) + volume_score + oi_score + oi_change_score - spread_penalty

    @staticmethod
    def _opening_mover_liquidity_status(quote: dict[str, Any], lot_size: int) -> tuple[bool, str]:
        if quote.get("quoteError"):
            return False, str(quote["quoteError"])
        premium = _to_float(quote.get("ltp"))
        if premium is None or premium <= 0:
            return False, "Waiting for Upstox stock option LTP."
        if lot_size <= 0:
            return False, "Stock option lot size unavailable."
        oi = _to_float(quote.get("oi"))
        if oi is None or oi <= 0:
            return False, "Waiting for Upstox stock option OI."
        return True, "Opening stock option quote OK."

    def _waiting_idea(
        self,
        index_config: dict[str, Any],
        direction: str,
        status: str,
        index_spot: dict[str, Any] | None,
        bias: dict[str, Any] | None,
        now: float,
    ) -> dict[str, Any]:
        index_symbol = str(index_config.get("symbol") or "NIFTY")
        index_name = str(index_config.get("name") or index_symbol)
        generated_at = _now_label()
        return {
            "symbol": "-",
            "underlying": index_name,
            "underlyingSymbol": index_symbol,
            "side": "BUY",
            "direction": direction,
            "optionType": "-",
            "thesis": "Index Heatmap Options Buyer",
            "thesisDetail": "Buy index CE/PE only when related heatmap breadth, index spot, and a completed M5 breakout agree.",
            "ready": False,
            "status": status,
            "originalStatus": status,
            "fresh": True,
            "stale": False,
            "generatedAt": generated_at,
            "lastSeenAt": generated_at,
            "expiresAfterSeconds": NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
            "spot": _round_price(_to_float((index_spot or {}).get("last") or (index_spot or {}).get("current"))),
            "heatmapBias": bias,
            "score": round(self._idea_score(bias or {}, False), 2),
            "checkedAt": time.strftime("%H:%M:%S", time.localtime(now)),
        }

    def _retained_ideas(
        self,
        fresh_ideas: list[dict[str, Any]],
        now: float,
        stale_reason: str = "Retained from previous refresh.",
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for idea in fresh_ideas:
            idea["originalStatus"] = self._base_idea_status(idea)
            merged[self._idea_display_key(idea)] = idea
        for old in self.last_ideas:
            key = self._idea_display_key(old)
            if key in merged:
                continue
            if not self._idea_is_recent(old, now):
                continue
            retained = {**old}
            retained["ready"] = False
            retained["fresh"] = False
            retained["stale"] = True
            retained["originalStatus"] = self._base_idea_status(old)
            retained["status"] = f"{stale_reason} Last signal: {retained['originalStatus']}"
            merged[key] = retained
        ideas = list(merged.values())
        ideas.sort(key=lambda idea: (bool(idea.get("fresh")), bool(idea.get("ready")), _to_float(idea.get("score")) or 0), reverse=True)
        return ideas

    @staticmethod
    def _idea_display_key(idea: dict[str, Any]) -> str:
        return "|".join(
            [
                str(idea.get("underlyingSymbol") or idea.get("underlying") or ""),
                str(idea.get("optionType") or ""),
                str(idea.get("strike") or ""),
                str(idea.get("expiry") or ""),
            ]
        )

    @staticmethod
    def _base_idea_status(idea: dict[str, Any]) -> str:
        text = str(idea.get("originalStatus") or idea.get("status") or "-")
        marker = "Last signal:"
        while marker in text:
            text = text.split(marker, 1)[1].strip()
        return text[:180] + "..." if len(text) > 180 else text

    @staticmethod
    def _idea_is_recent(idea: dict[str, Any], now: float) -> bool:
        text = str(idea.get("lastSeenAt") or idea.get("generatedAt") or "")
        parts = text.strip().split()
        stamp_text = " ".join(parts[:2]) if len(parts) >= 2 else text.strip()
        try:
            stamp = dt.datetime.strptime(stamp_text, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return False
        return 0 <= now - stamp <= NIFTY_OPTIONS_IDEA_RETENTION_SECONDS

    def _activate_ideas(self, ideas: list[dict[str, Any]]) -> None:
        index_placed = 0
        opening_placed = self._opening_mover_trade_count(_today_key())
        for idea in ideas:
            if not idea.get("ready"):
                continue
            if idea.get("thesis") == "Opening Top Gainer/Loser Option Buyer":
                if opening_placed >= max(1, OPENING_MOVER_OPTIONS_MAX_TRADES):
                    idea["ready"] = False
                    idea["status"] = f"Ready but opening mover max trades reached ({OPENING_MOVER_OPTIONS_MAX_TRADES})."
                    continue
                required_capital = _to_float(idea.get("allocation")) or 0
                if required_capital and self.snapshot()["availableCapital"] < required_capital:
                    idea["ready"] = False
                    idea["status"] = "Ready but options capital is fully allocated."
                    continue
            elif index_placed >= max(1, NIFTY_OPTIONS_MAX_NEW_TRADES_PER_REFRESH):
                idea["ready"] = False
                idea["status"] = "Ready but another higher-ranked options setup was placed this refresh."
                continue
            trade = self._trade_from_idea(idea)
            self.active_trades[trade["key"]] = trade
            self.used_confirmations[str(idea.get("confirmationKey") or "")] = int(_to_float(idea.get("confirmationBucket")) or 0)
            idea["status"] = "Options paper trade placed."
            idea["ready"] = False
            if trade.get("thesis") == "Opening Top Gainer/Loser Option Buyer":
                opening_placed += 1
            else:
                index_placed += 1

    def _trade_from_idea(self, idea: dict[str, Any]) -> dict[str, Any]:
        trade_id = f"OPT{self.next_trade_id:04d}"
        self.next_trade_id += 1
        entry_time = _now_label()
        entry_price = _to_float(idea.get("entry"))
        return {
            "id": trade_id,
            "key": self._trade_key(idea),
            "symbol": idea["symbol"],
            "underlying": idea["underlying"],
            "underlyingSymbol": idea.get("underlyingSymbol"),
            "side": "BUY",
            "direction": idea["direction"],
            "optionType": idea["optionType"],
            "thesis": idea["thesis"],
            "expiry": idea["expiry"],
            "strike": idea["strike"],
            "instrumentKey": idea.get("instrumentKey"),
            "entry": idea["entry"],
            "currentPrice": idea["currentPrice"],
            "stopLoss": idea["stopLoss"],
            "initialStopLoss": idea["stopLoss"],
            "target": idea["target"],
            "highSinceEntry": _round_price(entry_price),
            "lowSinceEntry": _round_price(entry_price),
            "highSinceEntryAt": entry_time,
            "lowSinceEntryAt": entry_time,
            "maxFavorablePrice": _round_price(entry_price),
            "maxAdversePrice": _round_price(entry_price),
            "maxFavorablePct": 0.0 if entry_price is not None else None,
            "maxAdversePct": 0.0 if entry_price is not None else None,
            "lots": idea["lots"],
            "lotSize": idea["lotSize"],
            "quantity": idea["quantity"],
            "allocation": _to_float(idea.get("allocation")) or self.trade_allocation,
            "unrealizedPnl": 0.0,
            "bid": idea.get("bid"),
            "ask": idea.get("ask"),
            "spreadPct": idea.get("spreadPct"),
            "volume": idea.get("volume"),
            "oi": idea.get("oi"),
            "prevOi": idea.get("prevOi"),
            "oiChange": idea.get("oiChange"),
            "oiChangePct": idea.get("oiChangePct"),
            "confirmationKey": idea.get("confirmationKey"),
            "confirmationBucket": idea.get("confirmationBucket"),
            "entrySpot": idea.get("spot"),
            "underlyingInstrumentKey": idea.get("underlyingInstrumentKey"),
            "previousM15Close": idea.get("previousM15Close"),
            "previousM15Candle": idea.get("previousM15Candle"),
            "maxExitAt": idea.get("maxExitAt"),
            "maxExitTimestamp": idea.get("maxExitTimestamp"),
            "topMover": idea.get("topMover"),
            "entryTime": entry_time,
            "openedAt": entry_time,
            "status": "ACTIVE",
        }

    def _mark_active_trades(self, option_quote_provider) -> None:
        for key, trade in list(self.active_trades.items()):
            self._mark_trade(trade, option_quote_provider)
            price = _to_float(trade.get("currentPrice"))
            stop_loss = _to_float(trade.get("stopLoss"))
            target = _to_float(trade.get("target"))
            if price is None or stop_loss is None:
                continue
            if price <= stop_loss:
                self._close_trade(key, trade, "SL", stop_loss)
            elif target is not None and price >= target:
                self._close_trade(key, trade, "TP", target)
            elif self._max_hold_due(trade):
                self._close_trade(key, trade, "M15_EXIT", price)

    def _mark_trade(self, trade: dict[str, Any], option_quote_provider) -> None:
        quote = option_quote_provider(trade)
        price = _to_float(quote.get("ltp"))
        if price is None:
            trade["quoteError"] = quote.get("quoteError") or "Upstox option quote missing"
            return
        trade["currentPrice"] = _round_price(price)
        trade["unrealizedPnl"] = _round_price(_long_pnl(trade["entry"], price, trade["quantity"]))
        self._update_option_extremes(trade, price)
        trade["bid"] = quote.get("bid")
        trade["ask"] = quote.get("ask")
        trade["spreadPct"] = quote.get("spreadPct")
        trade["volume"] = quote.get("volume")
        trade["oi"] = quote.get("oi")
        trade["prevOi"] = quote.get("prevOi")
        trade["oiChange"] = quote.get("oiChange")
        trade["oiChangePct"] = _round_price(_to_float(quote.get("oiChangePct")))
        trade["quoteError"] = None

    @staticmethod
    def _max_hold_due(trade: dict[str, Any], now: float | None = None) -> bool:
        max_exit = _to_float(trade.get("maxExitTimestamp"))
        return bool(max_exit and (now or time.time()) >= max_exit)

    @staticmethod
    def _update_option_extremes(trade: dict[str, Any], price: float) -> None:
        entry = _to_float(trade.get("entry"))
        if entry is None or entry <= 0:
            return
        high = _to_float(trade.get("highSinceEntry"))
        low = _to_float(trade.get("lowSinceEntry"))
        now_label = _now_label()
        if high is None or price > high:
            trade["highSinceEntry"] = _round_price(price)
            trade["highSinceEntryAt"] = now_label
        if low is None or price < low:
            trade["lowSinceEntry"] = _round_price(price)
            trade["lowSinceEntryAt"] = now_label
        high = _to_float(trade.get("highSinceEntry"))
        low = _to_float(trade.get("lowSinceEntry"))
        trade["maxFavorablePrice"] = _round_price(high)
        trade["maxAdversePrice"] = _round_price(low)
        trade["maxFavorablePct"] = _round_price(((high - entry) / entry) * 100) if high is not None else None
        trade["maxAdversePct"] = _round_price(((low - entry) / entry) * 100) if low is not None else None

    def _square_off_open_trades(self) -> None:
        for key, trade in list(self.active_trades.items()):
            exit_price = _to_float(trade.get("currentPrice")) or _to_float(trade.get("entry"))
            if exit_price is not None:
                self._close_trade(key, trade, "EOD", exit_price)

    def _close_trade(self, key: str, trade: dict[str, Any], exit_reason: str, exit_price: float) -> dict[str, Any]:
        pnl = _long_pnl(trade["entry"], exit_price, trade["quantity"])
        self.realized_pnl += pnl
        exit_time = _now_label()
        closed = {
            **trade,
            "exitReason": exit_reason,
            "exitPrice": _round_price(exit_price),
            "realizedPnl": _round_price(pnl),
            "entryTime": trade.get("entryTime") or trade.get("openedAt") or "-",
            "closedAt": exit_time,
            "exitTime": exit_time,
            "status": exit_reason,
        }
        self.closed_trades.append(closed)
        self.active_trades.pop(key, None)
        return closed

    def _update_index_candle(self, index_config: dict[str, Any], index_spot: dict[str, Any] | None, now: float) -> None:
        price = _to_float((index_spot or {}).get("last") or (index_spot or {}).get("current"))
        if price is None:
            return
        index_symbol = str(index_config.get("symbol") or (index_spot or {}).get("symbol") or "NIFTY")
        bucket = int(now // M5_SECONDS) * M5_SECONDS
        candles = self.candles.setdefault(index_symbol, [])
        if not candles or candles[-1]["bucket"] != bucket:
            candles.append(
                {
                    "bucket": bucket,
                    "startedAt": time.strftime("%H:%M:%S", time.localtime(bucket)),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "ticks": 1,
                }
            )
            del candles[:-12]
            return
        candle = candles[-1]
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price
        candle["ticks"] += 1

    def _latest_candle(self, symbol: str) -> dict[str, Any] | None:
        candles = self.candles.get(symbol) or []
        return candles[-2] if len(candles) >= 2 else None

    def _enabled_indexes(self) -> list[dict[str, Any]]:
        return [dict(config) for config in NIFTY_OPTIONS_INDEXES if config.get("enabled", True)]

    @staticmethod
    def _spot_for_index(
        index_spots: dict[str, dict[str, Any]],
        index_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(index_spots, dict):
            return None
        keys = [
            str(index_config.get("symbol") or ""),
            str(index_config.get("nseSymbol") or ""),
            str(index_config.get("name") or ""),
        ]
        normalized = {str(key or "").strip().upper(): value for key, value in index_spots.items()}
        for key in keys:
            spot = normalized.get(key.strip().upper())
            if spot:
                return spot
        nse_symbol = str(index_config.get("nseSymbol") or "").strip().upper()
        if nse_symbol:
            return next(
                (
                    spot for spot in index_spots.values()
                    if _clean_index_symbol(str(spot.get("symbol") or "")).upper() == nse_symbol
                ),
                None,
            )
        return None

    @staticmethod
    def _sector_universe_rows(
        sector_rows: list[dict[str, Any]],
        index_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        wanted = {
            str(symbol or "").strip().upper()
            for symbol in (index_config.get("sectorSymbols") or ())
            if str(symbol or "").strip()
        }
        if not wanted:
            return sector_rows
        rows = [
            row for row in sector_rows
            if _clean_index_symbol(str(row.get("symbol") or "")).upper() in wanted
        ]
        return rows or sector_rows

    def _heatmap_bias(self, sector_rows: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [row for row in sector_rows if _to_float(row.get("percentChange")) is not None]
        total = len(valid)
        green = len([row for row in valid if (_to_float(row.get("percentChange")) or 0) > 0])
        red = len([row for row in valid if (_to_float(row.get("percentChange")) or 0) < 0])
        total_breadth_count = sum((row.get("advances") or 0) + (row.get("declines") or 0) + (row.get("unchanged") or 0) for row in valid)
        net_breadth = (
            sum((row.get("advances") or 0) - (row.get("declines") or 0) for row in valid) / total_breadth_count
            if total_breadth_count
            else 0
        )
        top_gain = max((_to_float(row.get("percentChange")) or 0 for row in valid), default=0)
        top_loss = min((_to_float(row.get("percentChange")) or 0 for row in valid), default=0)
        return {
            "totalSectors": total,
            "greenSectors": green,
            "redSectors": red,
            "greenRatio": (green / total) if total else 0,
            "redRatio": (red / total) if total else 0,
            "netBreadth": net_breadth,
            "topGain": top_gain,
            "topLoss": top_loss,
        }

    @staticmethod
    def _idea_score(bias: dict[str, Any], ready_signal: bool) -> float:
        top_gain = abs(_to_float(bias.get("topGain")) or 0)
        top_loss = abs(_to_float(bias.get("topLoss")) or 0)
        breadth = abs(_to_float(bias.get("netBreadth")) or 0)
        green_ratio = _to_float(bias.get("greenRatio")) or 0
        red_ratio = _to_float(bias.get("redRatio")) or 0
        return max(top_gain, top_loss) + (breadth * 3) + (max(green_ratio, red_ratio) * 2) + (1 if ready_signal else 0)

    def _direction_from_bias(self, bias: dict[str, Any], spot: float, day_open: float, candle: dict[str, Any]) -> str | None:
        bullish = (
            (_to_float(bias.get("topGain")) or 0) >= BUY_SECTOR_THRESHOLD
            and (_to_float(bias.get("greenRatio")) or 0) >= NIFTY_OPTIONS_MIN_SECTOR_RATIO
            and (_to_float(bias.get("netBreadth")) or 0) >= NIFTY_OPTIONS_MIN_BREADTH
            and spot > day_open
            and PaperTradingEngine._candle_confirms(candle, "BUY")
        )
        bearish = (
            (_to_float(bias.get("topLoss")) or 0) <= SELL_SECTOR_THRESHOLD
            and (_to_float(bias.get("redRatio")) or 0) >= NIFTY_OPTIONS_MIN_SECTOR_RATIO
            and (_to_float(bias.get("netBreadth")) or 0) <= -NIFTY_OPTIONS_MIN_BREADTH
            and spot < day_open
            and PaperTradingEngine._candle_confirms(candle, "SHORT")
        )
        if bullish == bearish:
            return None
        return "BULLISH" if bullish else "BEARISH"

    @staticmethod
    def _spot_breaks_candle(direction: str, spot: float, candle: dict[str, Any]) -> bool:
        if direction == "BULLISH":
            return spot >= candle["high"] * (1 + NIFTY_OPTIONS_BREAKOUT_BUFFER)
        return spot <= candle["low"] * (1 - NIFTY_OPTIONS_BREAKOUT_BUFFER)

    @staticmethod
    def _contract_for(index_config: dict[str, Any], option_type: str, spot: float) -> dict[str, Any]:
        index_symbol = str(index_config.get("symbol") or "NIFTY")
        strike_interval = int(_to_float(index_config.get("strikeInterval")) or NIFTY_OPTIONS_STRIKE_INTERVAL)
        base = round(spot / strike_interval) * strike_interval
        offset = NIFTY_OPTIONS_STRIKE_OFFSET_STEPS * strike_interval
        strike = base + offset if option_type == "CE" else base - offset
        expiry = NiftyOptionsPaperEngine._nearest_expiry_date()
        symbol = f"{index_symbol} {expiry.strftime('%d%b%Y').upper()} {int(strike)} {option_type}"
        return {
            "symbol": symbol,
            "underlying": index_symbol,
            "underlyingSymbol": index_symbol,
            "underlyingName": index_config.get("name"),
            "nseSymbol": index_config.get("nseSymbol"),
            "expiry": _date_key(expiry),
            "strike": int(strike),
            "optionType": option_type,
            "lotSize": int(_to_float(index_config.get("lotSize")) or NIFTY_OPTIONS_LOT_SIZE),
        }

    @staticmethod
    def _nearest_expiry_date(now: dt.datetime | None = None) -> dt.date:
        now = now or dt.datetime.now()
        days = (NIFTY_OPTIONS_EXPIRY_WEEKDAY - now.weekday()) % 7
        expiry = now.date() + dt.timedelta(days=days)
        skip_time = dt.time(NIFTY_OPTIONS_EXPIRY_SKIP_HOUR, NIFTY_OPTIONS_EXPIRY_SKIP_MINUTE)
        if days == 0 and now.time() >= skip_time:
            expiry += dt.timedelta(days=7)
        return expiry

    @staticmethod
    def _liquidity_status(quote: dict[str, Any]) -> tuple[bool, str]:
        if quote.get("quoteError"):
            return False, str(quote["quoteError"])
        premium = _to_float(quote.get("ltp"))
        if premium is None:
            return False, "Waiting for Upstox option LTP."
        if premium < NIFTY_OPTIONS_MIN_PREMIUM or premium > NIFTY_OPTIONS_MAX_PREMIUM:
            return False, f"Rejected: premium outside {NIFTY_OPTIONS_MIN_PREMIUM:.0f}-{NIFTY_OPTIONS_MAX_PREMIUM:.0f}."
        spread_pct = _to_float(quote.get("spreadPct"))
        if spread_pct is None:
            return False, "Waiting for Upstox bid/ask spread."
        if spread_pct > NIFTY_OPTIONS_MAX_SPREAD_PCT * 100:
            return False, f"Rejected: spread above {NIFTY_OPTIONS_MAX_SPREAD_PCT * 100:.1f}%."
        volume = _to_float(quote.get("volume"))
        if volume is not None and volume < NIFTY_OPTIONS_MIN_VOLUME:
            return False, f"Rejected: volume below {NIFTY_OPTIONS_MIN_VOLUME}."
        oi = _to_float(quote.get("oi"))
        if oi is not None and oi < NIFTY_OPTIONS_MIN_OI:
            return False, f"Rejected: OI below {NIFTY_OPTIONS_MIN_OI}."
        return True, "Liquidity OK."

    @staticmethod
    def _trade_key(contract: dict[str, Any]) -> str:
        underlying = str(contract.get("underlyingSymbol") or contract.get("underlying") or "NIFTY").upper()
        return "|".join(
            [
                underlying,
                str(contract.get("expiry") or ""),
                str(contract.get("strike") or ""),
                str(contract.get("optionType") or ""),
            ]
        )

    @staticmethod
    def _session_is_open(now: float | None = None) -> bool:
        return PaperTradingEngine._session_is_open(now)

    @staticmethod
    def _square_off_due(now: float | None = None) -> bool:
        return PaperTradingEngine._square_off_due(now)

    def _entry_session_is_open(self, now: float | None = None) -> bool:
        return self._session_is_open(now) and not self._square_off_due(now)

    def _session_status(self) -> str:
        if self._square_off_due():
            return f"Options square-off active after {PAPER_SQUARE_OFF_HOUR:02d}:{PAPER_SQUARE_OFF_MINUTE:02d}"
        if self._session_is_open():
            return "Options paper engine active"
        return f"Waiting until {PAPER_START_HOUR:02d}:{PAPER_START_MINUTE:02d} to start options paper trading"

    def _all_trades_newest_first(self, active: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trades = [*active, *self.closed_trades]
        return sorted(
            trades,
            key=lambda trade: str(trade.get("entryTime") or trade.get("openedAt") or ""),
            reverse=True,
        )

    def _load(self) -> None:
        if not OPTIONS_PAPER_STATE_PATH.exists():
            return
        try:
            payload = json.loads(OPTIONS_PAPER_STATE_PATH.read_text(encoding="utf-8"))
            self.initial_capital = _to_float(payload.get("initialCapital")) or NIFTY_OPTIONS_INITIAL_CAPITAL
            self.trade_allocation = _to_float(payload.get("allocationPerTrade")) or NIFTY_OPTIONS_TRADE_ALLOCATION
            self.realized_pnl = _to_float(payload.get("realizedPnl")) or 0.0
            self.candles = payload.get("candles") if isinstance(payload.get("candles"), dict) else {}
            self.used_confirmations = PaperTradingEngine._normalize_used_confirmations(payload.get("usedConfirmations"))
            open_trades = payload.get("openTrades") or payload.get("activeTrades")
            self.active_trades = open_trades if isinstance(open_trades, dict) else {}
            self.closed_trades = payload.get("closedTrades") if isinstance(payload.get("closedTrades"), list) else []
            self.last_idea_date = _valid_date_key(payload.get("ideasDate"))
            if self.last_idea_date == _today_key() and isinstance(payload.get("ideas"), list):
                self.last_ideas = payload["ideas"]
            elif self.last_idea_date == _today_key() and isinstance(payload.get("idea"), dict):
                self.last_ideas = [payload["idea"]]
            else:
                self.last_ideas = []
            self.last_option_tiles = payload.get("optionTiles") if isinstance(payload.get("optionTiles"), list) else []
            self.next_trade_id = int(payload.get("nextTradeId") or self._next_trade_id_from_history())
            self.last_saved_at = payload.get("lastSavedAt") or payload.get("savedAt")
            self._normalize_loaded_trades()
            self.persistence_error = None
        except Exception as exc:  # noqa: BLE001
            self.persistence_error = f"Could not load options paper trading state: {exc}"

    def _persist(self) -> None:
        payload = {
            "schemaVersion": 1,
            "savedAt": _now_label(),
            "initialCapital": self.initial_capital,
            "allocationPerTrade": self.trade_allocation,
            "realizedPnl": self.realized_pnl,
            "nextTradeId": self.next_trade_id,
            "candles": self.candles,
            "usedConfirmations": self.used_confirmations,
            "openTrades": self.active_trades,
            "activeTrades": self.active_trades,
            "closedTrades": self.closed_trades,
            "ideasDate": self.last_idea_date,
            "ideas": self.last_ideas,
            "optionTiles": self.last_option_tiles,
        }
        try:
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            temp_path = OPTIONS_PAPER_STATE_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            temp_path.replace(OPTIONS_PAPER_STATE_PATH)
            self.last_saved_at = payload["savedAt"]
            self.persistence_error = None
        except Exception as exc:  # noqa: BLE001
            self.persistence_error = f"Could not save options paper trading state: {exc}"

    def _normalize_loaded_trades(self) -> None:
        for trade in self.active_trades.values():
            trade["entryTime"] = trade.get("entryTime") or trade.get("openedAt") or "-"
            trade["openedAt"] = trade["entryTime"]
            trade["quantity"] = int(_to_float(trade.get("quantity")) or 0)
            self._normalize_option_extremes(trade)
        for trade in self.closed_trades:
            trade["entryTime"] = trade.get("entryTime") or trade.get("openedAt") or "-"
            trade["openedAt"] = trade["entryTime"]
            trade["exitTime"] = trade.get("exitTime") or trade.get("closedAt") or "-"
            trade["closedAt"] = trade["exitTime"]
            trade["quantity"] = int(_to_float(trade.get("quantity")) or 0)
            self._normalize_option_extremes(trade)

    @staticmethod
    def _normalize_option_extremes(trade: dict[str, Any]) -> None:
        entry = _to_float(trade.get("entry"))
        current = _to_float(trade.get("currentPrice"))
        baseline = current if current is not None else entry
        if baseline is None or entry is None or entry <= 0:
            return
        opened_at = trade.get("entryTime") or trade.get("openedAt") or "-"
        trade["highSinceEntry"] = _round_price(_first_float(trade.get("highSinceEntry"), baseline))
        trade["lowSinceEntry"] = _round_price(_first_float(trade.get("lowSinceEntry"), baseline))
        trade["highSinceEntryAt"] = trade.get("highSinceEntryAt") or opened_at
        trade["lowSinceEntryAt"] = trade.get("lowSinceEntryAt") or opened_at
        high = _to_float(trade.get("highSinceEntry"))
        low = _to_float(trade.get("lowSinceEntry"))
        trade["maxFavorablePrice"] = _round_price(_first_float(trade.get("maxFavorablePrice"), high))
        trade["maxAdversePrice"] = _round_price(_first_float(trade.get("maxAdversePrice"), low))
        trade["maxFavorablePct"] = _round_price(((high - entry) / entry) * 100) if high is not None else None
        trade["maxAdversePct"] = _round_price(((low - entry) / entry) * 100) if low is not None else None

    def _next_trade_id_from_history(self) -> int:
        max_id = 0
        for trade in [*self.active_trades.values(), *self.closed_trades]:
            text = str(trade.get("id") or "")
            if text.startswith("OPT") and text[3:].isdigit():
                max_id = max(max_id, int(text[3:]))
        return max_id + 1

    @staticmethod
    def _strategy_config() -> dict[str, Any]:
        return {
            "initialCapital": NIFTY_OPTIONS_INITIAL_CAPITAL,
            "allocationPerTrade": NIFTY_OPTIONS_TRADE_ALLOCATION,
            "lotSize": NIFTY_OPTIONS_LOT_SIZE,
            "strikeInterval": NIFTY_OPTIONS_STRIKE_INTERVAL,
            "expiryWeekday": NIFTY_OPTIONS_EXPIRY_WEEKDAY,
            "minSectorRatio": NIFTY_OPTIONS_MIN_SECTOR_RATIO,
            "minBreadth": NIFTY_OPTIONS_MIN_BREADTH,
            "breakoutBufferPct": NIFTY_OPTIONS_BREAKOUT_BUFFER * 100,
            "premiumSlPct": NIFTY_OPTIONS_PREMIUM_SL_PCT * 100,
            "premiumTargetPct": NIFTY_OPTIONS_PREMIUM_TARGET_PCT * 100,
            "minPremium": NIFTY_OPTIONS_MIN_PREMIUM,
            "maxPremium": NIFTY_OPTIONS_MAX_PREMIUM,
            "maxSpreadPct": NIFTY_OPTIONS_MAX_SPREAD_PCT * 100,
            "minVolume": NIFTY_OPTIONS_MIN_VOLUME,
            "minOi": NIFTY_OPTIONS_MIN_OI,
            "maxNewTradesPerRefresh": NIFTY_OPTIONS_MAX_NEW_TRADES_PER_REFRESH,
            "ideaRetentionSeconds": NIFTY_OPTIONS_IDEA_RETENTION_SECONDS,
            "openingMover": {
                "thesis": "Opening Top Gainer/Loser Option Buyer",
                "entryTime": f"{OPENING_MOVER_OPTIONS_ENTRY_HOUR:02d}:{OPENING_MOVER_OPTIONS_ENTRY_MINUTE:02d}:{OPENING_MOVER_OPTIONS_ENTRY_SECOND:02d}",
                "entryWindowSeconds": OPENING_MOVER_OPTIONS_ENTRY_WINDOW_SECONDS,
                "maxHoldMinutes": OPENING_MOVER_OPTIONS_MAX_HOLD_MINUTES,
                "lots": 1,
                "topCountPerSide": OPENING_MOVER_OPTIONS_TOP_COUNT,
                "maxTrades": OPENING_MOVER_OPTIONS_MAX_TRADES,
                "stopLossPct": OPENING_MOVER_OPTIONS_SL_PCT * 100,
                "targetMultiple": OPENING_MOVER_OPTIONS_TARGET_MULTIPLE,
            },
            "indexes": [
                {
                    "symbol": config.get("symbol"),
                    "name": config.get("name"),
                    "lotSize": config.get("lotSize"),
                    "strikeInterval": config.get("strikeInterval"),
                    "enabled": config.get("enabled", True),
                }
                for config in NIFTY_OPTIONS_INDEXES
            ],
        }


class NSEClient:
    def __init__(self) -> None:
        self.cookies = cookiejar.CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookies))
        self.context = ssl.create_default_context()
        self.last_cookie_refresh = 0.0

    def fetch_all_indices(self) -> dict[str, Any]:
        return self._fetch_with_cookie_retry(NSE_ALL_INDICES_API)

    def fetch_sector_stocks(self, index_symbol: str) -> dict[str, Any]:
        encoded = parse.quote(index_symbol, safe="")
        return self._fetch_with_cookie_retry(
            f"{NSE_STOCK_INDICES_API}&symbol={encoded}",
            referer=NSE_LIVE_EQUITY_URL,
            warm_url=NSE_LIVE_EQUITY_URL,
        )

    def fetch_quote_equity(self, symbol: str) -> dict[str, Any]:
        encoded = parse.quote(symbol, safe="")
        return self._fetch_with_cookie_retry(
            f"{NSE_QUOTE_EQUITY_API}?symbol={encoded}",
            referer=NSE_LIVE_EQUITY_URL,
            warm_url=NSE_LIVE_EQUITY_URL,
        )

    def fetch_market_status(self) -> dict[str, Any]:
        return self._fetch_with_cookie_retry(NSE_MARKET_STATUS_API)

    def fetch_trading_holidays(self) -> dict[str, Any]:
        return self._fetch_with_cookie_retry(NSE_HOLIDAY_API)

    def fetch_top_gainers(self) -> dict[str, Any]:
        return self._fetch_with_cookie_retry(
            NSE_TOP_GAINERS_API,
            referer=NSE_TOP_GAINERS_LOSERS_URL,
            warm_url=NSE_TOP_GAINERS_LOSERS_URL,
        )

    def fetch_top_losers(self) -> dict[str, Any]:
        return self._fetch_with_cookie_retry(
            NSE_TOP_LOSERS_API,
            referer=NSE_TOP_GAINERS_LOSERS_URL,
            warm_url=NSE_TOP_GAINERS_LOSERS_URL,
        )

    def _fetch_with_cookie_retry(
        self,
        url: str,
        referer: str = NSE_HEATMAP_URL,
        warm_url: str = NSE_HEATMAP_URL,
    ) -> dict[str, Any]:
        if time.time() - self.last_cookie_refresh > 600 or not list(self.cookies):
            self._warm_cookies(warm_url=warm_url)
        try:
            return self._get_json(url, referer=referer)
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                self._warm_cookies(force=True, warm_url=warm_url)
                return self._get_json(url, referer=referer)
            raise

    def _warm_cookies(self, force: bool = False, warm_url: str = NSE_HEATMAP_URL) -> None:
        if not force and time.time() - self.last_cookie_refresh < 60 and list(self.cookies):
            return
        req = request.Request(warm_url, headers=self._headers(NSE_HOME))
        with self._open_with_transient_retry(req, timeout=15) as response:
            response.read(2048)
        self.last_cookie_refresh = time.time()

    def _get_json(self, url: str, referer: str = NSE_HEATMAP_URL) -> dict[str, Any]:
        req = request.Request(url, headers=self._headers(referer))
        with self._open_with_transient_retry(req, timeout=15) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8"))

    def _open_with_transient_retry(self, req: request.Request, timeout: int):
        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                return self.opener.open(req, timeout=timeout)
            except OSError as exc:
                last_exc = exc
                if not _is_transient_socket_error(exc) or attempt >= 2:
                    raise
                time.sleep(0.4 * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError("NSE request failed before it was attempted")

    @staticmethod
    def _headers(referer: str) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
            "Connection": "keep-alive",
        }


class UpstoxInstrumentResolver:
    def __init__(self, token: str) -> None:
        self.token = token
        self.cache_path = UPSTOX_INSTRUMENT_CACHE_PATH
        self.lock = threading.RLock()
        self.cache = self._load_cache()
        self.cache.update(self._override_cache())
        self.last_error: str | None = None

    def resolve(self, symbols: list[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        missing = []
        with self.lock:
            for symbol in self._clean_symbols(symbols):
                cached = self.cache.get(symbol)
                instrument_key = str(cached.get("instrument_key") or "") if isinstance(cached, dict) else ""
                if instrument_key:
                    resolved[symbol] = instrument_key
                else:
                    missing.append(symbol)

        changed = False
        for symbol in missing:
            instrument = self._search_symbol(symbol)
            if not instrument:
                continue
            instrument_key = str(instrument.get("instrument_key") or "")
            if not instrument_key:
                continue
            resolved[symbol] = instrument_key
            with self.lock:
                self.cache[symbol] = {
                    "instrument_key": instrument_key,
                    "trading_symbol": instrument.get("trading_symbol") or symbol,
                    "name": instrument.get("name") or instrument.get("short_name") or "",
                    "resolvedAt": _now_label(),
                }
                changed = True
        if changed:
            self._save_cache()
        return resolved

    def _search_symbol(self, symbol: str) -> dict[str, Any] | None:
        params = parse.urlencode(
            {
                "query": symbol,
                "exchanges": "NSE",
                "segments": "EQ",
                "instrument_types": "EQ",
                "page_number": "1",
                "records": "10",
            }
        )
        req = request.Request(
            f"{UPSTOX_API_BASE_URL}/instruments/search?{params}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with request.urlopen(req, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - keep NSE polling alive when Upstox lookup fails
            self.last_error = f"{symbol}: {exc}"
            return None

        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return None
        symbol_upper = symbol.upper()
        exact = [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("segment") or "").upper() == "NSE_EQ"
            and str(row.get("instrument_type") or "").upper() == "EQ"
            and str(row.get("trading_symbol") or "").upper() == symbol_upper
        ]
        if exact:
            self.last_error = None
            return exact[0]
        fallback = [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("segment") or "").upper() == "NSE_EQ"
            and str(row.get("instrument_key") or "").startswith("NSE_EQ|")
        ]
        if fallback:
            self.last_error = None
            return fallback[0]
        self.last_error = f"{symbol}: no NSE_EQ instrument found"
        return None

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(symbol).upper(): data
            for symbol, data in payload.items()
            if isinstance(data, dict)
        }

    def _save_cache(self) -> None:
        with self.lock:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True), encoding="utf-8")
            except OSError as exc:
                self.last_error = f"Could not save Upstox instrument cache: {exc}"

    @staticmethod
    def _override_cache() -> dict[str, dict[str, Any]]:
        overrides = {}
        for part in UPSTOX_INSTRUMENT_OVERRIDES.replace(",", ";").split(";"):
            if "=" not in part:
                continue
            symbol, instrument_key = part.split("=", 1)
            clean_symbol = symbol.strip().upper()
            clean_key = instrument_key.strip()
            if clean_symbol and clean_key:
                overrides[clean_symbol] = {
                    "instrument_key": clean_key,
                    "trading_symbol": clean_symbol,
                    "name": "manual override",
                    "resolvedAt": _now_label(),
                }
        return overrides

    @staticmethod
    def _clean_symbols(symbols: list[str]) -> list[str]:
        return sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})


class UpstoxOptionInstrumentResolver:
    def __init__(self, token: str) -> None:
        self.token = token
        self.cache_path = UPSTOX_OPTION_INSTRUMENT_CACHE_PATH
        self.lock = threading.RLock()
        self.cache = self._load_cache()
        self.cache.update(self._override_cache())
        self.last_error: str | None = None

    def resolve(self, contract: dict[str, Any]) -> str | None:
        cache_key = self._cache_key(contract)
        symbol_key = str(contract.get("symbol") or "").strip().upper()
        with self.lock:
            cached = self.cache.get(cache_key) or self.cache.get(symbol_key)
            instrument_key = str(cached.get("instrument_key") or "") if isinstance(cached, dict) else ""
            if instrument_key:
                return instrument_key

        instrument = self._search_contract(contract)
        if not instrument:
            return None
        instrument_key = str(instrument.get("instrument_key") or instrument.get("instrumentKey") or "")
        if not instrument_key:
            self.last_error = f"{cache_key}: option instrument key missing"
            return None
        with self.lock:
            self.cache[cache_key] = {
                "instrument_key": instrument_key,
                "trading_symbol": instrument.get("trading_symbol") or instrument.get("tradingSymbol") or contract.get("symbol"),
                "expiry": contract.get("expiry"),
                "strike": contract.get("strike"),
                "optionType": contract.get("optionType"),
                "resolvedAt": _now_label(),
            }
        self._save_cache()
        self.last_error = None
        return instrument_key

    def _search_contract(self, contract: dict[str, Any]) -> dict[str, Any] | None:
        strike = str(contract.get("strike") or "").strip()
        option_type = str(contract.get("optionType") or "").strip().upper()
        underlying = str(contract.get("underlying") or contract.get("underlyingSymbol") or "NIFTY").strip().upper()
        query = f"{underlying} {strike} {option_type}".strip()
        params = parse.urlencode(
            {
                "query": query,
                "exchanges": "NSE",
                "segments": "FO",
                "instrument_types": option_type or "CE,PE",
                "expiry": str(contract.get("expiry") or "").strip(),
                "page_number": "1",
                "records": "30",
            }
        )
        req = request.Request(
            f"{UPSTOX_API_BASE_URL}/instruments/search?{params}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with request.urlopen(req, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - options page should show the lookup error, not crash polling
            self.last_error = f"{contract.get('symbol') or query}: {exc}"
            return None

        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            self.last_error = f"{contract.get('symbol') or query}: no option search rows"
            return None
        match = self._best_match(rows, contract)
        if match:
            self.last_error = None
            return match
        self.last_error = f"{contract.get('symbol') or query}: no matching {underlying} {option_type} option found"
        return None

    @staticmethod
    def _best_match(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any] | None:
        expiry = str(contract.get("expiry") or "")
        option_type = str(contract.get("optionType") or "").upper()
        strike = _to_float(contract.get("strike"))
        candidates = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_type = str(row.get("option_type") or row.get("optionType") or row.get("instrument_type") or "").upper()
            row_segment = str(row.get("segment") or "").upper()
            row_name = str(row.get("name") or row.get("trading_symbol") or row.get("tradingSymbol") or "").upper()
            underlying_aliases = UpstoxOptionInstrumentResolver._underlying_aliases(contract)
            row_expiry = str(row.get("expiry") or row.get("expiry_date") or row.get("expiryDate") or "")
            row_strike = _to_float(row.get("strike_price") or row.get("strikePrice") or row.get("strike"))
            row_underlying = str(row.get("underlying_symbol") or row.get("underlyingSymbol") or "").upper()
            if not any(alias and (alias in row_name or alias in row_underlying) for alias in underlying_aliases):
                continue
            if option_type and option_type not in row_type and not row_name.endswith(option_type):
                continue
            if strike is not None and row_strike is not None and abs(row_strike - strike) > 0.01:
                continue
            score = 0
            if row_segment in {"NSE_FO", "NFO"}:
                score += 2
            if str(row.get("instrument_key") or "").startswith(("NSE_FO|", "NFO|")):
                score += 2
            if expiry and expiry in row_expiry:
                score += 4
            candidates.append((score, row))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _underlying_aliases(contract: dict[str, Any]) -> set[str]:
        aliases = {
            str(contract.get("underlying") or ""),
            str(contract.get("underlyingSymbol") or ""),
            str(contract.get("underlyingName") or ""),
            str(contract.get("nseSymbol") or ""),
        }
        return {alias.strip().upper() for alias in aliases if alias and alias.strip()}

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): data for key, data in payload.items() if isinstance(data, dict)}

    def _save_cache(self) -> None:
        with self.lock:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True), encoding="utf-8")
            except OSError as exc:
                self.last_error = f"Could not save Upstox option instrument cache: {exc}"

    @staticmethod
    def _override_cache() -> dict[str, dict[str, Any]]:
        overrides = {}
        for part in UPSTOX_OPTION_INSTRUMENT_OVERRIDES.replace(",", ";").split(";"):
            if "=" not in part:
                continue
            key, instrument_key = part.split("=", 1)
            clean_key = key.strip().upper()
            clean_instrument_key = instrument_key.strip()
            if clean_key and clean_instrument_key:
                overrides[clean_key] = {
                    "instrument_key": clean_instrument_key,
                    "trading_symbol": clean_key,
                    "name": "manual option override",
                    "resolvedAt": _now_label(),
                }
        return overrides

    @staticmethod
    def _cache_key(contract: dict[str, Any]) -> str:
        return "|".join(
            [
                str(contract.get("underlying") or "NIFTY").upper(),
                str(contract.get("expiry") or ""),
                str(contract.get("strike") or ""),
                str(contract.get("optionType") or "").upper(),
            ]
        )


UPSTOX_INDEX_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "NIFTY FIN SERVICE": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTY MID SELECT": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTY MIDCAP SELECT": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "NIFTY NEXT 50": "NSE_INDEX|Nifty Next 50",
}


class UpstoxPriceStreamer:
    def __init__(self, on_prices, app_log: AppLog | None = None) -> None:
        self.on_prices = on_prices
        self.app_log = app_log
        self.enabled = UPSTOX_WEBSOCKET_ENABLED
        self.token = UPSTOX_ACCESS_TOKEN
        self.mode = UPSTOX_MARKET_FEED_MODE or "ltpc"
        self.resolver = UpstoxInstrumentResolver(self.token) if self.token else None
        self.option_resolver = UpstoxOptionInstrumentResolver(self.token) if self.token else None
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.streamer = None
        self.connected = False
        self.desired_keys: set[str] = set()
        self.subscribed_keys: set[str] = set()
        self.key_to_symbol: dict[str, str] = {}
        self.symbol_to_key: dict[str, str] = {}
        self.latest_ticks: dict[str, dict[str, Any]] = {}
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.last_subscription_at: str | None = None
        self.resolved_count = 0
        self.last_rest_quote_at: str | None = None
        self.last_rest_quote_count = 0
        self.stream_allowed = False
        self.reconnect_delay_seconds = max(1, UPSTOX_RECONNECT_SECONDS)
        self.option_chain_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.option_contract_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.option_expiry_cache: dict[str, tuple[float, list[str]]] = {}
        self.previous_m15_close_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def resolve_equity_key(self, symbol: str) -> str | None:
        clean_symbol = str(symbol or "").strip().upper()
        if not clean_symbol or not self.token or not self.resolver:
            return None
        return self.resolver.resolve([clean_symbol]).get(clean_symbol)

    def quote_stocks(self, stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not USE_UPSTOX_PRICE_DATA:
            return stocks
        if not self.token or not self.resolver:
            self._log("WARN", "Upstox price provider selected but token is missing")
            return [self._stale_upstox_stock(stock, "Upstox token missing") for stock in stocks]
        by_symbol = {
            str(stock.get("symbol") or "").strip().upper(): stock
            for stock in stocks
            if str(stock.get("symbol") or "").strip()
        }
        if not by_symbol:
            return stocks
        resolved = self.resolver.resolve(sorted(by_symbol))
        keys = [resolved[symbol] for symbol in sorted(by_symbol) if symbol in resolved]
        if not keys:
            reason = self.resolver.last_error or "no Upstox instrument keys resolved"
            self._log("WARN", "No Upstox instrument keys resolved", reason=reason)
            return [self._stale_upstox_stock(stock, reason) for stock in stocks]
        try:
            quote_rows = self._fetch_quote_rows(keys)
        except Exception as exc:  # noqa: BLE001 - no fake fallback in Upstox mode
            self._log("WARN", "Upstox REST quote fetch failed", error=str(exc), symbols=len(by_symbol))
            return [self._stale_upstox_stock(stock, str(exc)) for stock in stocks]

        quoted = []
        found = 0
        for stock in stocks:
            symbol = str(stock.get("symbol") or "").strip().upper()
            key = resolved.get(symbol)
            row = self._quote_row_for_symbol(quote_rows, symbol, key)
            price = _first_float(row.get("last_price"), row.get("ltp"), row.get("lastPrice")) if row else None
            if price is None:
                quoted.append(self._stale_upstox_stock(stock, "Upstox quote missing"))
                continue
            found += 1
            ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else {}
            quoted.append(
                {
                    **stock,
                    "symbol": symbol,
                    "current": price,
                    "last": price,
                    "vwap": _first_float(row.get("average_price"), stock.get("vwap")),
                    "open": _first_float(ohlc.get("open"), stock.get("open")),
                    "high": _first_float(ohlc.get("high"), stock.get("high")),
                    "low": _first_float(ohlc.get("low"), stock.get("low")),
                    "volume": _first_float(row.get("volume"), stock.get("volume")),
                    "upstoxInstrumentKey": key,
                    "upstoxLastTradeTime": row.get("last_trade_time"),
                    "dataSource": "Upstox market-quote/quotes",
                    "priceIsMock": False,
                }
            )
        with self.lock:
            self.last_rest_quote_at = _now_label()
            self.last_rest_quote_count = found
            self.last_error = None if found else self.last_error
        self._log("INFO", "Upstox REST prices loaded", requested=len(by_symbol), quoted=found)
        return quoted

    def quote_option(self, contract: dict[str, Any]) -> dict[str, Any]:
        if not USE_UPSTOX_PRICE_DATA:
            return {**contract, "quoteError": "Options paper engine requires PRICE_DATA_PROVIDER=upstox."}
        if not self.token or not self.option_resolver:
            return {**contract, "quoteError": "Upstox token missing for option quote."}

        chain_quote = self._quote_option_from_chain(contract)
        if chain_quote.get("ltp") is not None:
            return {**contract, **chain_quote}

        instrument_key = str(contract.get("instrumentKey") or "") or self.option_resolver.resolve(contract)
        if not instrument_key:
            return {
                **contract,
                "quoteError": chain_quote.get("quoteError") or self.option_resolver.last_error or "Upstox option instrument was not resolved.",
            }
        try:
            rows = self._fetch_quote_rows([instrument_key])
        except Exception as exc:  # noqa: BLE001
            self._log("WARN", "Upstox option quote fetch failed", error=str(exc), symbol=contract.get("symbol"))
            return {**contract, "instrumentKey": instrument_key, "quoteError": chain_quote.get("quoteError") or str(exc)}
        row = rows.get(instrument_key) or next((value for value in rows.values() if isinstance(value, dict)), {})
        quote = self._option_quote_from_row(row)
        if quote.get("ltp") is None:
            return {**contract, "instrumentKey": instrument_key, "quoteError": chain_quote.get("quoteError") or "Upstox option LTP missing."}
        return {
            **contract,
            **quote,
            "instrumentKey": instrument_key,
            "dataSource": "Upstox market-quote/quotes",
            "priceIsMock": False,
        }

    def previous_m15_close(self, symbol: str, instrument_key: str) -> dict[str, Any]:
        clean_key = str(instrument_key or "").strip()
        clean_symbol = str(symbol or "").strip().upper()
        if not clean_key:
            return {"symbol": clean_symbol, "close": None, "error": "Upstox equity instrument key missing."}
        now = time.time()
        with self.lock:
            cached = self.previous_m15_close_cache.get(clean_key)
            if cached and now - cached[0] <= 60 * 60:
                return cached[1]

        today = dt.date.today()
        from_date = today - dt.timedelta(days=10)
        to_date = today - dt.timedelta(days=1)
        encoded = parse.quote(clean_key, safe="")
        base_v3 = UPSTOX_API_BASE_URL.replace("/v2", "/v3")
        req = request.Request(
            f"{base_v3}/historical-candle/{encoded}/minutes/15/{to_date.isoformat()}/{from_date.isoformat()}",
            headers=self._headers(),
        )
        try:
            with self._urlopen_with_transient_retry(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            result = {"symbol": clean_symbol, "close": None, "error": str(exc)}
            with self.lock:
                self.previous_m15_close_cache[clean_key] = (now, result)
            return result

        candles = (payload.get("data") or {}).get("candles") if isinstance(payload, dict) else []
        parsed = []
        if isinstance(candles, list):
            for candle in candles:
                if not isinstance(candle, list) or len(candle) < 5:
                    continue
                timestamp = str(candle[0] or "")
                close = _to_float(candle[4])
                try:
                    candle_dt = dt.datetime.fromisoformat(timestamp)
                except ValueError:
                    continue
                if candle_dt.date() >= today or close is None:
                    continue
                parsed.append((candle_dt, close))
        if not parsed:
            result = {"symbol": clean_symbol, "close": None, "error": "No previous 15-minute candle found."}
        else:
            candle_dt, close = max(parsed, key=lambda item: item[0])
            result = {
                "symbol": clean_symbol,
                "close": close,
                "candleStart": candle_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "error": None,
            }
        with self.lock:
            self.previous_m15_close_cache[clean_key] = (now, result)
        return result

    def historical_candles(
        self,
        instrument_key: str,
        unit: str,
        interval: int,
        from_date: dt.date,
        to_date: dt.date,
    ) -> list[dict[str, Any]]:
        clean_key = str(instrument_key or "").strip()
        if not clean_key:
            return []
        if unit == "minutes" and (to_date - from_date).days > 25:
            rows = []
            chunk_start = from_date
            while chunk_start <= to_date:
                chunk_end = min(to_date, chunk_start + dt.timedelta(days=25))
                rows.extend(self.historical_candles(clean_key, unit, interval, chunk_start, chunk_end))
                chunk_start = chunk_end + dt.timedelta(days=1)
            deduped = {str(row.get("timestamp")): row for row in rows if row.get("timestamp")}
            return sorted(deduped.values(), key=lambda row: row["datetime"])
        encoded = parse.quote(clean_key, safe="")
        base_v3 = UPSTOX_API_BASE_URL.replace("/v2", "/v3")
        req = request.Request(
            f"{base_v3}/historical-candle/{encoded}/{unit}/{interval}/{to_date.isoformat()}/{from_date.isoformat()}",
            headers=self._headers(),
        )
        with self._urlopen_with_transient_retry(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candles = (payload.get("data") or {}).get("candles") if isinstance(payload, dict) else []
        if not isinstance(candles, list):
            return []
        parsed = [_candle_row(candle) for candle in candles]
        rows = [row for row in parsed if row]
        rows.sort(key=lambda row: row["datetime"])
        return rows

    def update_targets(self, stocks: list[dict[str, Any]]) -> None:
        if not self.enabled:
            return
        if not self.token or not self.resolver:
            with self.lock:
                self.last_error = "Upstox websocket enabled, but UPSTOX_ACCESS_TOKEN or UPSTOX_ANALYTICS_TOKEN is missing."
            self._log("WARN", "Upstox websocket enabled but token is missing")
            return
        by_symbol = {
            str(stock.get("symbol") or "").strip().upper(): stock
            for stock in stocks
            if str(stock.get("symbol") or "").strip()
        }
        if not by_symbol:
            self._set_desired_keys({}, {})
            self._sync_subscription()
            return
        resolved = self.resolver.resolve(sorted(by_symbol))
        key_to_symbol = {instrument_key: symbol for symbol, instrument_key in resolved.items()}
        self._set_desired_keys(resolved, key_to_symbol)
        if not self.stream_allowed:
            with self.lock:
                self.last_error = "Upstox websocket paused outside market hours."
            return
        self.start()
        self._sync_subscription()

    def set_stream_allowed(self, allowed: bool, reason: str = "") -> None:
        if not self.enabled:
            return
        with self.lock:
            changed = self.stream_allowed != allowed
            self.stream_allowed = allowed
        if allowed:
            if changed:
                self._log("INFO", "Upstox websocket enabled by market clock", reason=reason)
            if self.desired_keys:
                self.start()
                self._sync_subscription()
            return
        if changed:
            self._log("INFO", "Upstox websocket paused by market clock", reason=reason)
        self.stop(disconnect=True, clear_targets=False)

    def start(self) -> None:
        if not self.enabled or not self.stream_allowed:
            return
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="upstox-price-streamer", daemon=True)
            self.thread.start()

    def stop(self, disconnect: bool = True, clear_targets: bool = False) -> None:
        self.stop_event.set()
        with self.lock:
            stream = self.streamer
            if clear_targets:
                self.desired_keys = set()
                self.symbol_to_key = {}
                self.key_to_symbol = {}
        if disconnect and stream:
            self._call_streamer(stream, "disconnect")

    def status(self) -> dict[str, Any]:
        with self.lock:
            latest = sorted(self.latest_ticks.values(), key=lambda tick: str(tick.get("tickTime") or ""), reverse=True)[:8]
            return {
                "provider": PRICE_STREAM_PROVIDER,
                "enabled": self.enabled,
                "mode": self.mode,
                "connected": self.connected,
                "streamAllowed": self.stream_allowed,
                "reconnectDelaySeconds": self.reconnect_delay_seconds,
                "maxStreamSymbols": UPSTOX_MAX_STREAM_SYMBOLS,
                "subscribedSymbols": len(self.symbol_to_key),
                "subscribedKeys": len(self.subscribed_keys),
                "desiredKeys": len(self.desired_keys),
                "resolvedSymbols": self.resolved_count,
                "lastSubscriptionAt": self.last_subscription_at,
                "lastTickAt": self.last_tick_at,
                "lastRestQuoteAt": self.last_rest_quote_at,
                "lastRestQuoteCount": self.last_rest_quote_count,
                "lastError": self.last_error or (self.resolver.last_error if self.resolver else None),
                "latestTicks": latest,
                "cachePath": str(UPSTOX_INSTRUMENT_CACHE_PATH),
            }

    def _run(self) -> None:
        try:
            import upstox_client  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - optional dependency
            with self.lock:
                self.last_error = f"Install upstox-python-sdk to enable websocket streaming: {exc}"
            self._log("WARN", "Upstox SDK missing; websocket disabled", error=str(exc))
            return

        while not self.stop_event.is_set():
            with self.lock:
                allowed = self.stream_allowed
            if not allowed:
                if self.stop_event.wait(max(1, UPSTOX_RECONNECT_SECONDS)):
                    break
                continue
            try:
                configuration = upstox_client.Configuration()
                configuration.access_token = self.token
                stream = upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(configuration))
                stream.on("open", self._on_open)
                stream.on("message", self._on_message)
                stream.on("error", self._on_error)
                stream.on("close", self._on_close)
                self._call_streamer(stream, "auto_reconnect", False)
                with self.lock:
                    self.streamer = stream
                    self.connected = False
                    self.last_error = None
                self._log("INFO", "Opening Upstox websocket")
                stream.connect()
                if not self.stop_event.wait(self.reconnect_delay_seconds):
                    self.reconnect_delay_seconds = min(self.reconnect_delay_seconds * 2, 300)
            except Exception as exc:  # noqa: BLE001 - reconnect loop keeps polling fallback alive
                with self.lock:
                    self.connected = False
                    self.streamer = None
                    self.subscribed_keys = set()
                    self.last_error = f"Upstox websocket stopped: {exc}"
                self._log("WARN", "Upstox websocket stopped", error=str(exc))
                if self.stop_event.wait(self.reconnect_delay_seconds):
                    break
                self.reconnect_delay_seconds = min(self.reconnect_delay_seconds * 2, 300)

    def _on_open(self, *args) -> None:
        with self.lock:
            self.connected = True
            self.last_error = None
            self.reconnect_delay_seconds = max(1, UPSTOX_RECONNECT_SECONDS)
        self._log("INFO", "Upstox websocket connected")
        self._sync_subscription()

    def _on_close(self, *args) -> None:
        with self.lock:
            self.connected = False
            self.subscribed_keys = set()
        self._log("WARN", "Upstox websocket closed")

    def _on_error(self, *args) -> None:
        message = args[-1] if args else "unknown websocket error"
        with self.lock:
            self.last_error = str(message)
        self._log("WARN", "Upstox websocket error", error=str(message))

    def _on_message(self, *args) -> None:
        message = args[-1] if args else None
        ticks = self._ticks_from_message(message)
        if not ticks:
            return
        with self.lock:
            for tick in ticks:
                self.latest_ticks[tick["symbol"]] = tick
            self.last_tick_at = _now_label()
        self._log("INFO", "Upstox websocket tick batch", ticks=len(ticks))
        self.on_prices(ticks)

    def _set_desired_keys(self, symbol_to_key: dict[str, str], key_to_symbol: dict[str, str]) -> None:
        with self.lock:
            self.symbol_to_key = dict(symbol_to_key)
            self.key_to_symbol = dict(key_to_symbol)
            self.desired_keys = set(key_to_symbol)
            self.resolved_count = len(symbol_to_key)

    def _sync_subscription(self) -> None:
        with self.lock:
            stream = self.streamer
            if not self.connected or not stream:
                return
            desired = set(self.desired_keys)
            subscribed = set(self.subscribed_keys)
        to_subscribe = sorted(desired - subscribed)
        to_unsubscribe = sorted(subscribed - desired)
        try:
            if to_subscribe:
                self._call_streamer(stream, "subscribe", to_subscribe, self.mode)
            if to_unsubscribe:
                self._call_streamer(stream, "unsubscribe", to_unsubscribe)
            if to_subscribe or to_unsubscribe:
                with self.lock:
                    self.subscribed_keys = desired
                    self.last_subscription_at = _now_label()
                    self.last_error = None
                self._log(
                    "INFO",
                    "Upstox websocket subscription updated",
                    subscribed=len(to_subscribe),
                    unsubscribed=len(to_unsubscribe),
                    total=len(desired),
                )
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.last_error = f"Upstox subscription update failed: {exc}"
            self._log("WARN", "Upstox subscription update failed", error=str(exc))

    @staticmethod
    def _call_streamer(stream, method_name: str, *args):
        method = getattr(stream, method_name, None)
        if method is None and "_" in method_name:
            parts = method_name.split("_")
            method = getattr(stream, parts[0] + "".join(part.title() for part in parts[1:]), None)
        if method is None:
            return None
        return method(*args)

    def _ticks_from_message(self, message: Any) -> list[dict[str, Any]]:
        if isinstance(message, bytes):
            with self.lock:
                self.last_error = "Upstox SDK returned raw protobuf bytes; decoded messages are required."
            return []
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except json.JSONDecodeError:
                return []
        if not isinstance(message, dict):
            return []
        feeds = message.get("feeds")
        if not isinstance(feeds, dict):
            return []
        ticks = []
        with self.lock:
            key_to_symbol = dict(self.key_to_symbol)
        for instrument_key, feed in feeds.items():
            key = str(instrument_key or "")
            symbol = key_to_symbol.get(key)
            if not symbol:
                continue
            price = self._extract_ltp(feed)
            if price is None:
                continue
            ticks.append(
                {
                    "symbol": symbol,
                    "current": price,
                    "tickTime": _now_label(),
                    "instrumentKey": key,
                    "dataSource": "Upstox MarketDataStreamerV3",
                    "priceIsMock": False,
                }
            )
        return ticks

    def _extract_ltp(self, value: Any) -> float | None:
        if not isinstance(value, dict):
            return None
        ltpc = value.get("ltpc")
        if isinstance(ltpc, dict):
            price = _first_float(ltpc.get("ltp"), ltpc.get("last_price"), ltpc.get("lastPrice"))
            if price is not None:
                return price
        for child in value.values():
            if isinstance(child, dict):
                price = self._extract_ltp(child)
                if price is not None:
                    return price
        return None

    def _fetch_quote_rows(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        params = parse.urlencode({"instrument_key": ",".join(keys)})
        req = request.Request(
            f"{UPSTOX_API_BASE_URL}/market-quote/quotes?{params}",
            headers=self._headers(),
        )
        with self._urlopen_with_transient_retry(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else {}
        return data if isinstance(data, dict) else {}

    def _quote_option_from_chain(self, contract: dict[str, Any]) -> dict[str, Any]:
        index_key = self._option_chain_index_key(contract)
        preferred_expiry = str(contract.get("expiry") or "").strip()
        if not index_key:
            return {"quoteError": "Upstox option-chain lookup needs index key and expiry."}
        expiries = [preferred_expiry] if preferred_expiry else []
        resolved_expiry = self._select_option_chain_expiry(index_key, preferred_expiry)
        if resolved_expiry and resolved_expiry not in expiries:
            expiries.append(resolved_expiry)
        if not expiries:
            return {"quoteError": f"Upstox option-chain expiry not resolved for {contract.get('symbol') or '-'}."}

        errors = []
        for expiry in expiries:
            rows, error = self._fetch_option_chain_rows(index_key, expiry)
            if error:
                errors.append(error)
                continue
            quote = self._quote_from_chain_rows(index_key, contract, rows)
            if quote.get("ltp") is not None:
                return quote
            errors.append(str(quote.get("quoteError") or f"strike not found for expiry {expiry}"))
        return {"quoteError": "; ".join(errors) if errors else f"Upstox option-chain quote missing for {contract.get('symbol') or '-'}."}

    def _fetch_option_chain_rows(self, index_key: str, expiry: str) -> tuple[list[dict[str, Any]], str | None]:
        cache_key = f"{index_key}|{expiry}"
        now = time.time()
        with self.lock:
            cached = self.option_chain_cache.get(cache_key)
            if cached and now - cached[0] <= max(2, POLL_SECONDS):
                return cached[1], None

        params = parse.urlencode({"instrument_key": index_key, "expiry_date": expiry})
        req = request.Request(
            f"{UPSTOX_API_BASE_URL}/option/chain?{params}",
            headers=self._headers(),
        )
        try:
            with self._urlopen_with_transient_retry(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return [], f"Upstox option-chain lookup failed for {expiry}: {exc}"

        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return [], f"Upstox option-chain returned no rows for {expiry}."
        with self.lock:
            self.option_chain_cache[cache_key] = (now, rows)
        return rows, None

    def _quote_from_chain_rows(self, index_key: str, contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        strike = _to_float(contract.get("strike"))
        spot = _to_float(contract.get("spot") or contract.get("underlyingSpot") or contract.get("last") or contract.get("ltp"))
        option_type = str(contract.get("optionType") or "").strip().upper()
        option_key = "call_options" if option_type == "CE" else "put_options"
        candidate_rows = [row for row in rows if isinstance(row, dict)]
        if strike is None and spot is not None:
            candidate_rows.sort(
                key=lambda row: abs((_to_float(row.get("strike_price") or row.get("strikePrice") or row.get("strike")) or spot) - spot)
            )
        for row in candidate_rows:
            row_strike = _to_float(row.get("strike_price") or row.get("strikePrice") or row.get("strike"))
            if strike is not None and row_strike is not None and abs(row_strike - strike) > 0.01:
                continue
            option = row.get(option_key) if isinstance(row.get(option_key), dict) else {}
            market = option.get("market_data") if isinstance(option.get("market_data"), dict) else {}
            greeks = option.get("option_greeks") if isinstance(option.get("option_greeks"), dict) else {}
            quote = self._option_quote_from_chain_market(market, greeks)
            if quote.get("ltp") is None:
                return {"quoteError": f"Upstox option-chain LTP missing for {contract.get('symbol') or '-'}."}
            expiry = str(row.get("expiry") or contract.get("expiry") or "")
            meta = self._option_contract_meta(index_key, expiry, row_strike, option_type)
            strike_value = int(row_strike) if row_strike is not None and float(row_strike).is_integer() else row_strike
            return {
                **quote,
                "symbol": meta.get("tradingSymbol") or contract.get("symbol"),
                "expiry": expiry,
                "strike": strike_value if strike_value is not None else contract.get("strike"),
                "lotSize": int(_to_float(meta.get("lotSize")) or _to_float(contract.get("lotSize")) or 0),
                "instrumentKey": option.get("instrument_key") or option.get("instrumentKey") or meta.get("instrumentKey"),
                "dataSource": "Upstox option/chain",
                "priceIsMock": False,
            }
        return {"quoteError": f"Upstox option-chain strike not found for {contract.get('symbol') or '-' }."}

    def _option_contract_meta(self, index_key: str, expiry: str, strike: float | None, option_type: str) -> dict[str, Any]:
        if not index_key or not expiry:
            return {}
        rows = self._fetch_option_contract_rows(index_key, expiry)
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_type = str(row.get("instrument_type") or row.get("optionType") or "").strip().upper()
            row_strike = _to_float(row.get("strike_price") or row.get("strikePrice") or row.get("strike"))
            if option_type and row_type != option_type:
                continue
            if strike is not None and row_strike is not None and abs(row_strike - strike) > 0.01:
                continue
            return {
                "instrumentKey": row.get("instrument_key") or row.get("instrumentKey"),
                "tradingSymbol": row.get("trading_symbol") or row.get("tradingSymbol"),
                "lotSize": row.get("lot_size") or row.get("lotSize") or row.get("minimum_lot"),
            }
        return {}

    def _fetch_option_contract_rows(self, index_key: str, expiry: str = "") -> list[dict[str, Any]]:
        cache_key = f"{index_key}|{expiry}"
        now = time.time()
        with self.lock:
            cached = self.option_contract_cache.get(cache_key)
            if cached and now - cached[0] <= 300:
                return cached[1]

        params = {"instrument_key": index_key}
        if expiry:
            params["expiry_date"] = expiry
        req = request.Request(
            f"{UPSTOX_API_BASE_URL}/option/contract?{parse.urlencode(params)}",
            headers=self._headers(),
        )
        try:
            with self._urlopen_with_transient_retry(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return []
        rows = payload.get("data") if isinstance(payload, dict) else []
        result = rows if isinstance(rows, list) else []
        with self.lock:
            self.option_contract_cache[cache_key] = (now, result)
        return result

    def _select_option_chain_expiry(self, index_key: str, preferred_expiry: str) -> str | None:
        expiries = self._option_chain_expiries(index_key)
        if preferred_expiry and preferred_expiry in expiries:
            return preferred_expiry
        parsed = []
        for expiry in expiries:
            try:
                parsed.append((dt.datetime.strptime(expiry, "%Y-%m-%d").date(), expiry))
            except ValueError:
                continue
        today = dt.date.today()
        future = sorted((item for item in parsed if item[0] >= today), key=lambda item: item[0])
        if future:
            return future[0][1]
        if parsed:
            return sorted(parsed, key=lambda item: item[0])[-1][1]
        return None

    def _option_chain_expiries(self, index_key: str) -> list[str]:
        now = time.time()
        with self.lock:
            cached = self.option_expiry_cache.get(index_key)
            if cached and now - cached[0] <= 300:
                return cached[1]

        rows = self._fetch_option_contract_rows(index_key)
        expiries = sorted(
            {
                str(row.get("expiry") or "").strip()
                for row in rows
                if isinstance(row, dict) and str(row.get("expiry") or "").strip()
            }
        )
        with self.lock:
            self.option_expiry_cache[index_key] = (now, expiries)
        return expiries

    @staticmethod
    def _option_chain_index_key(contract: dict[str, Any]) -> str | None:
        underlying_key = str(contract.get("underlyingInstrumentKey") or "").strip()
        if underlying_key:
            return underlying_key
        aliases = [
            str(contract.get("underlying") or ""),
            str(contract.get("underlyingSymbol") or ""),
            str(contract.get("underlyingName") or ""),
            str(contract.get("nseSymbol") or ""),
        ]
        for alias in aliases:
            key = UPSTOX_INDEX_INSTRUMENT_KEYS.get(alias.strip().upper())
            if key:
                return key
        return None

    @staticmethod
    def _option_quote_from_chain_market(market: dict[str, Any], greeks: dict[str, Any]) -> dict[str, Any]:
        bid = _first_float(market.get("bid_price"), market.get("bidPrice"), market.get("bid"))
        ask = _first_float(market.get("ask_price"), market.get("askPrice"), market.get("ask"))
        raw_ltp = _first_float(market.get("ltp"), market.get("last_price"), market.get("lastPrice"))
        ltp = raw_ltp if raw_ltp and raw_ltp > 0 else ((bid + ask) / 2 if bid and ask else raw_ltp)
        previous_close = _first_float(market.get("close_price"), market.get("prev_close"), market.get("previous_close"), market.get("previousClose"))
        change = _first_float(market.get("net_change"), market.get("netChange"), market.get("change"))
        if change is None and ltp is not None and previous_close:
            change = ltp - previous_close
        percent_change = _first_float(market.get("pchange"), market.get("pChange"), market.get("percent_change"), market.get("percentChange"))
        if percent_change is None and change is not None and previous_close:
            percent_change = (change / previous_close) * 100
        spread_pct = ((ask - bid) / ltp) * 100 if bid and ask and ltp else None
        oi = _first_float(market.get("oi"), market.get("open_interest"), market.get("openInterest"))
        prev_oi = _first_float(market.get("prev_oi"), market.get("prevOi"), market.get("previous_oi"), market.get("previousOi"))
        oi_change = _first_float(
            market.get("oi_change"),
            market.get("oiChange"),
            market.get("open_interest_change"),
            market.get("openInterestChange"),
        )
        if oi_change is None and oi is not None and prev_oi is not None:
            oi_change = oi - prev_oi
        oi_change_pct = _first_float(
            market.get("oi_change_pct"),
            market.get("oiChangePct"),
            market.get("open_interest_change_pct"),
            market.get("openInterestChangePct"),
        )
        if oi_change_pct is None and oi_change is not None and prev_oi:
            oi_change_pct = (oi_change / prev_oi) * 100
        return {
            "ltp": ltp,
            "change": change,
            "percentChange": percent_change,
            "previousClose": previous_close,
            "bid": _round_price(bid),
            "ask": _round_price(ask),
            "spreadPct": round(spread_pct, 2) if spread_pct is not None else None,
            "volume": _first_float(market.get("volume"), market.get("volume_traded"), market.get("total_volume")),
            "oi": oi,
            "prevOi": prev_oi,
            "oiChange": oi_change,
            "oiChangePct": oi_change_pct,
            "iv": _first_float(greeks.get("iv"), greeks.get("implied_volatility"), greeks.get("impliedVolatility")),
        }

    @staticmethod
    def _urlopen_with_transient_retry(req: request.Request, timeout: int):
        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                return request.urlopen(req, timeout=timeout)
            except OSError as exc:
                last_exc = exc
                if not _is_transient_socket_error(exc) or attempt >= 2:
                    raise
                time.sleep(0.4 * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError("Upstox request failed before it was attempted")

    def _headers(self) -> dict[str, str]:
        # Include the configured access token in the Authorization header so
        # Upstox REST endpoints can be queried.
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        }

    @staticmethod
    def _quote_row_for_symbol(rows: dict[str, dict[str, Any]], symbol: str, key: str | None) -> dict[str, Any]:
        if not rows:
            return {}
        row = rows.get(f"NSE_EQ:{symbol}") or rows.get(key or "")
        if isinstance(row, dict):
            return row
        return next(
            (
                value for value in rows.values()
                if isinstance(value, dict)
                and (
                    value.get("instrument_token") == key
                    or value.get("instrument_key") == key
                    or str(value.get("symbol") or "").upper() == symbol
                )
            ),
            {},
        )

    @staticmethod
    def _stale_upstox_stock(stock: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            **stock,
            "current": None,
            "quoteError": reason,
            "dataSource": "Upstox price unavailable",
            "priceIsMock": False,
        }

    @staticmethod
    def _option_quote_from_row(row: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        depth = row.get("depth") if isinstance(row.get("depth"), dict) else {}
        buy_depth = depth.get("buy") if isinstance(depth.get("buy"), list) else []
        sell_depth = depth.get("sell") if isinstance(depth.get("sell"), list) else []
        best_bid = buy_depth[0] if buy_depth and isinstance(buy_depth[0], dict) else {}
        best_ask = sell_depth[0] if sell_depth and isinstance(sell_depth[0], dict) else {}
        bid = _first_float(row.get("bid_price"), row.get("bidPrice"), best_bid.get("price"))
        ask = _first_float(row.get("ask_price"), row.get("askPrice"), best_ask.get("price"))
        ltp = _first_float(row.get("last_price"), row.get("ltp"), row.get("lastPrice"))
        previous_close = _first_float(row.get("prev_close"), row.get("previous_close"), row.get("previousClose"), row.get("close"))
        change = _first_float(row.get("net_change"), row.get("netChange"), row.get("change"))
        if change is None and ltp is not None and previous_close:
            change = ltp - previous_close
        percent_change = _first_float(row.get("pchange"), row.get("pChange"), row.get("percent_change"), row.get("percentChange"))
        if percent_change is None and change is not None and previous_close:
            percent_change = (change / previous_close) * 100
        spread_pct = ((ask - bid) / ltp) * 100 if bid and ask and ltp else None
        oi = _first_float(row.get("oi"), row.get("open_interest"), row.get("openInterest"))
        return {
            "ltp": ltp,
            "change": change,
            "percentChange": percent_change,
            "previousClose": previous_close,
            "bid": _round_price(bid),
            "ask": _round_price(ask),
            "spreadPct": round(spread_pct, 2) if spread_pct is not None else None,
            "volume": _first_float(row.get("volume"), row.get("last_traded_quantity"), row.get("lastTradedQuantity")),
            "oi": oi,
            "iv": _first_float(row.get("iv"), row.get("implied_volatility"), row.get("impliedVolatility")),
        }

    def _log(self, level: str, message: str, **fields: Any) -> None:
        if not self.app_log:
            return
        if level == "WARN":
            self.app_log.warn(message, **fields)
        else:
            self.app_log.info(message, **fields)


@dataclass
class FeedState:
    running: bool = False
    started_at: str | None = None
    last_fetch_started_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    source_url: str = NSE_HEATMAP_URL
    api_url: str = NSE_ALL_INDICES_API
    stock_api_url: str = NSE_STOCK_INDICES_API
    market_status_api_url: str = NSE_MARKET_STATUS_API
    holiday_api_url: str = NSE_HOLIDAY_API
    poll_seconds: int = POLL_SECONDS
    fetch_count: int = 0
    sector_rows: list[dict[str, Any]] = field(default_factory=list)
    sector_stock_groups: list[dict[str, Any]] = field(default_factory=list)
    paper_trading: dict[str, Any] = field(default_factory=dict)
    options_paper_trading: dict[str, Any] = field(default_factory=dict)
    price_streaming: dict[str, Any] = field(default_factory=dict)
    max_gainer: dict[str, Any] | None = None
    max_loser: dict[str, Any] | None = None
    top_movers: dict[str, Any] = field(default_factory=dict)
    nifty_spot: dict[str, Any] | None = None
    index_spots: dict[str, dict[str, Any]] = field(default_factory=dict)
    market_status: dict[str, Any] = field(default_factory=dict)
    market_clock: dict[str, Any] = field(default_factory=dict)
    data_provenance: dict[str, Any] = field(default_factory=dict)
    snapshot_time: str | None = None
    raw_count: int = 0


class NSEStreamer:
    def __init__(self) -> None:
        self.app_log = AppLog()
        self.client = NSEClient()
        self.paper_engine = PaperTradingEngine()
        self.options_engine = NiftyOptionsPaperEngine()
        self.price_streamer = UpstoxPriceStreamer(self._handle_stream_prices, self.app_log)
        self.state = FeedState()
        self.lock = threading.RLock()
        self.paper_lock = threading.RLock()
        self.holiday_cache: dict[int, dict[str, str]] = {}
        self.holiday_loaded_at = 0.0
        self.holiday_error: str | None = None
        self.market_status_cache: dict[str, Any] = {}
        self.market_status_loaded_at = 0.0
        self.market_status_error: str | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.app_log.info("Dashboard initialized", priceDataProvider=PRICE_DATA_PROVIDER)

    def start(self) -> bool:
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.state.running = True
                return False
            self.stop_event.clear()
            self.state.running = True
            self.state.started_at = _now_label()
            self.thread = threading.Thread(target=self._run, name="nse-streamer", daemon=True)
            self.thread.start()
            self.app_log.info("NSE streamer started", priceDataProvider=PRICE_DATA_PROVIDER)
            return True

    def stop(self) -> bool:
        with self.lock:
            was_running = self.state.running
            self.state.running = False
            self.stop_event.set()
        self.price_streamer.stop()
        self.app_log.info("Streamer stopped")
        return was_running

    def refresh_once(self) -> dict[str, Any]:
        self._fetch_and_store(force=True)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            clock = self.state.market_clock or {}
            data = {
                **self.state.__dict__,
                "streaming_label": "On" if self.state.running and clock.get("shouldStream", True) else "Scheduled" if self.state.running else "Off",
                "sector_selection_rule": self._sector_selection_rule(),
                "price_streaming": self.price_streamer.status(),
                "price_data_provider": PRICE_DATA_PROVIDER,
                "logs": self.app_log.latest(80),
            }
        return data

    def logs(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.app_log.latest(limit)

    def close_paper_trade(self, trade_id: str) -> dict[str, Any]:
        with self.paper_lock:
            result = self.paper_engine.close_trade_by_id(trade_id)
            paper_trading = self.paper_engine.snapshot()
        with self.lock:
            self.state.paper_trading = paper_trading
            status = self.status()
        self._refresh_price_stream_targets()
        return {**result, "status": status}

    def close_options_trade(self, trade_id: str) -> dict[str, Any]:
        with self.paper_lock:
            result = self.options_engine.close_trade_by_id(trade_id, self.price_streamer.quote_option)
            options_paper = self.options_engine.snapshot()
        with self.lock:
            self.state.options_paper_trading = options_paper
            status = self.status()
        return {**result, "status": status}

    def paper_report(self, date_key: str | None = None) -> dict[str, Any]:
        with self.paper_lock:
            return self.paper_engine.daily_report(date_key)

    def _handle_stream_prices(self, ticks: list[dict[str, Any]]) -> None:
        if not ticks:
            return
        with self.paper_lock:
            paper_trading = self.paper_engine.mark_stream_prices(ticks)
            options_paper = self.options_engine.snapshot()
        with self.lock:
            self._overlay_stream_prices_locked(ticks)
            self.state.paper_trading = paper_trading
            self.state.options_paper_trading = options_paper
            self.state.price_streaming = self.price_streamer.status()
        self._refresh_price_stream_targets()

    def _refresh_price_stream_targets(self) -> None:
        if not UPSTOX_WEBSOCKET_ENABLED:
            return
        with self.paper_lock:
            active_targets = self.paper_engine.active_mark_targets()
            closing_volume_targets = self.paper_engine.closing_volume_mark_targets()
        with self.lock:
            stock_groups = list(self.state.sector_stock_groups)
        self.price_streamer.update_targets(self._stream_subscription_targets(stock_groups, {**active_targets, **closing_volume_targets}))

    def _overlay_stream_prices_locked(self, ticks: list[dict[str, Any]]) -> None:
        by_symbol = {str(tick.get("symbol") or "").upper(): tick for tick in ticks}
        if not by_symbol:
            return
        for group in self.state.sector_stock_groups:
            for stock in group.get("stocks") or []:
                symbol = str(stock.get("symbol") or "").upper()
                tick = by_symbol.get(symbol)
                if not tick:
                    continue
                price = _to_float(tick.get("current"))
                if price is None:
                    continue
                stock["current"] = _round_price(price)
                stock["websocketLastTick"] = tick.get("tickTime")
                stock["websocketInstrumentKey"] = tick.get("instrumentKey")
                stock["dataSource"] = tick.get("dataSource") or stock.get("dataSource")

    @staticmethod
    def _price_stream_targets(
        stock_groups: list[dict[str, Any]],
        active_targets: dict[str, str],
    ) -> list[dict[str, Any]]:
        targets: dict[str, dict[str, Any]] = {}
        for group in stock_groups:
            for stock in group.get("stocks") or []:
                symbol = str(stock.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                targets[symbol] = {
                    **stock,
                    "symbol": symbol,
                    "sector": group.get("sector") or stock.get("sector"),
                    "direction": group.get("direction") or stock.get("direction"),
                }
        for symbol, sector in active_targets.items():
            clean_symbol = str(symbol or "").strip().upper()
            if not clean_symbol:
                continue
            targets.setdefault(clean_symbol, {"symbol": clean_symbol, "sector": sector, "direction": "active"})
        return list(targets.values())

    @staticmethod
    def _apply_price_targets_to_groups(
        stock_groups: list[dict[str, Any]],
        price_targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_symbol = {
            str(stock.get("symbol") or "").strip().upper(): stock
            for stock in price_targets
            if str(stock.get("symbol") or "").strip()
        }
        groups = []
        for group in stock_groups:
            stocks = []
            for stock in group.get("stocks") or []:
                symbol = str(stock.get("symbol") or "").strip().upper()
                stocks.append({**stock, **by_symbol.get(symbol, {})})
            groups.append({**group, "stocks": stocks})
        return groups

    @staticmethod
    def _stream_subscription_targets(
        stock_groups: list[dict[str, Any]],
        active_targets: dict[str, str],
    ) -> list[dict[str, Any]]:
        selected_targets = NSEStreamer._price_stream_targets(stock_groups, {})
        selected_by_symbol = {
            str(stock.get("symbol") or "").strip().upper(): stock
            for stock in selected_targets
            if str(stock.get("symbol") or "").strip()
        }
        ordered = []
        seen = set()
        for symbol, sector in active_targets.items():
            clean_symbol = str(symbol or "").strip().upper()
            if not clean_symbol:
                continue
            seen.add(clean_symbol)
            ordered.append(
                {
                    **selected_by_symbol.get(clean_symbol, {}),
                    "symbol": clean_symbol,
                    "sector": sector or selected_by_symbol.get(clean_symbol, {}).get("sector"),
                    "direction": "active",
                    "streamPriority": "active_trade",
                }
            )
        for stock in selected_targets:
            symbol = str(stock.get("symbol") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            if len(ordered) >= max(1, UPSTOX_MAX_STREAM_SYMBOLS):
                break
            seen.add(symbol)
            ordered.append({**stock, "symbol": symbol, "streamPriority": "selected_sector"})
        return ordered

    def _run(self) -> None:
        while not self.stop_event.is_set():
            clock = self._market_clock()
            self._set_market_clock(clock)
            if clock["shouldStream"]:
                self._fetch_and_store(market_clock=clock)
                wait_seconds = POLL_SECONDS
            else:
                wait_seconds = max(POLL_SECONDS, min(IDLE_POLL_SECONDS, int(clock.get("secondsToNextOpen") or IDLE_POLL_SECONDS)))
            self.stop_event.wait(wait_seconds)

    def _fetch_and_store(self, market_clock: dict[str, Any] | None = None, force: bool = False) -> None:
        market_clock = market_clock or self._market_clock(force=force)
        with self.lock:
            self.state.last_fetch_started_at = _now_label()
            self.state.market_clock = market_clock
        try:
            payload = self.client.fetch_all_indices()
            parsed = self._parse_payload(payload)
            top_movers = self._fetch_top_movers()
            stock_groups = self._fetch_sector_stock_groups(parsed["sector_rows"])
            with self.paper_lock:
                active_targets = self.paper_engine.active_mark_targets()
                closing_volume_targets = self.paper_engine.closing_volume_mark_targets()
            mark_targets = {**active_targets, **closing_volume_targets}
            websocket_allowed = bool(market_clock.get("shouldStream"))
            self.price_streamer.set_stream_allowed(websocket_allowed, str(market_clock.get("reason") or "market clock"))
            if USE_UPSTOX_PRICE_DATA:
                price_targets = self._price_stream_targets(stock_groups, mark_targets)
                upstox_marks = self.price_streamer.quote_stocks(price_targets)
                stock_groups = self._apply_price_targets_to_groups(stock_groups, upstox_marks)
                active_quote_stocks = [
                    stock for stock in upstox_marks
                    if str(stock.get("symbol") or "").strip().upper() in {symbol.upper() for symbol in mark_targets}
                ]
            else:
                active_quote_stocks = self._fetch_active_trade_marks(mark_targets, stock_groups)
            if websocket_allowed:
                self.price_streamer.update_targets(self._stream_subscription_targets(stock_groups, mark_targets))
            else:
                self.price_streamer.update_targets([])
            with self.paper_lock:
                paper_trading = self.paper_engine.update(
                    stock_groups,
                    market_open=bool(market_clock.get("shouldStream")),
                    mark_stocks=active_quote_stocks,
                )
                options_paper = self.options_engine.update(
                    parsed["sector_rows"],
                    parsed["index_spots"],
                    self.price_streamer.quote_option,
                    market_open=bool(market_clock.get("shouldStream")),
                    top_movers=top_movers,
                    equity_key_provider=self.price_streamer.resolve_equity_key,
                    previous_m15_close_provider=self.price_streamer.previous_m15_close,
                )
            with self.lock:
                self.state.last_error = None
                self.state.last_success_at = _now_label()
                self.state.fetch_count += 1
                self.state.sector_rows = parsed["sector_rows"]
                self.state.sector_stock_groups = stock_groups
                self.state.paper_trading = paper_trading
                self.state.options_paper_trading = options_paper
                self.state.max_gainer = parsed["max_gainer"]
                self.state.max_loser = parsed["max_loser"]
                self.state.top_movers = top_movers
                self.state.nifty_spot = parsed["nifty_spot"]
                self.state.index_spots = parsed["index_spots"]
                self.state.market_status = self.market_status_cache or parsed["market_status"]
                self.state.market_clock = market_clock
                self.state.data_provenance = self._data_provenance()
                self.state.price_streaming = self.price_streamer.status()
                self.state.snapshot_time = parsed["snapshot_time"]
                self.state.raw_count = parsed["raw_count"]
            self.app_log.info(
                "Market refresh stored",
                sectors=len(parsed["sector_rows"]),
                selectedGroups=len(stock_groups),
                activeTrades=len(active_targets),
                priceDataProvider=PRICE_DATA_PROVIDER,
            )
        except Exception as exc:  # noqa: BLE001 - surface the feed problem to the UI
            with self.lock:
                self.state.last_error = str(exc)
                self.state.market_clock = market_clock
            self.app_log.warn("Market refresh failed", error=str(exc))

    def _set_market_clock(self, clock: dict[str, Any]) -> None:
        self._maybe_refresh_closing_volume_shortlist(clock)
        with self.paper_lock:
            paper_trading = self.paper_engine.snapshot()
            options_paper = self.options_engine.snapshot()
        with self.lock:
            self.state.market_clock = clock
            self.state.market_status = self.market_status_cache
            self.state.data_provenance = self._data_provenance()
            self.state.paper_trading = paper_trading
            self.state.options_paper_trading = options_paper
            self.state.price_streaming = self.price_streamer.status()

    def _maybe_refresh_closing_volume_shortlist(self, clock: dict[str, Any]) -> None:
        if not USE_UPSTOX_PRICE_DATA:
            return
        now = dt.datetime.now()
        if bool(clock.get("shouldStream")) or now.time() <= MARKET_CLOSE_TIME:
            return
        session_date = self._last_trading_date(now.date())
        target_date = self._next_trading_date(session_date + dt.timedelta(days=1))
        with self.paper_lock:
            current_source = self.paper_engine.closing_volume_shortlist.get("sourceDate")
            current_universe = self.paper_engine.closing_volume_shortlist.get("universe")
            current_spike = _to_float(self.paper_engine.closing_volume_shortlist.get("spikeMultiple"))
        if (
            current_source == _date_key(session_date)
            and current_universe == CLOSING_VOLUME_UNIVERSE
            and current_spike == CLOSING_VOLUME_SPIKE_MULTIPLE
        ):
            return
        try:
            shortlist = self.generate_closing_volume_shortlist(session_date, target_date)
            with self.paper_lock:
                self.paper_engine.set_closing_volume_shortlist(shortlist)
            self.app_log.info(
                "Closing volume shortlist generated",
                sourceDate=shortlist.get("sourceDate"),
                targetDate=shortlist.get("targetDate"),
                selected=len(shortlist.get("selected") or []),
            )
        except Exception as exc:  # noqa: BLE001 - shortlist failure must not stop dashboard clock/status
            self.app_log.warn("Closing volume shortlist generation failed", error=str(exc))

    def generate_closing_volume_shortlist(
        self,
        session_date: dt.date | None = None,
        target_date: dt.date | None = None,
    ) -> dict[str, Any]:
        session_date = session_date or self._last_trading_date(dt.date.today())
        target_date = target_date or self._next_trading_date(session_date + dt.timedelta(days=1))
        payload = self.client.fetch_sector_stocks(CLOSING_VOLUME_UNIVERSE)
        universe = self._parse_sector_stocks(payload, CLOSING_VOLUME_UNIVERSE, "closing")
        symbols = [str(stock.get("symbol") or "").strip().upper() for stock in universe if stock.get("symbol")]
        resolved = self.price_streamer.resolver.resolve(symbols) if self.price_streamer.resolver else {}
        selected = []
        errors = []
        for symbol in symbols:
            instrument_key = resolved.get(symbol)
            if not instrument_key:
                errors.append({"symbol": symbol, "error": "Upstox instrument key missing"})
                continue
            try:
                candidate = self._closing_volume_candidate(symbol, instrument_key, session_date, target_date)
            except Exception as exc:  # noqa: BLE001 - one symbol should not block the full shortlist
                errors.append({"symbol": symbol, "error": str(exc)})
                continue
            if candidate:
                selected.append(candidate)

        bullish = sorted([row for row in selected if row.get("side") == "BUY"], key=lambda row: _to_float(row.get("score")) or 0, reverse=True)
        bearish = sorted([row for row in selected if row.get("side") == "SHORT"], key=lambda row: _to_float(row.get("score")) or 0, reverse=True)
        final_rows = bullish[:CLOSING_VOLUME_TOP_COUNT] + bearish[:CLOSING_VOLUME_TOP_COUNT]
        final_rows.sort(key=lambda row: _to_float(row.get("score")) or 0, reverse=True)
        return {
            "sourceDate": _date_key(session_date),
            "targetDate": _date_key(target_date),
            "generatedAt": _now_label(),
            "universe": CLOSING_VOLUME_UNIVERSE,
            "lookbackDays": CLOSING_VOLUME_LOOKBACK_DAYS,
            "topCountPerSide": CLOSING_VOLUME_TOP_COUNT,
            "spikeMultiple": CLOSING_VOLUME_SPIKE_MULTIPLE,
            "minDailyVolumePct": CLOSING_VOLUME_MIN_DAILY_VOLUME_PCT * 100,
            "minBodyPct": CLOSING_VOLUME_MIN_BODY_PCT * 100,
            "selected": final_rows,
            "eligibleCount": len(selected),
            "errorCount": len(errors),
            "errors": errors[:12],
        }

    def _closing_volume_candidate(
        self,
        symbol: str,
        instrument_key: str,
        session_date: dt.date,
        target_date: dt.date,
    ) -> dict[str, Any] | None:
        lookback_calendar_days = max(45, CLOSING_VOLUME_LOOKBACK_DAYS * 3)
        from_date = session_date - dt.timedelta(days=lookback_calendar_days)
        candles_15m = self.price_streamer.historical_candles(instrument_key, "minutes", 15, from_date, session_date)
        daily = self.price_streamer.historical_candles(instrument_key, "days", 1, from_date, session_date)
        session_candles = [row for row in candles_15m if row.get("date") == session_date]
        if not session_candles:
            return None
        final15 = max(session_candles, key=lambda row: row["datetime"])
        final_open = _to_float(final15.get("open"))
        final_close = _to_float(final15.get("close"))
        final_high = _to_float(final15.get("high"))
        final_low = _to_float(final15.get("low"))
        final_volume = _to_float(final15.get("volume"))
        if final_open is None or final_close is None or final_high is None or final_low is None or final_volume is None or final_open <= 0:
            return None
        if final_close == final_open:
            return None
        side = "BUY" if final_close > final_open else "SHORT"
        body_pct = abs(final_close - final_open) / final_open
        if body_pct < CLOSING_VOLUME_MIN_BODY_PCT:
            return None

        final_by_date: dict[dt.date, dict[str, Any]] = {}
        for row in candles_15m:
            row_date = row.get("date")
            if not isinstance(row_date, dt.date) or row_date >= session_date:
                continue
            current = final_by_date.get(row_date)
            if current is None or row["datetime"] > current["datetime"]:
                final_by_date[row_date] = row
        final_volumes = [
            _to_float(row.get("volume")) or 0
            for _, row in sorted(final_by_date.items(), reverse=True)[:CLOSING_VOLUME_LOOKBACK_DAYS]
        ]
        final_volumes = [volume for volume in final_volumes if volume > 0]
        daily_volumes = [
            _to_float(row.get("volume")) or 0
            for row in daily
            if isinstance(row.get("date"), dt.date) and row["date"] < session_date
        ][-CLOSING_VOLUME_LOOKBACK_DAYS:]
        daily_volumes = [volume for volume in daily_volumes if volume > 0]
        if not final_volumes or not daily_volumes:
            return None
        avg_final15 = sum(final_volumes) / len(final_volumes)
        avg_daily = sum(daily_volumes) / len(daily_volumes)
        volume_spike = final_volume / avg_final15 if avg_final15 else 0
        daily_share = final_volume / avg_daily if avg_daily else 0
        if volume_spike < CLOSING_VOLUME_SPIKE_MULTIPLE or daily_share < CLOSING_VOLUME_MIN_DAILY_VOLUME_PCT:
            return None
        score = (volume_spike * 50) + (daily_share * 200) + (body_pct * 1000)
        return {
            "symbol": symbol,
            "side": side,
            "sessionDate": _date_key(session_date),
            "targetDate": _date_key(target_date),
            "instrumentKey": instrument_key,
            "final15Start": final15.get("datetime").strftime("%Y-%m-%d %H:%M:%S"),
            "final15Open": _round_price(final_open),
            "final15High": _round_price(final_high),
            "final15Low": _round_price(final_low),
            "final15Close": _round_price(final_close),
            "final15Volume": int(final_volume),
            "avgFinal15Volume": int(avg_final15),
            "avgDailyVolume": int(avg_daily),
            "volumeSpike": round(volume_spike, 2),
            "dailyVolumeSharePct": round(daily_share * 100, 2),
            "final15BodyPct": round(body_pct * 100, 2),
            "score": round(score, 2),
        }

    def _market_clock(self, force: bool = False) -> dict[str, Any]:
        today = dt.datetime.now().date()
        now = dt.datetime.now()
        self._refresh_market_reference(today)
        holidays = self.holiday_cache.get(today.year, {})
        holiday_name = holidays.get(_date_key(today), "")
        is_weekend = today.weekday() >= 5
        is_holiday = bool(holiday_name)
        in_hours = MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME
        should_stream = not is_weekend and not is_holiday and in_hours
        if is_weekend:
            reason = "Weekend"
        elif is_holiday:
            reason = f"Trading holiday: {holiday_name}"
        elif now.time() < MARKET_OPEN_TIME:
            reason = "Before market open"
        elif now.time() > MARKET_CLOSE_TIME:
            reason = "After market close"
        else:
            reason = "Market hours"
        if force and not should_stream:
            reason = f"Manual refresh; {reason}"
        next_open = self._next_trading_start(now)
        return {
            "checkedAt": _now_label(),
            "today": _date_key(today),
            "shouldStream": should_stream,
            "manualRefresh": force,
            "reason": reason,
            "isWeekend": is_weekend,
            "isHoliday": is_holiday,
            "holidayName": holiday_name,
            "marketOpenTime": MARKET_OPEN_TIME.strftime("%H:%M"),
            "marketCloseTime": MARKET_CLOSE_TIME.strftime("%H:%M"),
            "nextOpenAt": next_open.strftime("%Y-%m-%d %H:%M:%S"),
            "secondsToNextOpen": max(0, int((next_open - now).total_seconds())),
            "holidaySourceOk": not self.holiday_error,
            "holidayError": self.holiday_error,
            "marketStatusSourceOk": not self.market_status_error,
            "marketStatusError": self.market_status_error,
            "nextHoliday": self._next_holiday(today),
        }

    def _refresh_market_reference(self, today: dt.date) -> None:
        now = time.time()
        if today.year not in self.holiday_cache or now - self.holiday_loaded_at > 12 * 60 * 60:
            try:
                self.holiday_cache[today.year] = self._parse_holidays(self.client.fetch_trading_holidays())
                self.holiday_loaded_at = now
                self.holiday_error = None
            except Exception as exc:  # noqa: BLE001 - fallback to weekend/clock gate and surface the issue
                self.holiday_error = str(exc)
                self.holiday_loaded_at = now
                self.holiday_cache.setdefault(today.year, {})
        if now - self.market_status_loaded_at > 5 * 60:
            try:
                self.market_status_cache = self.client.fetch_market_status()
                self.market_status_loaded_at = now
                self.market_status_error = None
            except Exception as exc:  # noqa: BLE001 - status is informational; clock/holiday still gate streaming
                self.market_status_error = str(exc)
                self.market_status_loaded_at = now

    @staticmethod
    def _parse_holidays(payload: dict[str, Any]) -> dict[str, str]:
        holidays: dict[str, str] = {}
        containers = payload.values() if isinstance(payload, dict) else []
        for container in containers:
            if not isinstance(container, list):
                continue
            for item in container:
                if not isinstance(item, dict):
                    continue
                holiday_date = _parse_nse_date(item.get("tradingDate") or item.get("date") or item.get("holidayDate"))
                if not holiday_date:
                    continue
                description = str(item.get("description") or item.get("name") or item.get("occasion") or "Trading holiday")
                holidays[_date_key(holiday_date)] = description
        return holidays

    def _next_trading_start(self, now: dt.datetime) -> dt.datetime:
        candidate = dt.datetime.combine(now.date(), MARKET_OPEN_TIME)
        if now.time() >= MARKET_OPEN_TIME:
            candidate += dt.timedelta(days=1)
        while True:
            date_key = _date_key(candidate.date())
            holidays = self.holiday_cache.get(candidate.year, {})
            if candidate.weekday() < 5 and date_key not in holidays:
                return candidate
            candidate += dt.timedelta(days=1)

    def _last_trading_date(self, start_date: dt.date) -> dt.date:
        candidate = start_date
        while True:
            self._refresh_market_reference(candidate)
            holidays = self.holiday_cache.get(candidate.year, {})
            if candidate.weekday() < 5 and _date_key(candidate) not in holidays:
                return candidate
            candidate -= dt.timedelta(days=1)

    def _next_trading_date(self, start_date: dt.date) -> dt.date:
        candidate = start_date
        while True:
            self._refresh_market_reference(candidate)
            holidays = self.holiday_cache.get(candidate.year, {})
            if candidate.weekday() < 5 and _date_key(candidate) not in holidays:
                return candidate
            candidate += dt.timedelta(days=1)

    def _next_holiday(self, today: dt.date) -> dict[str, str] | None:
        rows = []
        for year_rows in self.holiday_cache.values():
            for date_key, description in year_rows.items():
                holiday_date = _parse_nse_date(date_key)
                if holiday_date and holiday_date >= today:
                    rows.append((holiday_date, description))
        if not rows:
            return None
        holiday_date, description = min(rows, key=lambda item: item[0])
        return {"date": _date_key(holiday_date), "description": description}

    def _data_provenance(self) -> dict[str, Any]:
        return {
            "mockPricesAllowed": False,
            "priceDataProvider": PRICE_DATA_PROVIDER,
            "indexFeed": NSE_ALL_INDICES_API,
            "stockFeed": NSE_STOCK_INDICES_API,
            "quoteFeed": NSE_QUOTE_EQUITY_API,
            "holidayFeed": NSE_HOLIDAY_API,
            "marketStatusFeed": NSE_MARKET_STATUS_API,
            "upstoxPriceStream": "enabled for selected stocks and active paper trades" if UPSTOX_WEBSOCKET_ENABLED else "disabled; NSE polling marks trades",
            "paperLogic": (
                "NSE sector shortlist with Upstox prices for entries, candles, and SL/TP; no mock price fallback"
                if USE_UPSTOX_PRICE_DATA
                else "live NSE prices only; no mock price fallback; completed M5 candles only"
            ),
        }

    @staticmethod
    def _sector_selection_rule() -> dict[str, Any]:
        return {
            "buyThreshold": BUY_SECTOR_THRESHOLD,
            "sellThreshold": SELL_SECTOR_THRESHOLD,
            "sectorPickCount": SECTOR_PICK_COUNT,
            "stocksPerSector": STOCKS_PER_SECTOR,
            "dailyStockSlLimit": DAILY_STOCK_SL_LIMIT,
            "label": (
                f"Top {SECTOR_PICK_COUNT} buy >= {BUY_SECTOR_THRESHOLD:+.2f}% / "
                f"top {SECTOR_PICK_COUNT} sell <= {SELL_SECTOR_THRESHOLD:+.2f}% / "
                f"{STOCKS_PER_SECTOR} stocks each / "
                f"{DAILY_STOCK_SL_LIMIT} SL per stock threshold"
            ),
        }

    def _fetch_top_movers(self) -> dict[str, Any]:
        checked_at = _now_label()
        try:
            gainers = self._parse_top_mover_payload(self.client.fetch_top_gainers(), "gainer")
            losers = self._parse_top_mover_payload(self.client.fetch_top_losers(), "loser")
            return {
                "checkedAt": checked_at,
                "source": NSE_TOP_GAINERS_LOSERS_URL,
                "gainer": gainers[0] if gainers else None,
                "loser": losers[0] if losers else None,
                "gainers": gainers[:5],
                "losers": losers[:5],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - opening mover thesis should not break the main dashboard
            self.app_log.warn("NSE top movers fetch failed", error=str(exc))
            return {
                "checkedAt": checked_at,
                "source": NSE_TOP_GAINERS_LOSERS_URL,
                "gainer": None,
                "loser": None,
                "gainers": [],
                "losers": [],
                "error": str(exc),
            }

    @staticmethod
    def _parse_top_mover_payload(payload: dict[str, Any], direction: str) -> list[dict[str, Any]]:
        rows = (payload.get("FOSec") or {}).get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            parsed.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "series": row.get("series"),
                    "open": _first_float(row.get("open_price"), row.get("openPrice"), row.get("open")),
                    "high": _first_float(row.get("high_price"), row.get("highPrice"), row.get("high")),
                    "low": _first_float(row.get("low_price"), row.get("lowPrice"), row.get("low")),
                    "ltp": _first_float(row.get("ltp"), row.get("lastPrice"), row.get("last")),
                    "percentChange": _first_float(row.get("perChange"), row.get("net_price"), row.get("percentChange")),
                    "volume": _first_float(row.get("trade_quantity"), row.get("volume")),
                    "turnover": _first_float(row.get("turnover")),
                    "raw": row,
                }
            )
        if direction == "loser":
            parsed.sort(key=lambda item: _to_float(item.get("percentChange")) or 0)
        else:
            parsed.sort(key=lambda item: _to_float(item.get("percentChange")) or 0, reverse=True)
        return parsed

    def _fetch_sector_stock_groups(self, sector_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gain_sectors = [
            row for row in sector_rows
            if row["percentChange"] is not None and row["percentChange"] >= BUY_SECTOR_THRESHOLD
        ][:SECTOR_PICK_COUNT]
        loss_sectors = [
            row for row in sorted(sector_rows, key=lambda row: row["percentChange"])
            if row["percentChange"] is not None and row["percentChange"] <= SELL_SECTOR_THRESHOLD
        ][:SECTOR_PICK_COUNT]
        selections: list[tuple[dict[str, Any], str]] = []
        seen: set[tuple[str, str]] = set()
        for direction, selected_sectors in (("gain", gain_sectors), ("loss", loss_sectors)):
            for sector in selected_sectors:
                key = (sector["symbol"], direction)
                if key not in seen:
                    seen.add(key)
                    selections.append((sector, direction))

        groups = []
        for sector, direction in selections:
            groups.append(self._fetch_sector_stock_group(sector, direction))
        if not gain_sectors:
            groups.append(self._no_setup_group("gain", f"No valid setup: no sector is up at least {BUY_SECTOR_THRESHOLD:.2f}%"))
        if not loss_sectors:
            groups.append(self._no_setup_group("loss", f"No valid setup: no sector is down at least {abs(SELL_SECTOR_THRESHOLD):.2f}%"))
        return groups

    @staticmethod
    def _no_setup_group(direction: str, reason: str) -> dict[str, Any]:
        return {
            "sector": "No valid setup",
            "sectorPercentChange": None,
            "direction": direction,
            "stocks": [],
            "error": None,
            "noSetup": True,
            "reason": reason,
        }

    def _fetch_active_trade_marks(
        self,
        active_targets: dict[str, str],
        stock_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not active_targets:
            return []
        selected_symbols = {
            str(stock.get("symbol") or "")
            for group in stock_groups
            for stock in (group.get("stocks") or [])
        }
        quote_stocks = []
        missing_targets = {
            symbol: sector for symbol, sector in active_targets.items()
            if symbol and symbol not in selected_symbols
        }
        by_sector: dict[str, list[str]] = {}
        for symbol, sector in missing_targets.items():
            by_sector.setdefault(sector, []).append(symbol)

        found_symbols: set[str] = set()
        for sector, symbols in by_sector.items():
            if sector.upper().startswith("NIFTY "):
                try:
                    payload = self.client.fetch_sector_stocks(sector)
                    stocks = self._parse_sector_stocks(payload, sector, "mark")
                    by_symbol = {str(stock.get("symbol") or ""): stock for stock in stocks}
                    for symbol in symbols:
                        stock = by_symbol.get(symbol)
                        if stock:
                            quote_stocks.append(stock)
                            found_symbols.add(symbol)
                except Exception:
                    pass

        for symbol in sorted(set(missing_targets) - found_symbols):
            try:
                quote_stocks.append(_stock_row_from_quote(symbol, self.client.fetch_quote_equity(symbol)))
            except Exception as exc:  # noqa: BLE001 - do not fail the full stream for one stale active mark
                quote_stocks.append({
                    "symbol": symbol,
                    "sector": active_targets.get(symbol) or "ACTIVE PAPER TRADE",
                    "direction": "mark",
                    "current": None,
                    "quoteError": str(exc),
                    "dataSource": "NSE sector constituent feed / quote-equity",
                    "priceIsMock": False,
                })
        return quote_stocks

    def _fetch_sector_stock_group(self, sector: dict[str, Any], direction: str) -> dict[str, Any]:
        sector_symbol = sector["symbol"]
        group = {
            "sector": sector_symbol,
            "sectorPercentChange": sector.get("percentChange"),
            "direction": direction,
            "stocks": [],
            "error": None,
        }
        try:
            payload = self.client.fetch_sector_stocks(sector_symbol)
            stocks = self._parse_sector_stocks(payload, sector_symbol, direction)
            enriched = []
            for stock in stocks[:STOCKS_PER_SECTOR]:
                if stock["vwap"] is not None:
                    stock.pop("_raw", None)
                    enriched.append(stock)
                    continue
                try:
                    quote = self.client.fetch_quote_equity(stock["symbol"])
                    enriched.append(_stock_row(stock["_raw"], sector_symbol, direction, quote))
                except Exception as exc:  # noqa: BLE001 - a missing quote should not hide the sector table
                    stock.pop("_raw", None)
                    stock["quoteError"] = str(exc)
                    enriched.append(stock)
            group["stocks"] = enriched
        except Exception as exc:  # noqa: BLE001 - surface per-sector fetch failures in the UI
            group["error"] = str(exc)
        return group

    @staticmethod
    def _parse_sector_stocks(payload: dict[str, Any], sector_symbol: str, direction: str) -> list[dict[str, Any]]:
        container = payload.get("data") or []
        rows = container.get("data") if isinstance(container, dict) else container
        rows = rows or []
        stocks: list[dict[str, Any]] = []
        sector_upper = sector_symbol.upper()
        for item in rows:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip()
            if item.get("priority") == 1 or not symbol or symbol.upper() == sector_upper or symbol.upper().startswith("NIFTY "):
                continue
            stock = _stock_row(item, sector_symbol, direction)
            stock["_raw"] = item
            if stock["percentChange"] is not None:
                stocks.append(stock)
        stocks.sort(key=lambda row: row["percentChange"], reverse=direction == "gain")
        return stocks

    @staticmethod
    def _parse_payload(payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("data") or []
        sector_rows = [_sector_row(item) for item in rows if isinstance(item, dict) and _is_sector_index(item)]
        sector_rows = [row for row in sector_rows if row["percentChange"] is not None]
        sector_rows.sort(key=lambda row: row["percentChange"], reverse=True)
        index_lookup = {
            str(config.get("symbol") or "").upper(): str(config.get("nseSymbol") or "").upper()
            for config in NIFTY_OPTIONS_INDEXES
        }
        index_spots = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            clean_symbol = _clean_index_symbol(str(item.get("indexSymbol") or item.get("index") or "")).upper()
            for derivative_symbol, nse_symbol in index_lookup.items():
                if clean_symbol == nse_symbol:
                    index_spots[derivative_symbol] = _index_row(item, nse_symbol)
                    index_spots[nse_symbol] = index_spots[derivative_symbol]
                    break
        nifty_item = index_spots.get("NIFTY")
        max_gainer = sector_rows[0] if sector_rows else None
        max_loser = sector_rows[-1] if sector_rows else None
        market_status = payload.get("marketStatus") or payload.get("marketState") or {}
        snapshot_time = (
            payload.get("timestamp")
            or payload.get("time")
            or next((item.get("lastUpdateTime") for item in rows if isinstance(item, dict) and item.get("lastUpdateTime")), None)
        )
        return {
            "sector_rows": sector_rows,
            "max_gainer": max_gainer,
            "max_loser": max_loser,
            "nifty_spot": nifty_item,
            "index_spots": index_spots,
            "market_status": market_status,
            "snapshot_time": snapshot_time,
            "raw_count": len(rows),
        }


streamer = NSEStreamer()


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class AppHandler(BaseHTTPRequestHandler):
    server_version = "NSEHeatmapDashboard/1.0.0"

    def log_message(self, format: str, *args):  # noqa: A002
        return

    def do_GET(self):  # noqa: N802
        url = parse.urlparse(self.path)
        path = url.path
        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            name = path.replace("/static/", "", 1)
            content_type = self._static_content_type(name)
            self._serve_static(name, content_type)
        elif path == "/api/status":
            self._json(streamer.status())
        elif path == "/api/logs":
            params = parse.parse_qs(url.query)
            limit = int(_to_float(params.get("limit", ["200"])[0]) or 200)
            self._json({"ok": True, "logs": streamer.logs(max(1, min(limit, 300)))})
        elif path == "/api/paper-pnl":
            params = parse.parse_qs(url.query)
            date_key = params.get("date", [""])[0]
            self._json({"ok": True, "dailyReport": streamer.paper_report(date_key)})
        else:
            self._not_found()

    def do_POST(self):  # noqa: N802
        if self.path == "/api/start":
            started = streamer.start()
            self._json({"ok": True, "started": started, "status": streamer.status()})
        elif self.path == "/api/stop":
            stopped = streamer.stop()
            self._json({"ok": True, "stopped": stopped, "status": streamer.status()})
        elif self.path == "/api/refresh":
            self._json({"ok": True, "status": streamer.refresh_once()})
        elif self.path == "/api/paper-trades/close":
            payload = self._read_json()
            result = streamer.close_paper_trade(str(payload.get("trade_id") or payload.get("id") or ""))
            self._json(result, 200 if result.get("ok") else 400)
        elif self.path == "/api/options-trades/close":
            payload = self._read_json()
            result = streamer.close_options_trade(str(payload.get("trade_id") or payload.get("id") or ""))
            self._json(result, 200 if result.get("ok") else 400)
        else:
            self._not_found()

    def _serve_static(self, name: str, content_type: str) -> None:
        path = (STATIC_ROOT / name).resolve()
        if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.exists():
            self._not_found()
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _static_content_type(name: str) -> str:
        suffix = Path(name).suffix.lower()
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix == ".js":
            return "application/javascript; charset=utf-8"
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".svg":
            return "image/svg+xml"
        if suffix == ".ico":
            return "image/x-icon"
        return "application/octet-stream"

    def _json(self, data: Any, status: int = 200) -> None:
        encoded = json.dumps(data, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout, OSError) as exc:
            if _is_transient_socket_error(exc):
                return
            raise

    def _not_found(self) -> None:
        self._json({"error": "not found"}, 404)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}


def main() -> None:
    streamer.start()
    server = DashboardHTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), AppHandler)
    print(f"NSE Heatmap Dashboard: {DASHBOARD_URL}")
    print(f"Source: {NSE_HEATMAP_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCtrl+C received. Shutting down NSE Heatmap Dashboard...")
    finally:
        streamer.stop()
        server.server_close()
        print("NSE Heatmap Dashboard stopped.")
