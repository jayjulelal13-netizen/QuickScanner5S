#!/usr/bin/env python3
from pathlib import Path
import os

project = Path(os.environ["PROJECT_DIR"])
src = project / "app/src/main/java/com/example/screener"
cap = src / "CaptureService.kt"
if not cap.exists():
    raise SystemExit(f"CaptureService.kt missing: {cap}")
s = cap.read_text(encoding="utf-8")
start_marker = "        // 5S QUICK target is a blue LINE chart, not OHLC candles."
end_marker = "        val detected ="
start = s.find(start_marker)
if start >= 0:
    end = s.find(end_marker, start)
    if end < 0:
        raise SystemExit("Could not find candle-engine handoff after line-chart block")
    s = s[:start] + s[end:]
elif "LineChartAnalyzer.extractPriceY(bitmap)" in s:
    raise SystemExit("Line-chart quick path found but expected block boundaries differ")

# Ensure the 5S branch receives the actual CandleAnalyzer output, not a line sample.
if "LineChartAnalyzer.extractPriceY(bitmap)" in s:
    raise SystemExit("5S line-chart interception remains active")
if "val detected =" not in s:
    raise SystemExit("Candle detection entry point missing")
if "updateQuick5s(currentRunningCandle)" not in s and "updateQuick5s(detected.last())" not in s:
    raise SystemExit("Quick engine is not connected to detected candles")
cap.write_text(s, encoding="utf-8")

# Quotex chart ends above the timer/investment controls. Excluding those controls
# prevents the large green Buy/red Sell buttons from polluting candle detection.
ca = src / "CandleAnalyzer.kt"
a = ca.read_text(encoding="utf-8")
a = a.replace("val bottom = (height * 0.72f).toInt().coerceIn(top + 240, height)",
              "val bottom = (height * 0.60f).toInt().coerceIn(top + 240, height)", 1)
a = a.replace("val chartRight = (width * 0.84f).toInt().coerceIn(chartLeft + 180, width - 1)",
              "val chartRight = (width * 0.82f).toInt().coerceIn(chartLeft + 180, width - 1)", 1)
if "val bottom = (height * 0.60f)" not in a:
    raise SystemExit("Candle ROI bottom adjustment did not apply")
if "val chartRight = (width * 0.82f)" not in a:
    raise SystemExit("Candle ROI right adjustment did not apply")
ca.write_text(a, encoding="utf-8")
print("5S QUICK now uses OHLC candles; excluded lower trading controls from candle detection")
