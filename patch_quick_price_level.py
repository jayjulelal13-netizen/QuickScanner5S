from pathlib import Path
import os
import re

project = Path(os.environ["PROJECT_DIR"])
overlay = project / "app/src/main/java/com/example/screener/OverlayService.kt"
capture = project / "app/src/main/java/com/example/screener/CaptureService.kt"
gradle = next((p for p in (project / "app/build.gradle.kts", project / "app/build.gradle") if p.exists()), None)
if gradle is None:
    raise SystemExit("App Gradle file missing")

g = gradle.read_text(encoding="utf-8")
if "com.google.mlkit:text-recognition" not in g:
    dep = 'implementation("com.google.mlkit:text-recognition:16.0.1")'
    if "dependencies {" in g:
        g = g.replace("dependencies {", "dependencies {\n    " + dep, 1)
    else:
        g = g.rstrip() + "\n\ndependencies {\n    " + dep + "\n}\n"
    gradle.write_text(g, encoding="utf-8")

c = capture.read_text(encoding="utf-8")
for imp in [
    "import com.google.mlkit.vision.common.InputImage",
    "import com.google.mlkit.vision.text.TextRecognition",
    "import com.google.mlkit.vision.text.latin.TextRecognizerOptions",
]:
    if imp not in c:
        c = c.replace("import android.util.Log", "import android.util.Log\n" + imp, 1)

if 'private var quickPriceText = "WAITING"' not in c:
    c = c.replace("class CaptureService : Service() {", '''class CaptureService : Service() {
    @Volatile private var quickPriceText = "WAITING"
    private var lastPriceOcrAt = 0L
    private val priceTextRecognizer by lazy {
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    }

    private fun readVisiblePrice(bitmap: Bitmap) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastPriceOcrAt < 700L) return
        lastPriceOcrAt = now
        val left = (bitmap.width * 0.78f).toInt().coerceIn(0, bitmap.width - 1)
        val top = (bitmap.height * 0.18f).toInt().coerceIn(0, bitmap.height - 1)
        val bottom = (bitmap.height * 0.72f).toInt().coerceIn(top + 1, bitmap.height)
        val crop = try { Bitmap.createBitmap(bitmap, left, top, bitmap.width - left, bottom - top) }
            catch (_: Exception) { return }
        priceTextRecognizer.process(InputImage.fromBitmap(crop, 0))
            .addOnSuccessListener { result ->
                val values = result.textBlocks.flatMap { it.lines }.map { it.text.trim().replace(',', '.') }
                    .filter { it.matches(Regex("\\\\d{1,3}\\\\.\\\\d{3,8}")) }
                values.maxByOrNull { it.substringAfter('.').length }?.let { quickPriceText = it }
            }
            .addOnFailureListener { Log.w(TAG, "Price OCR failed", it) }
            .addOnCompleteListener { crop.recycle() }
    }
''', 1)

# Inject OCR at the start of processBitmap, regardless of the existing chart mode comments.
marker = "    private fun processBitmap("
start = c.find(marker)
if start < 0: raise SystemExit("processBitmap function not found")
body = c.find("{", start)
if body < 0: raise SystemExit("processBitmap body not found")
if "readVisiblePrice(bitmap)" not in c[body:body+500]:
    c = c[:body+1] + '\n        if (quickMode) readVisiblePrice(bitmap)\n' + c[body+1:]

anchor = 'putExtra("quickStatus", statusText)'
if anchor not in c: raise SystemExit("quickStatus broadcast anchor missing")
if 'putExtra("quickPriceText", quickPriceText)' not in c:
    c = c.replace(anchor, anchor + '\n            putExtra("quickPriceText", quickPriceText)', 1)
capture.write_text(c, encoding="utf-8")

o = overlay.read_text(encoding="utf-8")
if 'private var quickPriceText = "WAITING"' not in o:
    anchor = '    private var quickStatus = "WAITING"'
    if anchor not in o: raise SystemExit("overlay quickStatus field missing")
    o = o.replace(anchor, anchor + '\n    private var quickPriceText = "WAITING"', 1)
if 'quickPriceText = intent.getStringExtra("quickPriceText")' not in o:
    pattern = r'(val quickStatus = intent.getStringExtra\("quickStatus"\)\s*\?:\s*"[^"]*")'
    o, n = re.subn(pattern, r'\1\n                    quickPriceText = intent.getStringExtra("quickPriceText") ?: quickPriceText', o, count=1)
    if n != 1: raise SystemExit("overlay QUICK_5S receiver missing")
if '"LINE LEVEL: $quickPriceText' not in o:
    o, n = re.subn(r'("CHART: [^"]*\\n" \+)', r'\1\n            "LINE LEVEL: $quickPriceText\\n" +', o, count=1)
    if n != 1: raise SystemExit("overlay chart label missing")

if 'private var quickResultText = "WAITING"' not in o:
    o = o.replace('    private var quickStatus = "WAITING"', '    private var quickStatus = "WAITING"\n    private var quickResultText = "WAITING"')
if 'quickResultText = intent.getStringExtra("quickResult")' not in o:
    anchor = 'quickPriceText = intent.getStringExtra("quickPriceText") ?: quickPriceText'
    if anchor not in o: raise SystemExit("overlay price receiver anchor missing")
    o = o.replace(anchor, anchor + '\n                    quickResultText = intent.getStringExtra("quickResult") ?: quickResultText', 1)
if '"RESULT: $quickResultText' not in o:
    # Insert result on the next line after the line-level display, independent of escaping style.
    marker = '"LINE LEVEL: $quickPriceText'
    pos = o.find(marker)
    if pos < 0: raise SystemExit("overlay line-level label missing")
    end = o.find('" +', pos)
    if end < 0: raise SystemExit("overlay line-level expression end missing")
    end += 3
    o = o[:end] + '\n            "RESULT: $quickResultText\\n" +' + o[end:]

overlay.write_text(o, encoding="utf-8")
print("OCR price-label patch applied.")
