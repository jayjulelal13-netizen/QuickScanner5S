from pathlib import Path
import os
import re

project = Path(os.environ["PROJECT_DIR"])
overlay = project / "app/src/main/java/com/example/screener/OverlayService.kt"
capture = project / "app/src/main/java/com/example/screener/CaptureService.kt"

o = overlay.read_text()

# Add field without depending on a particular previous patch's formatting.
if "private var quickPriceLevel = Double.NaN" not in o:
    m = re.search(r'(?m)^\s*private var quickStatus = "WAITING"\s*$', o)
    if not m:
        raise SystemExit("QuickScanner overlay field anchor missing")
    o = o[:m.end()] + '\n    private var quickPriceLevel = Double.NaN' + o[m.end():]

# Read the value in the QUICK_5S broadcast regardless of fallback status wording.
if 'quickPriceLevel = intent.getDoubleExtra("quickPriceLevel"' not in o:
    pattern = r'(val quickStatus = intent.getStringExtra\("quickStatus"\)\s*\?:\s*"[^"]*")'
    o, n = re.subn(pattern, r'\1\n                    quickPriceLevel = intent.getDoubleExtra("quickPriceLevel", Double.NaN)', o, count=1)
    if n != 1:
        raise SystemExit("QuickScanner overlay quickStatus block not found")

# Add a clearly-labelled screen coordinate to the quick overlay text.
if '"LINE LEVEL: $lineLevelText' not in o:
    m = re.search(r'(return "5S QUICK\\n" \+\s*\n\s*"CHART: [^"]*\\n" \+)', o)
    if m:
        line = '''
        val lineLevelText = if (quickPriceLevel.isNaN() || quickPriceLevel.isInfinite()) {
            "WAITING"
        } else {
            String.format(Locale.US, "%.1f px", quickPriceLevel)
        }
'''
        o = o[:m.start()] + line + o[m.start():]
        pos = m.start() + len(line)
        o = o[:pos] + o[pos:].replace(m.group(1), m.group(1) + '\n            "LINE LEVEL: $lineLevelText\\n" +', 1)
    else:
        raise SystemExit("QuickScanner 5S overlay text anchor not found")
overlay.write_text(o)

c = capture.read_text()
if '"quickPriceLevel"' not in c:
    # Locate sendQuickStatus extras by their stable quickSamples line.
    pattern = r'(?m)^(\s*)putExtra\("quickSamples", samples\)\s*$'
    m = re.search(pattern, c)
    if not m:
        raise SystemExit("QuickScanner sendQuickStatus quickSamples anchor not found")
    indent = m.group(1)
    insertion = '\n' + indent + '// Screen Y coordinate of detected line; not the broker quote.\n' + indent + 'putExtra("quickPriceLevel", lineSamples.lastOrNull()?.second ?: Double.NaN)'
    c = c[:m.end()] + insertion + c[m.end():]
capture.write_text(c)
print("QuickScanner5S line-level overlay patch applied.")
