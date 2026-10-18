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
print("5S QUICK now falls through to CandleAnalyzer OHLC detection; line-chart interception removed")
