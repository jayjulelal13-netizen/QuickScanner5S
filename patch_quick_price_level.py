from pathlib import Path
import os
import re

project = Path(os.environ["PROJECT_DIR"])
overlay = project / "app/src/main/java/com/example/screener/OverlayService.kt"
o = overlay.read_text(encoding="utf-8")

# QuickScanner5S is a candle-chart scanner. A blue-line detector is not a valid
# price source for this screen, so remove the misleading LINE LEVEL field.
o = re.sub(r'(?m)^\s*private var quickPriceLevel = Double\.NaN\s*\n?', '', o)
o = re.sub(r'(?m)^\s*quickPriceLevel = intent\.getDoubleExtra\("quickPriceLevel", Double\.NaN\)\s*\n?', '', o)
o = re.sub(
    r'(?s)\s*val lineLevelText = if \(quickPriceLevel\.isNaN\(\).*?\n\s*"LINE LEVEL: \$lineLevelText\\n" \+',
    '',
    o
)
overlay.write_text(o, encoding="utf-8")
print("QuickScanner5S: removed misleading line-chart level; candle/pressure overlay retained.")
