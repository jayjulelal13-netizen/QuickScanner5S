from pathlib import Path

target = Path("build_project/app/src/main/java/com/example/screener/OverlayService.kt")
if not target.exists():
    raise SystemExit(f"OverlayService.kt not found: {target}")

s = target.read_text(encoding="utf-8")

if "private var chartAvailable = false" not in s:
    s = s.replace(
        "private var signalLocked = false",
        "private var signalLocked = false\n    private var chartAvailable = false",
        1,
    )

s = s.replace(
    '"CAPTURE_STARTED" -> {\n                    resetState()',
    '"CAPTURE_STARTED" -> {\n                    chartAvailable = false\n                    resetState()',
    1,
)

# Split chart-state statuses out of the generic scanning group.
old_group = '''"PROJECTION_STARTING", "IMAGE_READER_CREATED", "VIRTUAL_DISPLAY_CREATED",
                "FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",
                "LIVE_ANALYSIS", "CANDLE_RUNNING", "CANDLE_WAITING", "WAITING_NEW_CANDLE",
                "RESULT_WAITING_CANDLE_CONFIRMATION", "ANALYSIS_ERROR", "FRAME_ERROR" -> {'''
new_group = '''"PROJECTION_STARTING", "IMAGE_READER_CREATED", "VIRTUAL_DISPLAY_CREATED",
                "CANDLE_RUNNING", "CANDLE_WAITING", "WAITING_NEW_CANDLE",
                "RESULT_WAITING_CANDLE_CONFIRMATION", "ANALYSIS_ERROR", "FRAME_ERROR" -> {'''
if old_group in s:
    s = s.replace(old_group, new_group, 1)

marker = '                "ANALYSIS_READY" -> {'
if marker not in s:
    raise SystemExit("ANALYSIS_READY marker not found")

if '"NO_CHART / WAITING"' not in s:
    chart_cases = '''                "CANDLES_DETECTED", "FRAME_READY", "LIVE_ANALYSIS" -> {
                    chartAvailable = true
                    if (intent.getStringExtra("status") == "LIVE_ANALYSIS" &&
                        !activeTrade && !signalLocked
                    ) {
                        nextConfidence = intent.getIntExtra("confidence", nextConfidence)
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend
                    }
                    if (!activeTrade && !signalLocked) status = "SCANNING"
                    updateOverlay()
                }

                "CANDLE_DETECTION_WAITING", "HISTORY_WAITING", "NO_CHART_WAITING", "CHART_NOT_DETECTED" -> {
                    chartAvailable = false
                    if (!activeTrade) {
                        nextSignal = "NO TRADE"
                        nextConfidence = 0
                        nextTrend = "WAITING"
                        signalLocked = false
                        status = "NO CHART / WAITING"
                    }
                    updateOverlay()
                }

'''
    s = s.replace(marker, chart_cases + marker, 1)

analysis_start = '''                "ANALYSIS_READY" -> {
                    val signal = intent.getStringExtra("signal")?.uppercase(Locale.US) ?: "NO TRADE"'''
analysis_gate = '''                "ANALYSIS_READY" -> {
                    if (!chartAvailable) {
                        nextSignal = "NO TRADE"
                        nextConfidence = 0
                        nextTrend = "WAITING"
                        signalLocked = false
                        status = "NO CHART / WAITING"
                        updateOverlay()
                        return
                    }

                    val signal = intent.getStringExtra("signal")?.uppercase(Locale.US) ?: "NO TRADE"'''
if analysis_start in s:
    s = s.replace(analysis_start, analysis_gate, 1)
elif 'if (!chartAvailable)' not in s:
    raise SystemExit("ANALYSIS_READY block shape not found")

s = s.replace(
    '"CAPTURE_STOPPED" -> {\n                    removeOverlayNow()',
    '"CAPTURE_STOPPED" -> {\n                    chartAvailable = false\n                    removeOverlayNow()',
    1,
)
s = s.replace(
    '"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {\n',
    '"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {\n                    chartAvailable = false\n',
    1,
)

target.write_text(s, encoding="utf-8")
print("CHART-GATE-FIX applied")
