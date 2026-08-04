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
    NSE_ALL_INDICES_API,
    NSE_HEATMAP_URL,
    NSE_HOLIDAY_API,
    NSE_HOME,
    NSE_LIVE_EQUITY_URL,
    NSE_MARKET_STATUS_API,
    NSE_QUOTE_EQUITY_API,
    NSE_STOCK_INDICES_API,
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


class PaperTradingEngine:
    def __init__(self) -> None:
        self.initial_capital = PAPER_INITIAL_CAPITAL
        self.trade_allocation = PAPER_TRADE_ALLOCATION
        self.realized_pnl = 0.0
        self.candles: dict[str, list[dict[str, Any]]] = {}
        self.active_trades: dict[str, dict[str, Any]] = {}
        self.closed_trades: list[dict[str, Any]] = []
        self.fib_watch: dict[str, dict[str, Any]] = {}
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
        with self.opener.open(req, timeout=15) as response:
            response.read(2048)
        self.last_cookie_refresh = time.time()

    def _get_json(self, url: str, referer: str = NSE_HEATMAP_URL) -> dict[str, Any]:
        req = request.Request(url, headers=self._headers(referer))
        with self.opener.open(req, timeout=15) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8"))

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


class UpstoxPriceStreamer:
    def __init__(self, on_prices, app_log: AppLog | None = None) -> None:
        self.on_prices = on_prices
        self.app_log = app_log
        self.enabled = UPSTOX_WEBSOCKET_ENABLED
        self.token = UPSTOX_ACCESS_TOKEN
        self.mode = UPSTOX_MARKET_FEED_MODE or "ltpc"
        self.resolver = UpstoxInstrumentResolver(self.token) if self.token else None
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
        with request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else {}
        return data if isinstance(data, dict) else {}

    def _headers(self) -> dict[str, str]:
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
    price_streaming: dict[str, Any] = field(default_factory=dict)
    max_gainer: dict[str, Any] | None = None
    max_loser: dict[str, Any] | None = None
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

    def paper_report(self, date_key: str | None = None) -> dict[str, Any]:
        with self.paper_lock:
            return self.paper_engine.daily_report(date_key)

    def _handle_stream_prices(self, ticks: list[dict[str, Any]]) -> None:
        if not ticks:
            return
        with self.paper_lock:
            paper_trading = self.paper_engine.mark_stream_prices(ticks)
        with self.lock:
            self._overlay_stream_prices_locked(ticks)
            self.state.paper_trading = paper_trading
            self.state.price_streaming = self.price_streamer.status()
        self._refresh_price_stream_targets()

    def _refresh_price_stream_targets(self) -> None:
        if not UPSTOX_WEBSOCKET_ENABLED:
            return
        with self.paper_lock:
            active_targets = self.paper_engine.active_mark_targets()
        with self.lock:
            stock_groups = list(self.state.sector_stock_groups)
        self.price_streamer.update_targets(self._stream_subscription_targets(stock_groups, active_targets))

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
            stock_groups = self._fetch_sector_stock_groups(parsed["sector_rows"])
            with self.paper_lock:
                active_targets = self.paper_engine.active_mark_targets()
            websocket_allowed = bool(market_clock.get("shouldStream"))
            self.price_streamer.set_stream_allowed(websocket_allowed, str(market_clock.get("reason") or "market clock"))
            if USE_UPSTOX_PRICE_DATA:
                price_targets = self._price_stream_targets(stock_groups, active_targets)
                upstox_marks = self.price_streamer.quote_stocks(price_targets)
                stock_groups = self._apply_price_targets_to_groups(stock_groups, upstox_marks)
                active_quote_stocks = [
                    stock for stock in upstox_marks
                    if str(stock.get("symbol") or "").strip().upper() in {symbol.upper() for symbol in active_targets}
                ]
            else:
                active_quote_stocks = self._fetch_active_trade_marks(active_targets, stock_groups)
            if websocket_allowed:
                self.price_streamer.update_targets(self._stream_subscription_targets(stock_groups, active_targets))
            else:
                self.price_streamer.update_targets([])
            with self.paper_lock:
                paper_trading = self.paper_engine.update(
                    stock_groups,
                    market_open=bool(market_clock.get("shouldStream")),
                    mark_stocks=active_quote_stocks,
                )
            with self.lock:
                self.state.last_error = None
                self.state.last_success_at = _now_label()
                self.state.fetch_count += 1
                self.state.sector_rows = parsed["sector_rows"]
                self.state.sector_stock_groups = stock_groups
                self.state.paper_trading = paper_trading
                self.state.max_gainer = parsed["max_gainer"]
                self.state.max_loser = parsed["max_loser"]
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
        with self.paper_lock:
            paper_trading = self.paper_engine.snapshot()
        with self.lock:
            self.state.market_clock = clock
            self.state.market_status = self.market_status_cache
            self.state.data_provenance = self._data_provenance()
            self.state.paper_trading = paper_trading
            self.state.price_streaming = self.price_streamer.status()

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
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout):
            return

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
