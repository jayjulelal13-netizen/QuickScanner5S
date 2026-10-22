from pathlib import Path
import os
import re

project = Path(os.environ["PROJECT_DIR"])
overlay = project / "app/src/main/java/com/example/screener/OverlayService.kt"
capture = project / "app/src/main/java/com/example/screener/CaptureService.kt"
gradle = next((p for p in (project / "app/build.gradle.kts", project / "app/build.gradle") if p.exists()), None)
if gradle is None:
    raise SystemExit("App Gradle file missing")

# Add on-device OCR for the visible right-side price bubble/scale.
g = gradle.read_text(encoding="utf-8")
if "com.google.mlkit:text-recognition" not in g:
    dep = 'implementation("com.google.mlkit:text-recognition:16.0.1")'
    if "dependencies {" in g:
        g = g.replace("dependencies {", "dependencies {\n    " + dep, 1)
    else:
        g = g.rstrip() + "\n\ndependencies {\n    " + dep + "\n}\n"
    gradle.write_text(g, encoding="utf-8")

c = capture.read_text(encoding="utf-8")
imports = [
    ("import com.google.mlkit.vision.common.InputImage", "import com.google.mlkit.vision.common.InputImage"),
    ("import com.google.mlkit.vision.text.TextRecognition", "import com.google.mlkit.vision.text.TextRecognition"),
    ("import com.google.mlkit.vision.text.latin.TextRecognizerOptions", "import com.google.mlkit.vision.text.latin.TextRecognizerOptions"),
]
for needle, imp in imports:
    if imp not in c:
        c = c.replace("import android.util.Log", "import android.util.Log\n" + imp, 1)

if "private var quickPriceText = \"WAITING\"" not in c:
    anchor = "class CaptureService : Service() {"
    c = c.replace(anchor, anchor + '''
    @Volatile private var quickPriceText = "WAITING"
    private var lastPriceOcrAt = 0L
    private val priceTextRecognizer by lazy {
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    }

    private fun readVisiblePrice(bitmap: Bitmap) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastPriceOcrAt < 650L) return
        lastPriceOcrAt = now
        // Focus on the chart's right edge where the current quote bubble/axis labels live.
        val left = (bitmap.width * 0.78f).toInt().coerceIn(0, bitmap.width - 1)
        val top = (bitmap.height * 0.18f).toInt().coerceIn(0, bitmap.height - 1)
        val bottom = (bitmap.height * 0.72f).toInt().coerceIn(top + 1, bitmap.height)
        val crop = try {
            Bitmap.createBitmap(bitmap, left, top, bitmap.width - left, bottom - top)
        } catch (_: Exception) { return }
        val image = InputImage.fromBitmap(crop, 0)
        priceTextRecognizer.process(image)
            .addOnSuccessListener { result ->
                val candidates = result.textBlocks.flatMap { block ->
                    block.lines.map { it.text.trim() }
                }.map { it.replace(',', '.') }
                    .filter { it.matches(Regex("\\d{1,3}\\.\\d{3,8}")) }
                // Prefer the longer quote-like decimal (e.g. 0.80383) over short axis labels.
                val best = candidates.maxByOrNull { it.substringAfter('.', "").length }
                if (best != null) quickPriceText = best
            }
            .addOnFailureListener { Log.w(TAG, "Price OCR failed", it) }
            .addOnCompleteListener { crop.recycle() }
    }
''', 1)

# OCR each quick-mode frame before chart-specific signal logic.
anchor = '''        // 5S QUICK target is a blue LINE chart, not OHLC candles.
        if (quickMode) {'''
if anchor in c:
    c = c.replace(anchor, '''        if (quickMode) readVisiblePrice(bitmap)

        // 5S QUICK signal logic remains unchanged; OCR only reads the visible quote.
        if (quickMode) {''', 1)
else:
    raise SystemExit("Quick mode processBitmap anchor missing")

# Broadcast OCR value with the existing quick status.
anchor = '            putExtra("quickStatus", statusText)'
if anchor in c and 'putExtra("quickPriceText", quickPriceText)' not in c:
    c = c.replace(anchor, anchor + '\n            putExtra("quickPriceText", quickPriceText)', 1)
capture.write_text(c, encoding="utf-8")

o = overlay.read_text(encoding="utf-8")
if "private var quickPriceText = \"WAITING\"" not in o:
    anchor = '    private var quickStatus = "WAITING"'
    if anchor not in o:
        raise SystemExit("Overlay quickStatus field anchor missing")
    o = o.replace(anchor, anchor + '\n    private var quickPriceText = "WAITING"', 1)
anchor = '''                    val quickStatus = intent.getStringExtra("quickStatus")
                        ?: "SCANNING LINE CHART"'''
if 'quickPriceText = intent.getStringExtra("quickPriceText")' not in o:
    if anchor not in o:
        # tolerate alternate fallback text
        pat = r'(val quickStatus = intent.getStringExtra\("quickStatus"\)\s*\?:\s*"[^"]*")'
        o, n = re.subn(pat, r'\1\n                    quickPriceText = intent.getStringExtra("quickPriceText") ?: quickPriceText', o, count=1)
        if n != 1: raise SystemExit("Overlay QUICK_5S receiver anchor missing")
    else:
        o = o.replace(anchor, anchor + '\n                    quickPriceText = intent.getStringExtra("quickPriceText") ?: quickPriceText', 1)

if '"LINE LEVEL: $quickPriceText' not in o:
    # Place a quote label immediately below the chart label in the overlay.
    o, n = re.subn(r'("CHART: [^"]*\\n" \+)', r'\1\n            "LINE LEVEL: $quickPriceText\\n" +', o, count=1)
    if n != 1:
        raise SystemExit("Overlay chart label anchor missing")
overlay.write_text(o, encoding="utf-8")
print("Added on-device OCR for visible quote bubble and LINE LEVEL display.")
