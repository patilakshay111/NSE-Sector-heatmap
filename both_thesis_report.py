from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_STATE_PATH = ROOT / "data" / "paper_trading_state.json"
THESIS_VWAP = "VWAP M5 Retest"
THESIS_FIB = "Fib Retracement Confirm"


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def date_key(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Paper trading state was not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def available_dates(state: dict[str, Any]) -> list[str]:
    dates: set[str] = set()
    for trade in state.get("closedTrades") or []:
        for field in ("entryTime", "openedAt", "exitTime", "closedAt"):
            key = date_key(trade.get(field))
            if key:
                dates.add(key)
    open_map = state.get("openTrades") or state.get("activeTrades") or {}
    open_trades = list(open_map.values()) if isinstance(open_map, dict) else []
    for trade in open_trades:
        for field in ("entryTime", "openedAt"):
            key = date_key(trade.get(field))
            if key:
                dates.add(key)
    return sorted(dates)


def closed_trades_for_date(trades: list[dict[str, Any]], report_date: str | None) -> list[dict[str, Any]]:
    if not report_date:
        return trades
    return [
        trade
        for trade in trades
        if date_key(trade.get("entryTime") or trade.get("openedAt")) == report_date
        or date_key(trade.get("exitTime") or trade.get("closedAt")) == report_date
    ]


def open_trades_for_date(trades: list[dict[str, Any]], report_date: str | None) -> list[dict[str, Any]]:
    if not report_date:
        return trades
    return [
        trade
        for trade in trades
        if date_key(trade.get("entryTime") or trade.get("openedAt")) == report_date
    ]


def has_both_theses(trades: list[dict[str, Any]]) -> bool:
    theses = {str(trade.get("thesis") or "") for trade in trades}
    return THESIS_VWAP in theses and THESIS_FIB in theses


def group_key(trade: dict[str, Any]) -> str:
    return "|".join(
        [
            str(trade.get("symbol") or ""),
            str(trade.get("side") or ""),
            str(trade.get("entryTime") or trade.get("openedAt") or ""),
        ]
    )


def both_thesis_groups(trades: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        groups.setdefault(group_key(trade), []).append(trade)
    return [group for group in groups.values() if has_both_theses(group)]


def matched_trade(group: list[dict[str, Any]]) -> dict[str, Any]:
    trade = sorted(group, key=lambda item: str(item.get("id") or ""))[0]
    entry = to_float(trade.get("entry"))
    exit_price = to_float(trade.get("exitPrice"))
    quantity = int(to_float(trade.get("quantity")))
    allocation = to_float(trade.get("allocation"))
    pnl = to_float(trade.get("realizedPnl")) if trade.get("realizedPnl") is not None else None
    deployed = entry * quantity
    if pnl is None and quantity and entry and exit_price:
        if trade.get("side") == "BUY":
            pnl = (exit_price - entry) * quantity
        else:
            pnl = (entry - exit_price) * quantity
    pnl = pnl or 0.0
    original_ids = ", ".join(str(item.get("id") or "-") for item in sorted(group, key=lambda item: str(item.get("id") or "")))
    return {
        "id": str(trade.get("id") or "-"),
        "originalIds": original_ids,
        "symbol": str(trade.get("symbol") or "-"),
        "sector": str(trade.get("sector") or "-"),
        "side": str(trade.get("side") or "-"),
        "entryTime": str(trade.get("entryTime") or trade.get("openedAt") or "-"),
        "exitTime": str(trade.get("exitTime") or trade.get("closedAt") or "-"),
        "exitReason": str(trade.get("exitReason") or "-"),
        "entry": entry,
        "exit": exit_price,
        "quantity": quantity,
        "allocation": allocation,
        "deployed": deployed,
        "pnl": pnl,
        "pnlPct": (pnl / deployed) * 100 if deployed else 0.0,
    }


def open_signal(group: list[dict[str, Any]]) -> dict[str, Any]:
    trade = sorted(group, key=lambda item: str(item.get("id") or ""))[0]
    entry = to_float(trade.get("entry"))
    current = to_float(trade.get("currentPrice"))
    quantity = int(to_float(trade.get("quantity")))
    allocation = to_float(trade.get("allocation"))
    pnl = to_float(trade.get("unrealizedPnl")) if trade.get("unrealizedPnl") is not None else None
    if pnl is None and quantity and entry and current:
        if trade.get("side") == "BUY":
            pnl = (current - entry) * quantity
        else:
            pnl = (entry - current) * quantity
    pnl = pnl or 0.0
    return {
        "ids": ", ".join(str(item.get("id") or "-") for item in sorted(group, key=lambda item: str(item.get("id") or ""))),
        "symbol": str(trade.get("symbol") or "-"),
        "side": str(trade.get("side") or "-"),
        "entryTime": str(trade.get("entryTime") or trade.get("openedAt") or "-"),
        "entry": entry,
        "current": current,
        "quantity": quantity,
        "allocation": allocation,
        "unrealizedPnl": pnl,
    }


def stats(trades: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    pnls = [to_float(trade.get("pnl")) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    breakeven = [pnl for pnl in pnls if pnl == 0]
    gross_profit = sum(wins)
    gross_loss_raw = sum(losses)
    gross_loss = abs(gross_loss_raw)
    net = sum(pnls)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    worst_losing_streak = 0
    current_losing_streak = 0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
        if pnl < 0:
            current_losing_streak += 1
            worst_losing_streak = max(worst_losing_streak, current_losing_streak)
        else:
            current_losing_streak = 0
    total_allocation = sum(to_float(trade.get("allocation")) for trade in trades)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "winRate": (len(wins) / len(trades)) * 100 if trades else None,
        "netPnl": net,
        "grossProfit": gross_profit,
        "grossLoss": gross_loss,
        "profitFactor": gross_profit / gross_loss if gross_loss else None,
        "avgPnl": net / len(trades) if trades else None,
        "avgWin": gross_profit / len(wins) if wins else None,
        "avgLoss": gross_loss_raw / len(losses) if losses else None,
        "bestTrade": max(pnls) if pnls else None,
        "worstTrade": min(pnls) if pnls else None,
        "maxDrawdown": max_drawdown,
        "returnOnInitialCapitalPct": (net / initial_capital) * 100 if initial_capital else None,
        "returnOnTotalAllocatedPct": (net / total_allocation) * 100 if total_allocation else None,
        "worstLosingStreak": worst_losing_streak,
        "avgDeployed": sum(to_float(trade.get("deployed")) for trade in trades) / len(trades) if trades else None,
        "avgAllocation": sum(to_float(trade.get("allocation")) for trade in trades) / len(trades) if trades else None,
    }


def money(value: Any) -> str:
    if value is None:
        return "-"
    number = to_float(value)
    return f"Rs {number:,.2f}"


def pct(value: Any) -> str:
    if value is None:
        return "-"
    return f"{to_float(value):.3f}%"


def number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{to_float(value):,.{digits}f}"


def print_kv(rows: list[tuple[str, str]]) -> None:
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label:<{width}} : {value}")


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str, int]]) -> None:
    if not rows:
        print("(none)")
        return
    header = "  ".join(label.ljust(width) for _, label, width in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        parts = []
        for key, _, width in columns:
            value = str(row.get(key, ""))
            parts.append(value[:width].ljust(width))
        print("  ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report saved both-thesis paper trades.",
    )
    parser.add_argument("--date", type=parse_date, help="Filter by entry or exit date, YYYY-MM-DD.")
    parser.add_argument("--list-dates", action="store_true", help="Print saved report dates and exit.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Path to paper_trading_state.json.")
    args = parser.parse_args()

    state = load_state(args.state)
    if args.list_dates:
        for report_date in available_dates(state):
            print(report_date)
        return

    initial_capital = to_float(state.get("initialCapital"), 1_000_000.0)
    closed = closed_trades_for_date(list(state.get("closedTrades") or []), args.date)
    open_map = state.get("openTrades") or state.get("activeTrades") or {}
    open_trades = list(open_map.values()) if isinstance(open_map, dict) else []
    open_trades = open_trades_for_date(open_trades, args.date)

    closed_signals = [
        matched_trade(group)
        for group in both_thesis_groups(closed)
    ]
    closed_signals.sort(key=lambda trade: trade["exitTime"])
    open_signals = [
        open_signal(group)
        for group in both_thesis_groups(open_trades)
    ]
    open_signals.sort(key=lambda trade: trade["entryTime"])
    result = stats(closed_signals, initial_capital)

    title_date = args.date or "all dates"
    print()
    print(f"Both-Thesis Paper Trade Report ({title_date})")
    print("=" * 48)
    print_kv(
        [
            ("State file", str(args.state)),
            ("Saved at", str(state.get("savedAt") or "-")),
            ("Rule", f"same symbol + side + entry time has both '{THESIS_VWAP}' and '{THESIS_FIB}'"),
            ("Sizing", "saved quantity/allocation, no resizing"),
            ("Closed trades", str(result["trades"])),
            ("Open matching trades", str(len(open_signals))),
            ("Wins / Losses / BE", f"{result['wins']} / {result['losses']} / {result['breakeven']}"),
            ("Win rate", pct(result["winRate"])),
            ("Net P/L", money(result["netPnl"])),
            ("Gross profit", money(result["grossProfit"])),
            ("Gross loss", money(result["grossLoss"])),
            ("Profit factor", number(result["profitFactor"])),
            ("Avg P/L per trade", money(result["avgPnl"])),
            ("Avg win", money(result["avgWin"])),
            ("Avg loss", money(result["avgLoss"])),
            ("Best trade", money(result["bestTrade"])),
            ("Worst trade", money(result["worstTrade"])),
            ("Max realized DD", money(result["maxDrawdown"])),
            ("Return on initial capital", pct(result["returnOnInitialCapitalPct"])),
            ("Return on total allocation", pct(result["returnOnTotalAllocatedPct"])),
            ("Worst losing streak", str(result["worstLosingStreak"])),
            ("Avg saved allocation", money(result["avgAllocation"])),
            ("Avg deployed", money(result["avgDeployed"])),
        ]
    )

    print()
    print("Closed Trades")
    print("-" * 48)
    table_rows = [
        {
            "id": trade["id"],
            "ids": trade["originalIds"],
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entryTime": trade["entryTime"],
            "exitTime": trade["exitTime"],
            "reason": trade["exitReason"],
            "entry": number(trade["entry"]),
            "exit": number(trade["exit"]),
            "qty": str(trade["quantity"]),
            "allocation": money(trade["allocation"]),
            "deployed": money(trade["deployed"]),
            "pnl": money(trade["pnl"]),
            "pnlPct": pct(trade["pnlPct"]),
        }
        for trade in closed_signals
    ]
    print_table(
        table_rows,
        [
            ("id", "ID", 7),
            ("symbol", "Symbol", 12),
            ("side", "Side", 6),
            ("reason", "Exit", 8),
            ("entryTime", "Entry Time", 36),
            ("exitTime", "Exit Time", 36),
            ("entry", "Entry", 10),
            ("exit", "Exit", 10),
            ("qty", "Qty", 6),
            ("allocation", "Allocation", 14),
            ("deployed", "Deployed", 14),
            ("pnl", "P/L", 14),
            ("pnlPct", "P/L %", 9),
            ("ids", "Saved IDs", 16),
        ],
    )

    print()
    print("Open Matching Trades")
    print("-" * 48)
    open_rows = [
        {
            "ids": trade["ids"],
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entryTime": trade["entryTime"],
            "entry": number(trade["entry"]),
            "current": number(trade["current"]),
            "qty": str(trade["quantity"]),
            "allocation": money(trade["allocation"]),
            "unrealizedPnl": money(trade["unrealizedPnl"]),
        }
        for trade in open_signals
    ]
    print_table(
        open_rows,
        [
            ("symbol", "Symbol", 12),
            ("side", "Side", 6),
            ("entryTime", "Entry Time", 36),
            ("entry", "Entry", 10),
            ("current", "Current", 10),
            ("qty", "Qty", 6),
            ("allocation", "Allocation", 14),
            ("unrealizedPnl", "Open P/L", 14),
            ("ids", "Saved IDs", 16),
        ],
    )
    print()


if __name__ == "__main__":
    main()
