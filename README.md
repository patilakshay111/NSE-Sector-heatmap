# NSE Heatmap Dashboard

Local operator dashboard for NSE live market index heatmap monitoring.

## Start

```powershell
python run.py
```

Then open:

```text
http://127.0.0.1:8775
```

The stream starts automatically. Use the top-right controls to pause, resume, or force-refresh the NSE feed.

## Main Files

- `src/nse_heatmap_dashboard/app.py` - local UI/API server and NSE polling client
- `src/nse_heatmap_dashboard/config.py` - dashboard, NSE feed, polling, and paper-trading configuration
- `src/nse_heatmap_dashboard/static/index.html` - dashboard shell with multiple pages
- `src/nse_heatmap_dashboard/static/styles.css` - Trading Agent inspired visual styling
- `src/nse_heatmap_dashboard/static/app.js` - frontend refresh, navigation, and rendering
