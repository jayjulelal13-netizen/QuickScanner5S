#!/usr/bin/env python3
import os
from pathlib import Path

project = Path(os.environ["PROJECT_DIR"])
target = project / "app/src/main/java/com/example/screener/CaptureService.kt"
source = target.read_text(encoding="utf-8")

anchor = "    private var quickBucketId = -1L\n"
state = """    private data class QuickPressureCandle(val bucket: Long, val open: Double, var high: Double, var low: Double, var close: Double)
    private var quickPressureCandle: QuickPressureCandle? = null
    private val quickPressureHistory = mutableListOf<QuickPressureCandle>()

"""
if "private data class QuickPressureCandle" not in source:
    if anchor not in source: raise SystemExit("Quick state anchor not found")
    source = source.replace(anchor, state + anchor, 1)
source = source.replace("        quickBucketId = -1L\n",
    "        quickBucketId = -1L\n        quickPressureCandle = null\n        quickPressureHistory.clear()\n")

start_marker = "    private fun updateQuick5s(\n"
end_marker = "    private fun quickHistoricalProbability(\n"
start = source.find(start_marker)
end = source.find(end_marker, start + len(start_marker))
if start < 0 or end < 0: raise SystemExit("Quick engine function boundaries not found")

replacement = r'''    private fun updateQuick5s(runningCandle: CandleAnalyzer.DetectedCandle) {
        val nowBucket = System.currentTimeMillis() / QUICK_BUCKET_MS
        val price = runningCandle.close
        if (!price.isFinite()) {
            sendQuickStatus("NO TRADE", 0, 0, "WAIT - INVALID PRICE")
            return
        }

        if (quickBucketId < 0L || quickPressureCandle == null) {
            quickBucketId = nowBucket
            quickLastClose = price
            quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)
            return
        }

        val building = quickPressureCandle
        if (nowBucket == quickBucketId && building != null) {
            building.high = max(building.high, price)
            building.low = min(building.low, price)
            building.close = price
            return
        }

        // Missing capture buckets invalidate the setup; never synthesize missing data.
        if (nowBucket != quickBucketId + 1L || building == null) {
            quickBucketId = nowBucket
            quickLastClose = price
            quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)
            quickShadowDirection = "NONE"
            quickShadowEntry = Double.NaN
            quickShadowUntilBucket = -1L
            quickSignalDirection = "NONE"
            quickSignal = "NO TRADE"
            quickSignalEntry = Double.NaN
            quickActiveUntilBucket = -1L
            sendQuickStatus("NO TRADE", 0, 0, "WAIT - MISSED 5S DATA")
            return
        }

        val closed = building
        quickPressureHistory.add(closed)
        while (quickPressureHistory.size > 120) quickPressureHistory.removeAt(0)

        // Score a shadow setup only when the next bucket's first real price arrives.
        if ((quickShadowDirection == "CALL" || quickShadowDirection == "PUT") &&
            quickShadowUntilBucket >= 0L && nowBucket >= quickShadowUntilBucket) {
            val won = if (quickShadowDirection == "CALL") price > quickShadowEntry else price < quickShadowEntry
            val wk = if (quickShadowDirection == "CALL") "shadow_call_wins" else "shadow_put_wins"
            val lk = if (quickShadowDirection == "CALL") "shadow_call_losses" else "shadow_put_losses"
            val wins = probabilityPrefs.getInt(wk, 0) + if (won) 1 else 0
            val losses = probabilityPrefs.getInt(lk, 0) + if (won) 0 else 1
            probabilityPrefs.edit().putInt(wk, wins).putInt(lk, losses).apply()
            quickShadowDirection = "NONE"
            quickShadowEntry = Double.NaN
            quickShadowUntilBucket = -1L
        }

        if ((quickSignalDirection == "CALL" || quickSignalDirection == "PUT") &&
            quickActiveUntilBucket >= 0L && nowBucket >= quickActiveUntilBucket) {
            val won = if (quickSignalDirection == "CALL") price > quickSignalEntry else price < quickSignalEntry
            if (won) quickWins++ else quickLosses++
            probabilityPrefs.edit().putInt("quick_wins", quickWins).putInt("quick_losses", quickLosses).apply()
            quickSignalDirection = "NONE"
            quickSignal = "NO TRADE"
            quickSignalEntry = Double.NaN
            quickActiveUntilBucket = -1L
        }

        // Start the next bucket before evaluating the completed one.
        quickBucketId = nowBucket
        quickLastClose = price
        quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)

        val oneMinute = candleHistory.takeLast(MAX_HISTORY)
        if (oneMinute.size < 30 || quickPressureHistory.size < 3) {
            sendQuickStatus("NO TRADE", 0, quickPressureHistory.size, "WAIT - BUILDING 1M/5S HISTORY")
            return
        }

        val trend1m = quickTrend(oneMinute.map { it.close }, 5, 13)
        // Approximate 5M structure from five-candle groups on the 1M chart.
        // This is not an independent broker-provided 5M candle feed.
        val fiveMinuteCloses = oneMinute.takeLast(60).chunked(5)
            .filter { it.size == 5 }.map { it.last().close }
        val trend5m = quickTrend(fiveMinuteCloses, 3, 6)

        val range = (closed.high - closed.low).coerceAtLeast(1.0e-12)
        val bodyRatio = (abs(closed.close - closed.open) / range).coerceIn(0.0, 1.0)
        val upper = (closed.high - max(closed.open, closed.close)).coerceAtLeast(0.0) / range
        val lower = (min(closed.open, closed.close) - closed.low).coerceAtLeast(0.0) / range
        val closeLocation = ((closed.close - closed.low) / range).coerceIn(0.0, 1.0)
        val micro = quickPressureHistory.takeLast(3)
        val momentum = micro.last().close - micro.first().open
        val momentumUp = momentum > 0.0
        val momentumDown = momentum < 0.0

        // Body + close location + both wick tips + three-candle momentum.
        // This is price-action pressure, not order-book buying/selling volume.
        val bullPressure = (bodyRatio * 0.40 + closeLocation * 0.30 + lower * 0.20 +
            (if (momentumUp) 0.10 else 0.0) - upper * 0.20).coerceIn(0.0, 1.0)
        val bearPressure = (bodyRatio * 0.40 + (1.0 - closeLocation) * 0.30 + upper * 0.20 +
            (if (momentumDown) 0.10 else 0.0) - lower * 0.20).coerceIn(0.0, 1.0)

        val bull = closed.close > closed.open && bodyRatio >= 0.35 &&
            closeLocation >= 0.62 && upper <= 0.35 && momentumUp && bullPressure >= 0.58
        val bear = closed.close < closed.open && bodyRatio >= 0.35 &&
            closeLocation <= 0.38 && lower <= 0.35 && momentumDown && bearPressure >= 0.58

        val direction = when {
            trend5m == "BULLISH" && trend1m == "BULLISH" && bull -> "CALL"
            trend5m == "BEARISH" && trend1m == "BEARISH" && bear -> "PUT"
            else -> "NO TRADE"
        }

        val setupKey = "$trend5m:$trend1m:$direction:" + closed.bucket
        val cooldown = quickLastSignalBucket >= 0L &&
            nowBucket - quickLastSignalBucket < QUICK_COOLDOWN_BUCKETS
        val fresh = setupKey != quickLastSetupKey ||
            nowBucket - quickLastSetupBucket >= QUICK_COOLDOWN_BUCKETS

        if ((direction == "CALL" || direction == "PUT") && fresh && quickShadowDirection == "NONE") {
            quickShadowDirection = direction
            quickShadowEntry = price
            quickShadowUntilBucket = nowBucket + 1L
            quickLastSetupKey = setupKey
            quickLastSetupBucket = nowBucket
        }

        val probability = if (direction == "CALL" || direction == "PUT") quickHistoricalProbability(direction) else null
        val samples = if (direction == "CALL" || direction == "PUT") quickHistoricalSampleCount(direction) else 0
        val canSignal = (direction == "CALL" || direction == "PUT") &&
            probability != null && probability >= MIN_EMPIRICAL_PROBABILITY &&
            samples >= MIN_EMPIRICAL_SAMPLES && !cooldown && fresh &&
            quickSignalDirection == "NONE"

        if (canSignal) {
            quickSignal = direction
            quickSignalDirection = direction
            quickSignalEntry = price
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
            quickLastSetupKey = setupKey
            quickLastSetupBucket = nowBucket
            sendQuickStatus(direction, probability ?: 0, samples, "5S SIGNAL - DEMO TEST ONLY")
        } else {
            val why = when {
                trend5m == "WAITING" || trend1m == "WAITING" -> "WAIT - TREND HISTORY"
                trend5m != trend1m -> "NO TRADE - TREND CONFLICT"
                direction == "NO TRADE" -> "NO TRADE - WEAK 5S PRESSURE"
                probability == null || samples < MIN_EMPIRICAL_SAMPLES -> "WAIT - EMPIRICAL SAMPLES ($samples/$MIN_EMPIRICAL_SAMPLES)"
                cooldown || !fresh -> "WAIT - FRESH SETUP"
                else -> "NO TRADE - 90% GATE"
            }
            sendQuickStatus("NO TRADE", probability ?: 0, samples, why)
        }
    }

    private fun quickTrend(values: List<Double>, fastPeriod: Int, slowPeriod: Int): String {
        if (values.size < maxOf(slowPeriod + 2, 6)) return "WAITING"
        val fast = quickEma(values, fastPeriod)
        val slow = quickEma(values, slowPeriod)
        val recent = values.takeLast(3)
        return when {
            fast > slow && recent.last() > recent.first() -> "BULLISH"
            fast < slow && recent.last() < recent.first() -> "BEARISH"
            else -> "SIDEWAYS"
        }
    }

    private fun quickEma(values: List<Double>, period: Int): Double {
        if (values.isEmpty()) return Double.NaN
        val alpha = 2.0 / (period + 1.0)
        var value = values.first()
        for (i in 1 until values.size) value = alpha * values[i] + (1.0 - alpha) * value
        return value
    }

'''
source = source[:start] + replacement + source[end:]
target.write_text(source, encoding="utf-8")
print(f"Patched {target}")
