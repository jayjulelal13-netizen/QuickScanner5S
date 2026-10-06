from pathlib import Path

roots = [
    Path("build_project/app/src/main/java/com/example/screener"),
    Path("build_project"),
]
files = []
for root in roots:
    if root.exists():
        files.extend(root.rglob("OverlayService.kt"))
files = list(dict.fromkeys(files))
if not files:
    raise SystemExit("OverlayService.kt not found")

patched = 0
for target in files:
    s = target.read_text(encoding="utf-8")
    original = s

    if "private var quickChartPresent = false" not in s:
        anchor = "private var quickMode = false"
        if anchor in s:
            s = s.replace(anchor, anchor + "\n    private var quickChartPresent = false", 1)
        else:
            anchor = 'private var quickSignal = "NO TRADE"'
            if anchor in s:
                s = s.replace(anchor, "private var quickChartPresent = false\n\n    " + anchor, 1)
            else:
                continue

    # Reset quick state on explicit chart-not-detected.
    old = '''"CHART_NOT_DETECTED" -> {
                    nextSignal = "NO TRADE"'''
    new = '''"CHART_NOT_DETECTED" -> {
                    quickChartPresent = false
                    quickSignal = "NO TRADE"
                    quickProbability = 0
                    quickSamples = 0
                    quickStatus = "NO CHART / WAITING"
                    nextSignal = "NO TRADE"'''
    if old in s and 'quickStatus = "NO CHART / WAITING"' not in s:
        s = s.replace(old, new, 1)

    # In CANDLES_DETECTED, count=0 is the missing-chart signal.
    old = '''if (intent.hasExtra("count")) {
                candleCount = intent.getIntExtra("count", candleCount)
            }'''
    new = '''if (intent.hasExtra("count")) {
                candleCount = intent.getIntExtra("count", candleCount)
                if (intent.getStringExtra("status") == "CANDLES_DETECTED") {
                    quickChartPresent = candleCount > 0
                    if (!quickChartPresent) {
                        quickSignal = "NO TRADE"
                        quickProbability = 0
                        quickSamples = 0
                        quickStatus = "NO CHART / WAITING"
                        signalLocked = false
                    }
                }
            }'''
    if old in s and 'quickChartPresent = candleCount > 0' not in s:
        s = s.replace(old, new, 1)

    # Existing grouped no-chart branch: clear all quick fields too.
    old = '''if (intent.getStringExtra("status") == "NO_CHART_WAITING" ||
                        intent.getStringExtra("status") == "CANDLE_DETECTION_WAITING" ||
                        intent.getStringExtra("status") == "HISTORY_WAITING") {
                        nextSignal = "NO TRADE"'''
    new = '''if (intent.getStringExtra("status") == "NO_CHART_WAITING" ||
                        intent.getStringExtra("status") == "CANDLE_DETECTION_WAITING" ||
                        intent.getStringExtra("status") == "HISTORY_WAITING") {
                        quickChartPresent = false
                        quickSignal = "NO TRADE"
                        quickProbability = 0
                        quickSamples = 0
                        quickStatus = "NO CHART / WAITING"
                        nextSignal = "NO TRADE"'''
    if old in s:
        s = s.replace(old, new, 1)

    # Guard QUICK_5S payloads themselves.
    old = '''"QUICK_5S" -> {
                    quickMode = true
                    quickSignal =
                        intent.getStringExtra("quickSignal")'''
    new = '''"QUICK_5S" -> {
                    quickMode = true
                    if (!quickChartPresent) {
                        quickSignal = "NO TRADE"
                        quickProbability = 0
                        quickSamples = 0
                        quickStatus = "NO CHART / WAITING"
                        updateOverlay()
                        return
                    }
                    quickSignal =
                        intent.getStringExtra("quickSignal")'''
    if old in s:
        s = s.replace(old, new, 1)

    # Guard 5S ANALYSIS_READY against stale analysis after chart loss.
    old = '''if (timeframe == "5S") {
                        quickSignal = if ((signal == "CALL" || signal == "PUT") && confidence >= CONFIDENCE_LEVEL) signal else "NO TRADE"'''
    new = '''if (timeframe == "5S") {
                        if (!quickChartPresent) {
                            quickSignal = "NO TRADE"
                            quickProbability = 0
                            quickSamples = 0
                            quickStatus = "NO CHART / WAITING"
                            updateOverlay()
                            return
                        }
                        quickSignal = if ((signal == "CALL" || signal == "PUT") && confidence >= CONFIDENCE_LEVEL) signal else "NO TRADE"'''
    if old in s:
        s = s.replace(old, new, 1)

    # Clear quick state on capture stop/errors.
    s = s.replace('"CAPTURE_STOPPED" -> {\n                    removeOverlayNow()', '"CAPTURE_STOPPED" -> {\n                    quickChartPresent = false\n                    quickSignal = "NO TRADE"\n                    quickProbability = 0\n                    quickSamples = 0\n                    quickStatus = "NO CHART / WAITING"\n                    removeOverlayNow()', 1)
    s = s.replace('"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {\n', '"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {\n                    quickChartPresent = false\n                    quickSignal = "NO TRADE"\n                    quickProbability = 0\n                    quickSamples = 0\n                    quickStatus = "NO CHART / WAITING"\n', 1)

    if s != original:
        target.write_text(s, encoding="utf-8")
        patched += 1

if patched == 0:
    raise SystemExit("No matching OverlayService source pattern was patched")
print("CHART-GATE V2 patched", patched, "OverlayService file(s)")
