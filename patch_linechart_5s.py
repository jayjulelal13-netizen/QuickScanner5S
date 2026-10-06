#!/usr/bin/env python3
from pathlib import Path

root = Path("build_project")
projects = list(root.rglob("settings.gradle.kts")) + list(root.rglob("settings.gradle"))
if not projects:
    raise SystemExit("Android project not found")
project = projects[0].parent
src = project / "app" / "src" / "main" / "java" / "com" / "example" / "screener"
cap = src / "CaptureService.kt"
overlay = src / "OverlayService.kt"
if not cap.exists() or not overlay.exists():
    raise SystemExit(f"Expected screener sources missing: {src}")

# The UI label is "5S QUICK" while the older source compared against the
# internal token "5S". That mismatch left quickMode=false, so the line-chart
# engine was never reached. Normalize all MainActivity quick-mode checks here.
main = src / "MainActivity.kt"
if not main.exists():
    raise SystemExit(f"Expected MainActivity missing: {main}")
m = main.read_text(encoding="utf-8")
m = m.replace('selectedTimeframe != "5S"', 'selectedTimeframe != "5S QUICK"')
m = m.replace('selectedTimeframe == "5S"', 'selectedTimeframe == "5S QUICK"')
# 5S QUICK must be broker-timeframe independent. The scanner samples the
# visible line every ~200 ms and derives a 5-second demo window from movement;
# it must not force the broker UI to 1M.
m = m.replace('if (selectedTimeframe == "5S QUICK") "1M" else selectedTimeframe',
              'selectedTimeframe')

m = m.replace('                "5S" -> "Chart stays on 1M for 5S QUICK"', '                "5S QUICK" -> "Chart stays on 1M for 5S QUICK"')
m = m.replace('                "5S" -> "Selected: 5S QUICK (Chart: 1M)"', '                "5S QUICK" -> "Selected: 5S QUICK (Chart: 1M)"')
main.write_text(m, encoding="utf-8")
print("5S QUICK activation token fixed")

# Binomo 5ST requires the broker chart itself to stay at 1 second.
# Keep the scanner's internal quick path tied to that real chart timeframe.
cap_path = src / "CaptureService.kt"
cap_text = cap_path.read_text(encoding="utf-8")
cap_text = cap_text.replace('The broker chart\n        // remains on 1M; quickMode observes successive 1M screen frames\n        // and derives the 5-second move from the running candle.', 'Binomo 5ST requires a 1-second broker chart; quickMode observes the\n        // live 1-second screen frames and derives the 5-second demo window.')
cap_text = cap_text.replace('if (quickMode) {\n            selectedTimeframe = "1M"\n        }', 'if (quickMode) {\n            selectedTimeframe = "1S"\n        }')
cap_path.write_text(cap_text, encoding="utf-8")
print("Binomo 5ST 1-second timeframe fixed")

line = src / "LineChartAnalyzer.kt"
line.write_text(r"""package com.example.screener

import android.graphics.Bitmap
import android.graphics.Color
import kotlin.math.roundToInt

object LineChartAnalyzer {
    fun extractPriceY(bitmap: Bitmap): Double? {
        val w = bitmap.width
        val h = bitmap.height
        if (w < 300 || h < 500) return null

        // Binomo's visible line chart has a blue filled area. The actual
        // price is the TOP EDGE of that area, never the average of all blue
        // pixels (the old average produced fake momentum).
        val left = (w * 0.03f).roundToInt().coerceAtLeast(0)
        val right = (w * 0.42f).roundToInt().coerceAtMost(w - 1)
        val top = (h * 0.18f).roundToInt().coerceAtLeast(0)
        val bottom = (h * 0.54f).roundToInt().coerceAtMost(h - 1)
        if (right - left < 120 || bottom - top < 120) return null

        val hsv = FloatArray(3)
        val points = ArrayList<Pair<Int, Float>>(220)

        for (x in left..right step 2) {
            var minY = Int.MAX_VALUE
            var y = top
            while (y <= bottom) {
                val pixel = bitmap.getPixel(x, y)
                Color.colorToHSV(pixel, hsv)
                val r = Color.red(pixel)
                val g = Color.green(pixel)
                val b = Color.blue(pixel)

                val blueHsv = hsv[0] >= 185f && hsv[0] <= 245f &&
                    hsv[1] >= 0.28f && hsv[2] >= 0.30f
                val blueRgb = b > 110 && b > r * 1.35f && b > g * 1.08f

                if (blueHsv || blueRgb) minY = y
                y += 2
            }
            if (minY != Int.MAX_VALUE) points.add(x to minY.toFloat())
        }

        if (points.size < 18) return null

        // Reject isolated blue UI/text pixels by requiring local continuity.
        val continuous = ArrayList<Float>(points.size)
        var previous = Float.NaN
        for ((_, y) in points) {
            if (previous.isNaN() || kotlin.math.abs(y - previous) <= h * 0.10f) {
                continuous.add(y)
                previous = y
            }
        }
        if (continuous.size < 12) return null

        // Only the newest part of the price line drives momentum.
        return continuous.takeLast(minOf(8, continuous.size)).average()
    }
}
""", encoding="utf-8")

c = cap.read_text(encoding="utf-8")
c = c.replace("private const val FRAME_INTERVAL = 1000L",
              "private const val FRAME_INTERVAL = 200L", 1)

state_marker = "    private var quickLastSetupBucket = -1L\n"
state_insert = """    private var quickLastSetupBucket = -1L

    private var lineSignalDirection = "NONE"
    private var lineSignalEntryY = Double.NaN
    private var lineSignalUntilMs = 0L
    private var lineLastSignalMs = 0L
    private val lineSamples = ArrayDeque<Pair<Long, Double>>()
"""
if state_marker not in c:
    raise SystemExit("quick state marker not found")
c = c.replace(state_marker, state_insert, 1)

reset_marker = """        quickLastSetupKey = ""
        quickLastSetupBucket = -1L
"""
reset_insert = """        quickLastSetupKey = ""
        quickLastSetupBucket = -1L

        lineSignalDirection = "NONE"
        lineSignalEntryY = Double.NaN
        lineSignalUntilMs = 0L
        lineLastSignalMs = 0L
        lineSamples.clear()
"""
if reset_marker not in c:
    raise SystemExit("reset marker not found")
c = c.replace(reset_marker, reset_insert, 1)

proc_marker = """        if (!running) {
            return
        }

        val detected =
"""
proc_insert = """        if (!running) {
            return
        }

        // 5S QUICK target is a blue LINE chart, not OHLC candles.
        if (quickMode) {
            try {
                val lineY = LineChartAnalyzer.extractPriceY(bitmap)
                if (lineY != null) {
                    updateQuickLine5s(lineY)
                    sendCandleCount(0)
                    return
                }
            } catch (e: Exception) {
                Log.e(TAG, "Line chart detection failed", e)
            }
        }

        val detected =
"""
if proc_marker not in c:
    raise SystemExit("process marker not found")
c = c.replace(proc_marker, proc_insert, 1)

quick_marker = """    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
"""
line_engine = """    private fun updateQuickLine5s(priceY: Double) {
        val now = System.currentTimeMillis()
        lineSamples.addLast(now to priceY)
        while (lineSamples.isNotEmpty() && now - lineSamples.first().first > 2200L) {
            lineSamples.removeFirst()
        }

        if (lineSignalDirection == "CALL" || lineSignalDirection == "PUT") {
            if (now >= lineSignalUntilMs) {
                val win = if (lineSignalDirection == "CALL") {
                    priceY < lineSignalEntryY
                } else {
                    priceY > lineSignalEntryY
                }
                sendQuickStatus(
                    "NO TRADE", 0, lineSamples.size,
                    if (win) "5S DEMO RESULT: WIN" else "5S DEMO RESULT: LOSS"
                )
                lineSignalDirection = "NONE"
                lineSignalEntryY = Double.NaN
                lineSignalUntilMs = 0L
                lineLastSignalMs = now
            } else {
                sendQuickStatus(lineSignalDirection, 0, lineSamples.size, "5S SIGNAL LOCKED")
                return
            }
        }

        if (lineSamples.size < 5) {
            sendQuickStatus("NO TRADE", 0, lineSamples.size, "LINE DETECTED • WARMING")
            return
        }

        val values = lineSamples.map { it.second }
        val first = values.first()
        val last = values.last()
        val delta = first - last

        // Ignore sub-pixel jitter. Direction must agree across most observed
        // moves before a 90% signal is allowed.
        var up = 0
        var down = 0
        var previous = first
        for (y in values.drop(1)) {
            val d = previous - y
            if (d > 2.0) up++
            else if (d < -2.0) down++
            previous = y
        }

        val directionalMoves = up + down
        if (directionalMoves < 5) {
            val scanScore = (55 + kotlin.math.abs(delta).coerceAtMost(15.0)).roundToInt()
            sendQuickStatus("NO TRADE", scanScore.coerceIn(0, 89), lineSamples.size,
                "LINE DETECTED • SCANNING")
            return
        }

        val agreement = maxOf(up, down).toDouble() / directionalMoves.toDouble()
        val movement = kotlin.math.abs(delta)

        val movementScore = when {
            movement >= 55.0 -> 45
            movement >= 40.0 -> 38
            movement >= 30.0 -> 32
            movement >= 22.0 -> 26
            movement >= 16.0 -> 20
            movement >= 12.0 -> 14
            else -> 8
        }
        val agreementScore = when {
            agreement >= 0.92 -> 45
            agreement >= 0.85 -> 40
            agreement >= 0.78 -> 34
            agreement >= 0.72 -> 27
            agreement >= 0.66 -> 20
            else -> 10
        }

        val momentum = (movementScore + agreementScore).coerceIn(0, 99)
        val strongDirection = if (up > down) "CALL" else "PUT"

        // Both meaningful movement and strong directional agreement are
        // mandatory. This removes the previous false-90% behavior.
        val strong = movement >= 22.0 && agreement >= 0.78 && momentum >= 90

        if (strong) {
            lineSignalDirection = strongDirection
            lineSignalEntryY = priceY
            lineSignalUntilMs = now + 5000L
            lineLastSignalMs = now

            sendQuickStatus(
                strongDirection, momentum, lineSamples.size,
                "5S DEMO SIGNAL • LOCK 5 SEC"
            )
        } else {
            sendQuickStatus(
                "NO TRADE", momentum.coerceAtMost(89), lineSamples.size,
                "LINE DETECTED • SCANNING"
            )
        }
    }

"""""
if quick_marker not in c:
    raise SystemExit("quick function marker not found")
c = c.replace(quick_marker, line_engine + quick_marker, 1)
cap.write_text(c, encoding="utf-8")

o = overlay.read_text(encoding="utf-8")
analysis_marker = """                "ANALYSIS_READY" -> {
"""
quick_case = """                "QUICK_5S" -> {
                    val signal = intent.getStringExtra("quickSignal")
                        ?.uppercase(Locale.US) ?: "NO TRADE"
                    val strength = intent.getIntExtra("quickProbability", 0)
                    val quickStatus = intent.getStringExtra("quickStatus")
                        ?: "SCANNING LINE CHART"

                    // QUICK_5S is the authoritative 5S LINE result.
                    // Never let a NO-TRADE branch hide a valid 90%+ signal.
                    if (signal == "CALL" || signal == "PUT") {
                        nextSignal = signal
                        nextConfidence = strength.coerceAtLeast(90)
                        nextTrend = "LINE MOMENTUM"
                        signalLocked = true
                        status = quickStatus
                    } else if (quickStatus.contains("RESULT")) {
                        signalLocked = false
                        nextSignal = "NO TRADE"
                        nextConfidence = 0
                        nextTrend = "LINE MOMENTUM"
                        status = quickStatus
                    } else {
                        nextSignal = "NO TRADE"
                        nextConfidence = strength
                        nextTrend = "LINE MOMENTUM"
                        status = quickStatus
                    }
                    updateOverlay()
                }

"""
if analysis_marker not in o:
    raise SystemExit("overlay analysis marker not found")
o = o.replace(analysis_marker, quick_case + analysis_marker, 1)

# 5S QUICK LINE mode is authoritative. Ignore normal candle/status updates
# so LIVE_ANALYSIS confidence cannot overwrite the line momentum.
generic_marker = """                "PROJECTION_STARTING", "IMAGE_READER_CREATED", "VIRTUAL_DISPLAY_CREATED",
                "FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",
                "LIVE_ANALYSIS", "CANDLE_RUNNING", "CANDLE_WAITING", "WAITING_NEW_CANDLE",
                "RESULT_WAITING_CANDLE_CONFIRMATION", "ANALYSIS_ERROR", "FRAME_ERROR" -> {"""
generic_replacement = """                "PROJECTION_STARTING", "IMAGE_READER_CREATED", "VIRTUAL_DISPLAY_CREATED",
                "FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",
                "LIVE_ANALYSIS", "CANDLE_RUNNING", "CANDLE_WAITING", "WAITING_NEW_CANDLE",
                "RESULT_WAITING_CANDLE_CONFIRMATION", "ANALYSIS_ERROR", "FRAME_ERROR" -> {
                    if (quickMode) return"""
if generic_marker not in o:
    raise SystemExit("generic overlay status marker not found")
o = o.replace(generic_marker, generic_replacement, 1)

trade_marker = """                "TRADE_ENTRY" -> {
                    val signal ="""
trade_replacement = """                "TRADE_ENTRY" -> {
                    if (quickMode) return
                    val signal ="""
if trade_marker not in o:
    raise SystemExit("trade marker not found")
o = o.replace(trade_marker, trade_replacement, 1)

result_marker = """                "RESULT_READY" -> {
                    lastResult ="""
result_replacement = """                "RESULT_READY" -> {
                    if (quickMode) return
                    lastResult ="""
if result_marker not in o:
    raise SystemExit("result marker not found")
o = o.replace(result_marker, result_replacement, 1)

# Replace the overlay text function after V23, whose exact body can vary.
import re
overlay_block = re.compile(r'(?s)(private fun buildOverlayText\(\): String \{).*?(\n    private fun formatPrice)', re.MULTILINE)
replacement_body = r'''\1
        val shownConfidence = when {
            activeTrade -> activeConfidence
            signalLocked -> nextConfidence
            else -> nextConfidence
        }
        val resultText = if (recentResults.isEmpty()) "-" else {
            val wins = recentResults.count { it == "WIN" }
            "${wins}/${recentResults.size}"
        }
        return "5S QUICK\\n" +
            "CHART: LINE\\n" +
            "SIGNAL: ${if (signalLocked) nextSignal else "NO TRADE"}\\n" +
            "MOMENTUM: ${shownConfidence}%\\n" +
            "STATUS: ${if (signalLocked) "LOCKED 5 SEC" else status}\\n" +
            "RESULT: $resultText"
    }\2'''
if not overlay_block.search(o):
    raise SystemExit("buildOverlayText function not found after earlier patches")
o = overlay_block.sub(replacement_body, o, count=1)
overlay.write_text(o, encoding="utf-8")
print("Line-chart 5S demo patch applied")
