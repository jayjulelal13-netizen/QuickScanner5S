#!/usr/bin/env python3
from pathlib import Path

files = list(Path("build_project").rglob("OverlayService.kt"))
if not files:
    raise SystemExit("OverlayService.kt not found")
changed = 0
for p in files:
    s = p.read_text(encoding="utf-8")
    before = s

    # Never manufacture a 90% value from a weaker score.
    s = s.replace('nextConfidence = strength.coerceAtLeast(90)', 'nextConfidence = strength')
    # The overlay must not call the detected chart a line chart.
    s = s.replace('"CHART: LINE\\n" +', '"CHART: CANDLE DETECTION\\n" +')
    # Reject malformed/low-score signals; retain NO TRADE otherwise.
    s = s.replace('if (signal == "CALL" || signal == "PUT") {',
                  'if ((signal == "CALL" || signal == "PUT") && strength >= CONFIDENCE_LEVEL && quickSamples > 0 && !quickStatus.contains("WAITING", ignoreCase = true) && !quickStatus.contains("NO LINE", ignoreCase = true)) {', 1)
    # Avoid a misleading 90% display for any locked result.
    s = s.replace('nextConfidence.coerceAtLeast(90)', 'nextConfidence')
    if s != before:
        p.write_text(s, encoding="utf-8")
        changed += 1
if changed == 0:
    raise SystemExit("Overlay safety patch made no changes; source layout differs")
print("Overlay: removed artificial 90% floor; requires >=90 score and candle status")
