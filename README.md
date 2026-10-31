# NSE Heatmap Dashboard

[![GitHub release](https://img.shields.io/github/release/patilakshay111/Project-self-healing-docs-with-PR.svg?label=Latest)](https://github.com/patilakshay111/Project-self-healing-docs-with-PR/releases/latest)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-Self--Healing%20Docs-blue?logo=github)](https://github.com/marketplace)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-green?logo=openai)](https://platform.openai.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://www.docker.com/)
[![GitHub Actions](https://img.shields.io/badge/CI-GitHub%20Actions-gray?logo=github-actions)](https://github.com/features/actions)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Local operator dashboard for NSE live market index heatmap monitoring.

## Start

```powershell
python run.py
```

Then open:

```text
http://127.0.0.1:8775
```

You can change the dashboard host, port, and URL in `src/nse_heatmap_dashboard/config.py`.

The stream starts automatically. Use the top-right controls to pause, resume, or force-refresh the NSE feed.

## Optional Upstox Price Streaming

The default mode is unchanged: NSE polling marks paper trades every `POLL_SECONDS`.

To use Upstox websocket ticks for selected sector stocks and active paper trades:

```powershell
pip install -r requirements-upstox.txt
$env:PRICE_DATA_PROVIDER = "upstox"
python run.py
```

Paste Upstox tokens in this local ignored file:

```text
.run/upstox-token.json
```

Use this shape:

```json
{
  "access_token": "paste-access-token-here",
  "analytics_token": "paste-analytics-token-here"
}
```

You can also set tokens for only the current terminal session:

```powershell
$env:UPSTOX_ACCESS_TOKEN = "paste-access-token-here"
$env:UPSTOX_ANALYTICS_TOKEN = "paste-analytics-token-here"
```

Token lookup order is `UPSTOX_ACCESS_TOKEN`, `UPSTOX_ANALYTICS_TOKEN`, then `.run/upstox-token.json`. The app resolves NSE symbols to Upstox equity instrument keys and caches them in `data/upstox_instrument_cache.json`.

`PRICE_STREAM_PROVIDER=upstox_websocket` still works as a legacy alias, but `PRICE_DATA_PROVIDER` is the preferred switch.

To switch back to the original NSE polling-only mode:

```powershell
$env:PRICE_DATA_PROVIDER = "nse"
python run.py
```

If a symbol needs a manual key, set semicolon-separated overrides:

```powershell
$env:UPSTOX_INSTRUMENT_OVERRIDES = "RELIANCE=NSE_EQ|INE002A01018;TCS=NSE_EQ|INE467B01029"
```

When enabled, Upstox ticks update displayed selected-stock LTPs and immediately re-check active paper trade SL/TP. NSE polling still runs for sector selection, M5 candles, ideas, and fallback marking.

## Main Files

- `src/nse_heatmap_dashboard/app.py` - local UI/API server and NSE polling client
- `src/nse_heatmap_dashboard/config.py` - dashboard, NSE feed, polling, and paper-trading configuration
- `src/nse_heatmap_dashboard/static/index.html` - dashboard shell with multiple pages
- `src/nse_heatmap_dashboard/static/styles.css` - Trading Agent inspired visual styling
- `src/nse_heatmap_dashboard/static/app.js` - frontend refresh, navigation, and rendering
