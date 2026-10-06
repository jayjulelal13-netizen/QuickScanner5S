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

        val left = (w * 0.01f).roundToInt().coerceAtLeast(0)
        val right = (w * 0.56f).roundToInt().coerceAtMost(w - 1)
        val top = (h * 0.16f).roundToInt().coerceAtLeast(0)
        val bottom = (h * 0.70f).roundToInt().coerceAtMost(h - 1)
        if (right - left < 80 || bottom - top < 100) return null

        val perColumn = ArrayList<Float>(90)
        val startX = (right - 120).coerceAtLeast(left)
        val endX = (right - 12).coerceAtLeast(startX + 1)
        val hsv = FloatArray(3)

        for (x in startX..endX) {
            val ys = ArrayList<Int>(12)
            var y = top
            while (y <= bottom) {
                Color.colorToHSV(bitmap.getPixel(x, y), hsv)
                if (hsv[0] >= 180f && hsv[0] <= 235f &&
                    hsv[1] >= 0.22f && hsv[2] >= 0.30f) {
                    ys.add(y)
                }
                y += 2
            }
            if (ys.isNotEmpty()) {
                ys.sort()
                perColumn.add(ys[ys.size / 2].toFloat())
            }
        }

        if (perColumn.size < 12) return null
        val tail = perColumn.takeLast(minOf(30, perColumn.size)).sorted()
        return tail[tail.size / 2].toDouble()
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
        while (lineSamples.isNotEmpty() && now - lineSamples.first().first > 2500L) {
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
                    "NO TRADE", 0, 0,
                    if (win) "5S DEMO RESULT: WIN" else "5S DEMO RESULT: LOSS"
                )
                lineSignalDirection = "NONE"
                lineSignalEntryY = Double.NaN
                lineSignalUntilMs = 0L
                lineLastSignalMs = now
            } else {
                sendQuickStatus(lineSignalDirection, 0, 0, "5S SIGNAL LOCKED")
                return
            }
        }

        if (now - lineLastSignalMs < 1000L || lineSamples.size < 6) {
            sendQuickStatus("NO TRADE", 0, 0, "SCANNING LINE CHART")
            return
        }

        val first = lineSamples.first().second
        val last = lineSamples.last().second
        val delta = first - last
        val movement = kotlin.math.abs(delta)

        var up = 0
        var down = 0
        var previous = first
        for ((_, y) in lineSamples.drop(1)) {
            val d = previous - y
            if (d > 0.8) up++
            else if (d < -0.8) down++
            previous = y
        }

        val totalMoves = (up + down).coerceAtLeast(1)
        val agreement = maxOf(up, down).toDouble() / totalMoves.toDouble()

        if (movement >= 6.0 && agreement >= 0.65) {
            val direction = if (delta > 0) "CALL" else "PUT"
            val strength = (50.0 + agreement * 35.0 +
                movement.coerceAtMost(30.0) * 0.5)
                .roundToInt().coerceIn(50, 99)

            lineSignalDirection = direction
            lineSignalEntryY = priceY
            lineSignalUntilMs = now + 5000L
            lineLastSignalMs = now

            sendQuickStatus(direction, strength, 0, "5S DEMO SIGNAL • LOCK 5 SEC")
        } else {
            sendQuickStatus("NO TRADE", 0, 0, "SCANNING LINE CHART")
        }
    }

"""
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

                    if (signal == "CALL" || signal == "PUT") {
                        nextSignal = signal
                        nextConfidence = strength
                        nextTrend = "LINE MOMENTUM"
                        signalLocked = true
                        status = quickStatus
                    } else if (!signalLocked) {
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
