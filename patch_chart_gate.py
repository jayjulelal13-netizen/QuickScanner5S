from pathlib import Path
import re

targets = list(Path("build_project").rglob("OverlayService.kt"))
if not targets:
    raise SystemExit("OverlayService.kt not found")

changed = 0
for target in targets:
    s = target.read_text(encoding="utf-8")
    before = s

    # Force the 5S quick-state variables into class scope. Older patch versions
    # could accidentally place them inside the BroadcastReceiver, making them
    # unavailable to updateOverlay/buildOverlayText.
    class_open = "class OverlayService : Service() {"
    if class_open not in s:
        raise SystemExit("OverlayService class declaration not found")

    names = ["quickMode", "quickChartPresent", "quickSignal", "quickProbability", "quickSamples", "quickStatus"]
    for name in names:
        s = re.sub(rf"^[ \\t]*private var {name} = .*?\\n", "", s, flags=re.MULTILINE)

    state = '''\n    private var quickMode = false\n    private var quickChartPresent = false\n    private var quickSignal = "NO TRADE"\n    private var quickProbability = 0\n    private var quickSamples = 0\n    private var quickStatus = "WAITING"\n'''
    s = s.replace(class_open, class_open + state, 1)

    # Every explicit no-chart state must wipe the complete quick state.
    old = '''"CHART_NOT_DETECTED" -> {\n                    nextSignal = "NO TRADE"'''
    new = '''"CHART_NOT_DETECTED" -> {\n                    if (quickMode) {\n                        updateOverlay()\n                        return\n                    }\n                    quickChartPresent = false\n                    quickSignal = "NO TRADE"\n                    quickProbability = 0\n                    quickSamples = 0\n                    quickStatus = "NO CHART / WAITING"\n                    nextSignal = "NO TRADE"'''
    s = s.replace(old, new, 1)

    old = '''if (!quickMode && (intent.getStringExtra("status") == "NO_CHART_WAITING" ||\n                        intent.getStringExtra("status") == "CANDLE_DETECTION_WAITING" ||\n                        intent.getStringExtra("status") == "HISTORY_WAITING")) {\n                        nextSignal = "NO TRADE"'''
    new = '''if (!quickMode && (intent.getStringExtra("status") == "NO_CHART_WAITING" ||\n                        intent.getStringExtra("status") == "CANDLE_DETECTION_WAITING" ||\n                        intent.getStringExtra("status") == "HISTORY_WAITING")) {\n                        quickChartPresent = false\n                        quickSignal = "NO TRADE"\n                        quickProbability = 0\n                        quickSamples = 0\n                        quickStatus = "NO CHART / WAITING"\n                        nextSignal = "NO TRADE"'''
    s = s.replace(old, new, 1)

    # A chart is present only after the engine reports actual detected candles.
    old = '''if (intent.hasExtra("count")) {\n                candleCount = intent.getIntExtra("count", candleCount)\n            }'''
    new = '''if (intent.hasExtra("count")) {\n                candleCount = intent.getIntExtra("count", candleCount)\n                if (intent.getStringExtra("status") == "CANDLES_DETECTED" && !quickMode) {\n                    quickChartPresent = candleCount > 0\n                    if (!quickChartPresent) {\n                        quickSignal = "NO TRADE"\n                        quickProbability = 0\n                        quickSamples = 0\n                        quickStatus = "NO CHART / WAITING"\n                        signalLocked = false\n                    }\n                }\n            }'''
    s = s.replace(old, new, 1)

    # Never resurrect a stale 5S signal while the chart gate is closed.
    old = '''"QUICK_5S" -> {\n                    quickMode = true\n                    quickSignal ='''
    new = '''"QUICK_5S" -> {\n                    quickMode = true\n                    val lineSamples = intent.getIntExtra("quickSamples", 0)\n                    if (lineSamples > 0) {
                        quickChartPresent = true
                        quickLastLineSeenMs = System.currentTimeMillis()
                    }\n                    if (!quickChartPresent) {\n                        quickSignal = "NO TRADE"\n                        quickProbability = 0\n                        quickSamples = 0\n                        quickStatus = "NO CHART / WAITING"\n                        signalLocked = false\n                        updateOverlay()\n                        return\n                    }\n                    quickSignal ='''
    s = s.replace(old, new, 1)

    # Guard 5S ANALYSIS_READY as well.
    old = '''if (quickMode) {\n                        updateOverlay()\n                        return\n                    }\n                    if (timeframe == "5S") {\n                        quickSignal = if ((signal == "CALL" || signal == "PUT") && confidence >= CONFIDENCE_LEVEL) signal else "NO TRADE"'''
    new = '''if (timeframe == "5S") {\n                        if (!quickChartPresent) {\n                            quickSignal = "NO TRADE"\n                            quickProbability = 0\n                            quickSamples = 0\n                            quickStatus = "NO CHART / WAITING"\n                            signalLocked = false\n                            updateOverlay()\n                            return\n                        }\n                        quickSignal = if ((signal == "CALL" || signal == "PUT") && confidence >= CONFIDENCE_LEVEL) signal else "NO TRADE"'''
    s = s.replace(old, new, 1)

    # Capture start/reset invalidates chart presence.
    s = s.replace(
        '"CAPTURE_STARTED" -> {\\n                    resetState()',
        '"CAPTURE_STARTED" -> {\\n                    quickChartPresent = false\\n                    resetState()',
        1
    )
    s = s.replace(
        'private fun resetState() {\\n        timeframe = "1M"',
        'private fun resetState() {\\n        quickChartPresent = false\\n        timeframe = "1M"',
        1
    )

    if s != before:
        target.write_text(s, encoding="utf-8")
        changed += 1

if changed == 0:
    raise SystemExit("Chart gate source already patched or patterns unavailable")
print("CHART-GATE CLASS-SCOPE OK:", changed, "OverlayService file(s)")
