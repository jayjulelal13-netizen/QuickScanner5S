from pathlib import Path
import os

project = Path(os.environ["PROJECT_DIR"])
overlay = project / "app/src/main/java/com/example/screener/OverlayService.kt"
capture = project / "app/src/main/java/com/example/screener/CaptureService.kt"

o = overlay.read_text()
if "private var quickPriceLevel = Double.NaN" not in o:
    anchor = '    private var quickStatus = "WAITING"'
    if anchor not in o:
        raise SystemExit("QuickScanner overlay anchor missing: quickStatus")
    o = o.replace(anchor, anchor + '\n    private var quickPriceLevel = Double.NaN', 1)

anchor = '''                    val quickStatus = intent.getStringExtra("quickStatus")
                        ?: "SCANNING LINE CHART"'''
replacement = '''                    val quickStatus = intent.getStringExtra("quickStatus")
                        ?: "SCANNING LINE CHART"
                    quickPriceLevel = intent.getDoubleExtra("quickPriceLevel", Double.NaN)'''
if 'quickPriceLevel = intent.getDoubleExtra("quickPriceLevel"' not in o:
    if anchor not in o:
        raise SystemExit("QuickScanner overlay anchor missing: QUICK_5S quickStatus")
    o = o.replace(anchor, replacement, 1)

anchor = '''        return "5S QUICK\\n" +
            "CHART: LINE\\n" +
            "SIGNAL: ${if (signalLocked) nextSignal else "NO TRADE"}\\n" +'''
replacement = '''        val lineLevelText = if (quickPriceLevel.isNaN() || quickPriceLevel.isInfinite()) {
            "WAITING"
        } else {
            String.format(Locale.US, "%.1f px", quickPriceLevel)
        }
        return "5S QUICK\\n" +
            "CHART: LINE\\n" +
            "LINE LEVEL: $lineLevelText\\n" +
            "SIGNAL: ${if (signalLocked) nextSignal else "NO TRADE"}\\n" +'''
if '"LINE LEVEL: $lineLevelText' not in o:
    if anchor not in o:
        raise SystemExit("QuickScanner overlay anchor missing: buildOverlayText")
    o = o.replace(anchor, replacement, 1)
overlay.write_text(o)

c = capture.read_text()
anchor = '''            putExtra("quickSamples", samples)
            putExtra("quickStatus", statusText)'''
replacement = '''            putExtra("quickSamples", samples)
            // This is the detected screen Y coordinate of the line, not a broker quote.
            putExtra("quickPriceLevel", lineSamples.lastOrNull()?.second ?: Double.NaN)
            putExtra("quickStatus", statusText)'''
if '"quickPriceLevel"' not in c:
    if anchor not in c:
        raise SystemExit("QuickScanner capture anchor missing: sendQuickStatus")
    c = c.replace(anchor, replacement, 1)
capture.write_text(c)
print("QuickScanner5S-only line level overlay patch applied.")
