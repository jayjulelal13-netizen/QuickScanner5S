package com.example.screener

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
        val right = (w * 0.80f).roundToInt().coerceAtMost(w - 1)
        val top = (h * 0.17f).roundToInt().coerceAtLeast(0)
        val bottom = (h * 0.64f).roundToInt().coerceAtMost(h - 1)
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
