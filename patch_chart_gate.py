from pathlib import Path

targets = list(Path("build_project").rglob("OverlayService.kt"))
if not targets:
    raise SystemExit("OverlayService.kt not found")

changed = 0
for target in targets:
    s = target.read_text(encoding="utf-8")
    before = s

    # Ensure all quick-state properties exist at class scope, immediately after quickMode.
    if "private var quickChartPresent" not in s:
        s = s.replace(
            "    private var quickMode = false",
            """    private var quickMode = false
    private var quickChartPresent = false
    private var quickSignal = "NO TRADE"
    private var quickProbability = 0
    private var quickSamples = 0
    private var quickStatus = "WAITING"""",
            1
        )

    # Every explicit no-chart state must wipe the complete quick state.
    old = '''"CHART_NOT_DETECTED" -> {
                    nextSignal = "NO TRADE"'''
    new = '''"CHART_NOT_DETECTED" -> {
                    quickChartPresent = false
                    quickSignal = "NO TRADE"
                    quickProbability = 0
                    quickSamples = 0
                    quickStatus = "NO CHART / WAITING"
                    nextSignal = "NO TRADE"'''
    s = s.replace(old, new, 1)

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
    s = s.replace(old, new, 1)

    # Chart is considered present only when candles are actually detected.
    old = '''"FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",'''
    new = '''"FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",'''
    # no-op marker; actual state is set from CANDLES_DETECTED below.

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
    s = s.replace(old, new, 1)

    # Guard QUICK_5S messages from resurrecting a stale signal.
    old = '''"QUICK_5S" -> {
                    quickMode = true
                    quickSignal ='''
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
                    quickSignal ='''
    s = s.replace(old, new, 1)

    # Guard 5S ANALYSIS_READY.
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
    s = s.replace(old, new, 1)

    # Make capture start/reset invalidate chart presence.
    s = s.replace(
        '"CAPTURE_STARTED" -> {\n                    resetState()',
        '"CAPTURE_STARTED" -> {\n                    quickChartPresent = false\n                    resetState()',
        1
    )

    # Ensure resetState also clears the gate.
    s = s.replace(
        'private fun resetState() {\n        timeframe = "1M"',
        'private fun resetState() {\n        quickChartPresent = false\n        timeframe = "1M"',
        1
    )

    if s != before:
        target.write_text(s, encoding="utf-8")
        changed += 1

if changed == 0:
    raise SystemExit("Chart gate source already patched or patterns unavailable")
print("CHART-GATE V2 OK:", changed, "OverlayService file(s)")
