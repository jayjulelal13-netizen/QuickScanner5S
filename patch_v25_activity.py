from pathlib import Path
import re

project = Path(__file__).resolve().parent
# The workflow runs this file from the repository root, while the Android
# project itself is extracted into build_project.
projects = list(Path("build_project").rglob("settings.gradle.kts"))
if not projects:
    projects = list(Path("build_project").rglob("settings.gradle"))
if not projects:
    raise SystemExit("V25: Android project not found")
project = projects[0].parent

candle = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
if not candle.exists() or not cap.exists():
    raise SystemExit("V25: required Kotlin sources missing")

# -------------------------------------------------------------------------
# ROOT FIX 1: CandleAnalyzer must expose a real live-activity calculation.
# It must not require a completed 1M setup before returning a non-zero score.
# The running candle + recent sequence are the activity source.
# -------------------------------------------------------------------------
ca = candle.read_text()

start = ca.find("    data class LiveActivityResult(")
if start >= 0:
    end = ca.find("\n    fun ", start)
    if end < 0:
        raise SystemExit("V25: LiveActivityResult end marker missing")
    # Preserve the rest of the class but replace the old V24 helper.
    helper = r'''    data class LiveActivityResult(
        val direction: String,
        val confidence: Int,
        val bodyRatio: Double,
        val recentStrength: Double
    )

    /*
     * V25 ROOT ACTIVITY ANALYZER
     *
     * This is intentionally separate from analyzeHistory(). The normal 1M
     * analyzer is allowed to return WAITING until a completed-candle setup is
     * proven. 5S QUICK cannot use that rule because its input is a running
     * intrabar candle. This method therefore measures live activity first and
     * uses completed candles only as confluence.
     */
    fun analyzeLiveActivity(
        running: DetectedCandle,
        completed: List<DetectedCandle>
    ): LiveActivityResult {
        val range =
            (running.high - running.low).coerceAtLeast(1.0e-9)

        val bodyMove =
            running.close - running.open

        val bodyRatio =
            (abs(bodyMove) / range).coerceIn(0.0, 1.0)

        val recent =
            completed
                .filter {
                    it.open.isFinite() &&
                    it.high.isFinite() &&
                    it.low.isFinite() &&
                    it.close.isFinite()
                }
                .takeLast(8)

        val bulls =
            recent.count { it.close > it.open }

        val bears =
            recent.count { it.close < it.open }

        val recentMove =
            if (recent.size >= 2) {
                recent.last().close - recent.first().open
            } else {
                0.0
            }

        val recentRange =
            recent.sumOf {
                (it.high - it.low).coerceAtLeast(1.0e-9)
            }

        val recentStrength =
            if (recentRange > 0.0) {
                (abs(recentMove) / recentRange).coerceIn(0.0, 1.0)
            } else {
                0.0
            }

        val runningDirection =
            when {
                bodyMove > 0.0 -> "CALL"
                bodyMove < 0.0 -> "PUT"
                else -> "NO TRADE"
            }

        val recentDirection =
            when {
                recent.size >= 3 &&
                    bulls >= 3 &&
                    recentMove > 0.0 -> "CALL"

                recent.size >= 3 &&
                    bears >= 3 &&
                    recentMove < 0.0 -> "PUT"

                else -> "NO TRADE"
            }

        val direction =
            when {
                runningDirection != "NO TRADE" -> runningDirection
                recentDirection != "NO TRADE" -> recentDirection
                else -> "NO TRADE"
            }

        var score = 0

        // A measurable direction is already real activity.
        if (direction != "NO TRADE") {
            score += 15
        }

        // Current running-candle activity.
        score += when {
            bodyRatio >= 0.60 -> 30
            bodyRatio >= 0.45 -> 25
            bodyRatio >= 0.30 -> 20
            bodyRatio >= 0.20 -> 15
            bodyRatio >= 0.10 -> 10
            bodyRatio >= 0.04 -> 5
            bodyRatio > 0.0 -> 2
            else -> 0
        }

        // Recent completed-candle movement.
        score += when {
            recentStrength >= 0.30 -> 20
            recentStrength >= 0.20 -> 16
            recentStrength >= 0.12 -> 12
            recentStrength >= 0.06 -> 8
            recentStrength > 0.0 -> 4
            else -> 0
        }

        // Sequence agreement.
        if (
            direction != "NO TRADE" &&
            recentDirection == direction
        ) {
            score += 20
        }

        // When the running candle itself is flat, a clear recent sequence
        // still reports activity instead of incorrectly forcing 0%.
        if (
            direction == "NO TRADE" &&
            recentDirection != "NO TRADE"
        ) {
            score += 10
        }

        // Completed-candle analyzer is confluence only; it must never turn
        // live activity back to zero simply because its strict setup is WAIT.
        if (recent.size >= 25) {
            val base =
                try {
                    analyzeHistory(
                        recent,
                        "1M"
                    )
                } catch (_: Exception) {
                    null
                }

            if (base != null) {
                if (
                    direction == "CALL" &&
                    (
                        base.trend.uppercase().contains("BULLISH") ||
                        base.bullishScore >= base.bearishScore + 8
                    )
                ) {
                    score += 15
                } else if (
                    direction == "PUT" &&
                    (
                        base.trend.uppercase().contains("BEARISH") ||
                        base.bearishScore >= base.bullishScore + 8
                    )
                ) {
                    score += 15
                }
            }
        }

        return LiveActivityResult(
            direction = direction,
            confidence = score.coerceIn(0, 100),
            bodyRatio = bodyRatio,
            recentStrength = recentStrength
        )
    }
'''
    ca = ca[:start] + helper + ca[end:]
else:
    raise SystemExit("V25: expected V24 LiveActivityResult not found")

candle.write_text(ca)

# -------------------------------------------------------------------------
# ROOT FIX 2: CaptureService must feed the analyzer on EVERY valid frame,
# after the candle history has been refreshed. Do not depend on a changed
# visible-candle signature for the 5S engine.
# -------------------------------------------------------------------------
c = cap.read_text()

# Keep 200ms sampling.
c = re.sub(
    r'private const val FRAME_INTERVAL\s*=\s*\d+L',
    'private const val FRAME_INTERVAL = 200L',
    c,
    count=1
)

# Locate the quick engine and replace it with a single deterministic driver.
start = c.find("    private fun updateQuick5s(")
end = c.find("    private fun quickHistoricalProbability", start)
if start < 0 or end < 0:
    raise SystemExit("V25: updateQuick5s markers missing")

quick = r'''    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
        val nowBucket =
            SystemClock.elapsedRealtime() / QUICK_BUCKET_MS

        if (quickBucketId < 0L) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        val bucketChanged =
            nowBucket != quickBucketId

        if (bucketChanged) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        // IMPORTANT: CandleAnalyzer receives the latest running candle on
        // every frame. Completed candles are context only.
        val completed =
            if (candleHistory.isNotEmpty()) {
                candleHistory
                    .dropLast(1)
                    .takeLast(80)
            } else {
                emptyList()
            }

        val live =
            try {
                CandleAnalyzer.analyzeLiveActivity(
                    runningCandle,
                    completed
                )
            } catch (e: Exception) {
                Log.e(
                    TAG,
                    "V25 live activity analyzer error",
                    e
                )
                null
            }

        val range =
            (runningCandle.high - runningCandle.low)
                .coerceAtLeast(1.0e-9)

        val frameMove =
            if (
                !bucketChanged &&
                quickPrevFrameClose.isFinite() &&
                runningCandle.close.isFinite()
            ) {
                runningCandle.close -
                    quickPrevFrameClose
            } else {
                0.0
            }

        val bucketMove =
            if (
                quickBucketOpen.isFinite() &&
                runningCandle.close.isFinite()
            ) {
                runningCandle.close -
                    quickBucketOpen
            } else {
                0.0
            }

        quickPrevFrameClose =
            runningCandle.close

        quickBucketClose =
            runningCandle.close

        val frameStrength =
            (
                abs(frameMove) / range
            ).coerceIn(
                0.0,
                1.0
            )

        val bucketStrength =
            (
                abs(bucketMove) / range
            ).coerceIn(
                0.0,
                1.0
            )

        val direction =
            live?.direction ?: when {
                bucketMove > 0.0 -> "CALL"
                bucketMove < 0.0 -> "PUT"
                runningCandle.close > runningCandle.open -> "CALL"
                runningCandle.close < runningCandle.open -> "PUT"
                else -> "NO TRADE"
            }

        var score =
            live?.confidence ?: 0

        // Add live intrabucket evidence. This is only additional evidence;
        // the CandleAnalyzer activity score remains the base score.
        score += when {
            bucketStrength >= 0.25 -> 12
            bucketStrength >= 0.12 -> 8
            bucketStrength >= 0.05 -> 5
            bucketStrength > 0.0 -> 2
            else -> 0
        }

        score += when {
            frameStrength >= 0.10 -> 6
            frameStrength >= 0.04 -> 4
            frameStrength > 0.0 -> 2
            else -> 0
        }

        val confidence =
            score.coerceIn(
                0,
                100
            )

        // Hard gate: only 90%+ can become a signal.
        val strong =
            (
                direction == "CALL" ||
                direction == "PUT"
            ) &&
            confidence >= 90

        if (
            strong &&
            quickSignalDirection == "NONE"
        ) {
            quickSignal =
                direction

            quickSignalDirection =
                direction

            quickSignalEntry =
                runningCandle.close

            quickActiveUntilBucket =
                nowBucket + 1L

            quickLastSignalBucket =
                nowBucket
        }

        sendQuickStatus(
            if (strong) direction else "NO TRADE",
            confidence,
            quickHistoricalSampleCount(direction),
            if (strong)
                "5S STRONG SETUP"
            else
                "WAIT - 90% GATE"
        )
    }

'''
c = c[:start] + quick + c[end:]

# Ensure there is a driver immediately after the current running candle is
# obtained, AND another driver after history is rebuilt. The second call is
# the important one because it gives CandleAnalyzer the newest completed list.
driver = r'''        // V25: feed live activity immediately from the current detected candle.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V25 quick activity driver error", e)
            }
        }
'''
if "V25 quick activity driver error" not in c:
    anchor = """        val currentRunningCandle =
            detected.last()
"""
    if anchor not in c:
        raise SystemExit("V25: currentRunningCandle anchor missing")
    c = c.replace(anchor, anchor + "
" + driver, 1)

# Add a post-history-refresh driver. We deliberately use a unique marker and
# do not touch the normal 1M completed-candle trade logic.
post = r'''        // V25: second pass after candleHistory has been refreshed.
        // This keeps 5S activity and CandleAnalyzer confluence synchronized.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V25 post-history quick activity error", e)
            }
        }
'''
if "V25 post-history quick activity error" not in c:
    # The history is assigned with candleHistory.clear()/addAll in this codebase.
    # Insert after the last addAll that occurs before the running-candle safety
    # block. If that exact pattern is absent, use the previousRunningCandle
    # assignment as a safe post-history anchor.
    pos = c.find("        previousRunningCandle =")
    if pos < 0:
        raise SystemExit("V25: post-history anchor missing")
    c = c[:pos] + post + "
" + c[pos:]

cap.write_text(c)

# Strict 90% gate remains authoritative.
c2 = cap.read_text()
c2 = c2.replace(
    'private val MIN_CONFIDENCE_TO_QUEUE = 85',
    'private val MIN_CONFIDENCE_TO_QUEUE = 90'
)
c2 = c2.replace(
    'private const val CONFIDENCE_LEVEL = 85',
    'private const val CONFIDENCE_LEVEL = 90'
)
cap.write_text(c2)

# Verification
ca2 = candle.read_text()
cap2 = cap.read_text()
for needle in [
    "fun analyzeLiveActivity(",
    "data class LiveActivityResult"
]:
    if needle not in ca2:
        raise SystemExit("V25 VERIFY CandleAnalyzer: " + needle)
for needle in [
    "CandleAnalyzer.analyzeLiveActivity(",
    "V25 post-history quick activity error",
    "val confidence =",
    "confidence >= 90"
]:
    if needle not in cap2:
        raise SystemExit("V25 VERIFY CaptureService: " + needle)

print("V25 VERIFIED: CandleAnalyzer live activity + CaptureService dual-frame driver + strict 90% gate")
