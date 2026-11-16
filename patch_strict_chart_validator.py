#!/usr/bin/env python3
from pathlib import Path
import os, re

project = Path(os.environ["PROJECT_DIR"])
src = project / "app/src/main/java/com/example/screener"
cap = src / "CaptureService.kt"
if not cap.exists():
    raise SystemExit("CaptureService.kt missing")

validator = r"""package com.example.screener

import android.graphics.Bitmap
import android.graphics.Color
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Conservative screen-level gate for the 5-second candle scanner.
 * A few colored UI pixels/icons are not enough: require multiple narrow,
 * separated OHLC-like bodies across the chart plot before candle analysis.
 */
object ChartScreenValidator {
    private data class Body(val x: Int, val top: Int, val bottom: Int)

    fun isLikelyCandlestickChart(bitmap: Bitmap): Boolean {
        val w = bitmap.width
        val h = bitmap.height
        if (w < 360 || h < 500) return false

        val left = (w * 0.04f).toInt()
        val right = (w * 0.84f).toInt()
        val top = (h * 0.15f).toInt()
        val bottom = (h * 0.62f).toInt()
        if (right - left < 180 || bottom - top < 180) return false

        val bodies = ArrayList<Body>()
        val step = 2
        var x = left
        while (x < right) {
            var y = top
            while (y < bottom) {
                if (isCandleColor(bitmap.getPixel(x, y))) {
                    val runTop = y
                    var runBottom = y
                    y += step
                    while (y < bottom && isCandleColor(bitmap.getPixel(x, y))) {
                        runBottom = y
                        y += step
                    }
                    val runHeight = runBottom - runTop
                    if (runHeight in 6..100) {
                        bodies.add(Body(x, runTop, runBottom))
                    }
                } else {
                    y += step
                }
            }
            x += step
        }

        if (bodies.size < 14) return false

        // Merge adjacent sampled columns belonging to the same candle body.
        val sorted = bodies.sortedBy { it.x }
        val groups = ArrayList<MutableList<Body>>()
        for (body in sorted) {
            val group = groups.lastOrNull()
            val prev = group?.lastOrNull()
            if (group != null && prev != null &&
                body.x - prev.x <= 4 &&
                abs(body.top - prev.top) <= 12 &&
                abs(body.bottom - prev.bottom) <= 12
            ) {
                group.add(body)
            } else {
                groups.add(mutableListOf(body))
            }
        }

        val candleGroups = groups.filter { group ->
            val width = (group.last().x - group.first().x + step)
            val groupTop = group.map { it.top }.minOrNull() ?: 0
            val groupBottom = group.map { it.bottom }.maxOrNull() ?: 0
            val height = groupBottom - groupTop
            width in 2..20 && height in 6..100 && width < height
        }

        if (candleGroups.size < 7) return false
        val xPositions = candleGroups.map { it.first().x }
        val spread = (xPositions.maxOrNull() ?: 0) - (xPositions.minOrNull() ?: 0)
        if (spread < (right - left) * 0.42f) return false

        // Require bodies at different price levels and at least two faint
        // horizontal grid rows spanning a substantial part of the plot.
        val bodyCenters = candleGroups.map { group ->
            ((group.map { it.top }.average() + group.map { it.bottom }.average()) / 2.0)
        }
        if (bodyCenters.maxOrNull()!! - bodyCenters.minOrNull()!! < (bottom - top) * 0.12f) {
            return false
        }

        var gridRows = 0
        var gy = top
        while (gy < bottom) {
            var neutral = 0
            var xx = left
            while (xx < right) {
                val pixel = bitmap.getPixel(xx, gy)
                val r = Color.red(pixel)
                val g = Color.green(pixel)
                val b = Color.blue(pixel)
                val maxC = max(r, max(g, b))
                val minC = min(r, min(g, b))
                if (maxC - minC <= 22 && maxC in 45..220) neutral++
                xx += 3
            }
            val sampled = ((right - left) / 3).coerceAtLeast(1)
            if (neutral >= sampled * 0.38) gridRows++
            gy += 3
        }
        return gridRows >= 2
    }

    private fun isCandleColor(pixel: Int): Boolean {
        val hsv = FloatArray(3)
        Color.colorToHSV(pixel, hsv)
        if (hsv[1] < 0.42f || hsv[2] < 0.30f) return false
        val hue = hsv[0]
        return (hue in 72f..170f) || (hue <= 18f || hue >= 342f)
    }
}
"""
(src / "ChartScreenValidator.kt").write_text(validator, encoding="utf-8")

s = cap.read_text(encoding="utf-8")
if "ChartScreenValidator.isLikelyCandlestickChart(bitmap)" not in s:
    match = re.search(r"(?m)^(\s*)val detected\s*=", s)
    if not match:
        raise SystemExit("Could not find candle detector entry point")
    indent = match.group(1)
    guard = (
        indent + "// Hard reject home screens/non-chart screens before candle extraction.\n" +
        indent + "if (quickMode && !ChartScreenValidator.isLikelyCandlestickChart(bitmap)) {\n" +
        indent + "    resetWhenChartIsMissing()\n" +
        indent + "    sendQuickStatus(\"NO TRADE\", 0, 0, \"NO CHART • WAITING FOR CANDLES\")\n" +
        indent + "    sendCandleCount(0)\n" +
        indent + "    return\n" +
        indent + "}\n"
    )
    s = s[:match.start()] + guard + s[match.start():]
cap.write_text(s, encoding="utf-8")

print("STRICT CHART SCREEN VALIDATOR installed before candle extraction")
