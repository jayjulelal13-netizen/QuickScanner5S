from pathlib import Path

cap = Path(__file__).resolve().parent / "build_project"
matches = list(cap.rglob("CaptureService.kt"))
if not matches:
    raise SystemExit("V23: CaptureService.kt not found")
p = matches[0]
c = p.read_text()

# Keep fast frame sampling.
c = c.replace("private const val FRAME_INTERVAL = 1000L",
              "private const val FRAME_INTERVAL = 200L")

start = c.find("    private fun updateQuick5s(")
end = c.find("    private fun quickHistoricalProbability", start)
if start < 0 or end < 0:
    raise SystemExit("V23: quick engine markers missing")

quick = r'''    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
        val nowBucket = SystemClock.elapsedRealtime() / QUICK_BUCKET_MS

        if (quickBucketId < 0L) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
            sendQuickStatus("NO TRADE", 0, 0, "5S WARMING")
            return
        }

        val bucketChanged = nowBucket != quickBucketId
        if (bucketChanged) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        val candleRange =
            (runningCandle.high - runningCandle.low).coerceAtLeast(1.0e-9)

        val frameMove =
            if (!bucketChanged &&
                quickPrevFrameClose.isFinite() &&
                runningCandle.close.isFinite()
            ) runningCandle.close - quickPrevFrameClose else 0.0

        val bucketMove =
            if (quickBucketOpen.isFinite() && runningCandle.close.isFinite())
                runningCandle.close - quickBucketOpen
            else 0.0

        quickPrevFrameClose = runningCandle.close
        quickBucketClose = runningCandle.close

        val bodyMove = runningCandle.close - runningCandle.open
        val bodyRatio =
            (abs(bodyMove) / candleRange).coerceIn(0.0, 1.0)

        val bucketStrength =
            (abs(bucketMove) / candleRange).coerceIn(0.0, 1.0)

        val frameStrength =
            (abs(frameMove) / candleRange).coerceIn(0.0, 1.0)

        val completed =
            if (candleHistory.size > 1)
                candleHistory.dropLast(1).takeLast(8)
            else emptyList()

        val bulls = completed.count { it.close > it.open }
        val bears = completed.count { it.close < it.open }

        val recentMove =
            if (completed.size >= 2)
                completed.last().close - completed.first().open
            else 0.0

        val recentRange =
            completed.sumOf {
                (it.high - it.low).coerceAtLeast(1.0e-9)
            }

        val recentStrength =
            if (recentRange > 0.0)
                (abs(recentMove) / recentRange).coerceIn(0.0, 1.0)
            else 0.0

        val recentDirection = when {
            bulls >= 5 && recentMove > 0.0 -> "CALL"
            bears >= 5 && recentMove < 0.0 -> "PUT"
            bulls >= 4 && bulls > bears && recentMove > 0.0 -> "CALL"
            bears >= 4 && bears > bulls && recentMove < 0.0 -> "PUT"
            else -> "NO TRADE"
        }

        val analysis =
            if (candleHistory.size >= 5) {
                try {
                    CandleAnalyzer.analyzeHistory(
                        candleHistory.takeLast(MAX_HISTORY),
                        "1M"
                    )
                } catch (_: Exception) {
                    null
                }
            } else null

        val analyzerDirection = when {
            analysis != null &&
                (
                    analysis.trend.uppercase(Locale.US).contains("BULLISH") ||
                    analysis.bullishScore >= analysis.bearishScore + 8
                ) -> "CALL"

            analysis != null &&
                (
                    analysis.trend.uppercase(Locale.US).contains("BEARISH") ||
                    analysis.bearishScore >= analysis.bullishScore + 8
                ) -> "PUT"

            else -> "NO TRADE"
        }

        val activityDirection = when {
            bucketMove > 0.0 -> "CALL"
            bucketMove < 0.0 -> "PUT"
            frameMove > 0.0 -> "CALL"
            frameMove < 0.0 -> "PUT"
            bodyMove > 0.0 -> "CALL"
            bodyMove < 0.0 -> "PUT"
            recentDirection != "NO TRADE" -> recentDirection
            analyzerDirection != "NO TRADE" -> analyzerDirection
            else -> "NO TRADE"
        }

        // V23 measured confidence:
        // activity + candle body + recent completed-candle direction +
        // CandleAnalyzer agreement. No historical sample gate and no
        // artificial fallback value.
        var score = 0

        if (activityDirection == "CALL" || activityDirection == "PUT") {
            score += 20
        }

        score += when {
            bodyRatio >= 0.70 -> 25
            bodyRatio >= 0.50 -> 22
            bodyRatio >= 0.35 -> 18
            bodyRatio >= 0.20 -> 13
            bodyRatio >= 0.10 -> 7
            bodyRatio > 0.0 -> 3
            else -> 0
        }

        score += when {
            bucketStrength >= 0.35 -> 20
            bucketStrength >= 0.25 -> 17
            bucketStrength >= 0.15 -> 14
            bucketStrength >= 0.08 -> 10
            bucketStrength >= 0.03 -> 5
            bucketStrength > 0.0 -> 2
            else -> 0
        }

        score += when {
            frameStrength >= 0.15 -> 5
            frameStrength >= 0.05 -> 3
            frameStrength > 0.0 -> 1
            else -> 0
        }

        if (recentDirection == activityDirection &&
            activityDirection != "NO TRADE") {
            score += 15
        }

        if (analyzerDirection == activityDirection &&
            activityDirection != "NO TRADE") {
            score += 10
        }

        if (recentStrength >= 0.20) score += 5

        val confidence = score.coerceIn(0, 100)

        val strong =
            (activityDirection == "CALL" || activityDirection == "PUT") &&
            confidence >= 90

        if (strong && quickSignalDirection == "NONE") {
            quickSignal = activityDirection
            quickSignalDirection = activityDirection
            quickSignalEntry = runningCandle.close
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
        }

        sendQuickStatus(
            if (strong) activityDirection else "NO TRADE",
            confidence,
            quickHistoricalSampleCount(activityDirection),
            if (strong) "5S STRONG SETUP" else "WAIT - 90% GATE"
        )
    }

'''
c = c[:start] + quick + c[end:]

# Make sure QUICK is fed before normal 1M guards, exactly once.
anchor = '''        val currentRunningCandle =
            detected.last()
'''
if anchor not in c:
    raise SystemExit("V23: running candle anchor missing")

driver_marker = "V23 quick activity feed"
if driver_marker not in c:
    driver = '''        val currentRunningCandle =
            detected.last()

        // V23: feed the 5S activity analyzer on every detected frame,
        // before any normal 1M lifecycle/return guard.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V23 quick activity feed", e)
            }
        }
'''
    c = c.replace(anchor, driver, 1)

# Remove duplicate older live drivers, but never remove the V23 driver.
for msg in [
    "V22 quick activity error",
    "V21 quick activity error",
    "V20 quick activity frame error",
    "V19 quick activity frame error",
    "V19 quick activity frame error"
]:
    block = '''        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "''' + msg + '''", e)
            }
        }

'''
    c = c.replace(block, "")

p.write_text(c)

# Patch CandleAnalyzer with an explicit activity majority helper if absent.
ca = p.parent / "CandleAnalyzer.kt"
if not ca.exists():
    raise SystemExit("V23: CandleAnalyzer.kt not found")
a = ca.read_text()

if "fun recentActivityDirection(" not in a:
    helper = r'''
    fun recentActivityDirection(
        candles: List<DetectedCandle>
    ): String {
        if (candles.size < 4) return "NONE"
        val recent = candles.takeLast(8)
        val bulls = recent.count { it.close > it.open }
        val bears = recent.count { it.close < it.open }
        val move = recent.last().close - recent.first().open

        return when {
            bulls >= 5 && move > 0.0 -> "CALL"
            bears >= 5 && move < 0.0 -> "PUT"
            bulls >= 4 && bulls > bears && move > 0.0 -> "CALL"
            bears >= 4 && bears > bulls && move < 0.0 -> "PUT"
            else -> "NONE"
        }
    }

'''
    idx = a.rfind("
}")
    if idx < 0:
        raise SystemExit("V23: CandleAnalyzer class end missing")
    a = a[:idx] + "
" + helper + a[idx:]
    ca.write_text(a)

# Compile-time/source sanity.
for needle in [
    "private const val FRAME_INTERVAL = 200L",
    "V23 quick activity feed",
    "val confidence = score.coerceIn(0, 100)",
    "confidence >= 90",
    "CandleAnalyzer.analyzeHistory"
]:
    if needle not in p.read_text():
        raise SystemExit("V23 VERIFY FAIL: " + needle)

print("V23 VERIFIED: live activity candle + CandleAnalyzer confluence + strict 90% gate")
