from __future__ import annotations

from dataclasses import dataclass, field
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


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"

NSE_HOME = "https://www.nseindia.com"
NSE_HEATMAP_URL = f"{NSE_HOME}/market-data/live-market-indices/heatmap"
NSE_LIVE_EQUITY_URL = f"{NSE_HOME}/market-data/live-equity-market?symbol=NIFTY%2050"
NSE_ALL_INDICES_API = f"{NSE_HOME}/api/allIndices"
NSE_STOCK_INDICES_API = f"{NSE_HOME}/api/NextApi/apiClient/marketWatchApi?functionName=getIndicesData"
NSE_QUOTE_EQUITY_API = f"{NSE_HOME}/api/quote-equity"
POLL_SECONDS = 30
SECTOR_PICK_COUNT = 2
STOCKS_PER_SECTOR = 5

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


def _now_label() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


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
        return self._fetch_with_cookie_retry(f"{NSE_QUOTE_EQUITY_API}?symbol={encoded}")

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
    poll_seconds: int = POLL_SECONDS
    fetch_count: int = 0
    sector_rows: list[dict[str, Any]] = field(default_factory=list)
    sector_stock_groups: list[dict[str, Any]] = field(default_factory=list)
    max_gainer: dict[str, Any] | None = None
    max_loser: dict[str, Any] | None = None
    market_status: dict[str, Any] = field(default_factory=dict)
    snapshot_time: str | None = None
    raw_count: int = 0


class NSEStreamer:
    def __init__(self) -> None:
        self.client = NSEClient()
        self.state = FeedState()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

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
            return True

    def stop(self) -> bool:
        with self.lock:
            was_running = self.state.running
            self.state.running = False
            self.stop_event.set()
            return was_running

    def refresh_once(self) -> dict[str, Any]:
        self._fetch_and_store()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            data = {
                **self.state.__dict__,
                "streaming_label": "On" if self.state.running else "Off",
            }
        return data

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._fetch_and_store()
            self.stop_event.wait(POLL_SECONDS)

    def _fetch_and_store(self) -> None:
        with self.lock:
            self.state.last_fetch_started_at = _now_label()
        try:
            payload = self.client.fetch_all_indices()
            parsed = self._parse_payload(payload)
            stock_groups = self._fetch_sector_stock_groups(parsed["sector_rows"])
            with self.lock:
                self.state.last_error = None
                self.state.last_success_at = _now_label()
                self.state.fetch_count += 1
                self.state.sector_rows = parsed["sector_rows"]
                self.state.sector_stock_groups = stock_groups
                self.state.max_gainer = parsed["max_gainer"]
                self.state.max_loser = parsed["max_loser"]
                self.state.market_status = parsed["market_status"]
                self.state.snapshot_time = parsed["snapshot_time"]
                self.state.raw_count = parsed["raw_count"]
        except Exception as exc:  # noqa: BLE001 - surface the feed problem to the UI
            with self.lock:
                self.state.last_error = str(exc)

    def _fetch_sector_stock_groups(self, sector_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gain_sectors = sector_rows[:SECTOR_PICK_COUNT]
        loss_sectors = sorted(sector_rows, key=lambda row: row["percentChange"])[:SECTOR_PICK_COUNT]
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
        return groups

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
    server_version = "NSEHeatmapDashboard/0.1"

    def log_message(self, format: str, *args):  # noqa: A002
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path.startswith("/?"):
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif self.path.startswith("/static/"):
            name = self.path.replace("/static/", "", 1).split("?", 1)[0]
            content_type = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8"
            self._serve_static(name, content_type)
        elif self.path == "/api/status":
            self._json(streamer.status())
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


def main() -> None:
    host = "127.0.0.1"
    port = 8775
    streamer.start()
    server = DashboardHTTPServer((host, port), AppHandler)
    url = f"http://{host}:{port}"
    print(f"NSE Heatmap Dashboard: {url}")
    print(f"Source: {NSE_HEATMAP_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCtrl+C received. Shutting down NSE Heatmap Dashboard...")
    finally:
        streamer.stop()
        server.server_close()
        print("NSE Heatmap Dashboard stopped.")
