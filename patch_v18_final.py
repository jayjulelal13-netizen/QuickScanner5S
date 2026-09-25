import re
from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
for f in (cap, candle, ov):
    if not f.exists():
        raise SystemExit(f'missing {f}')

c = cap.read_text()
start = c.find('    private fun updateQuick5s(')
end = c.find('    private fun quickHistoricalProbability', start)
if start < 0 or end < 0:
    raise SystemExit('V18 quick function markers missing')

fn = r'''    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
        val nowBucket = android.os.SystemClock.elapsedRealtime() / QUICK_BUCKET_MS

        if (quickBucketId < 0L) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        val bucketChanged = nowBucket != quickBucketId
        if (bucketChanged) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        val range = (runningCandle.high - runningCandle.low)
            .coerceAtLeast(1.0e-9)
        val body = runningCandle.close - runningCandle.open
        val frameMove =
            if (!bucketChanged && quickPrevFrameClose.isFinite()) {
                runningCandle.close - quickPrevFrameClose
            } else 0.0
        val bucketMove = runningCandle.close - quickBucketOpen

        quickPrevFrameClose = runningCandle.close
        quickBucketClose = runningCandle.close

        val bodyRatio = (kotlin.math.abs(body) / range).coerceIn(0.0, 1.0)
        val bucketStrength =
            (kotlin.math.abs(bucketMove) / range).coerceIn(0.0, 1.0)
        val frameStrength =
            (kotlin.math.abs(frameMove) / range).coerceIn(0.0, 1.0)

        var direction = when {
            bucketMove > 0.0 -> "CALL"
            bucketMove < 0.0 -> "PUT"
            frameMove > 0.0 -> "CALL"
            frameMove < 0.0 -> "PUT"
            body > 0.0 -> "CALL"
            body < 0.0 -> "PUT"
            else -> "NO TRADE"
        }

        val completed = if (candleHistory.size > 1) {
            candleHistory.dropLast(1).takeLast(8)
        } else emptyList()

        val bulls = completed.count { it.close > it.open }
        val bears = completed.count { it.close < it.open }
        val sequenceMove =
            if (completed.size >= 2) {
                completed.last().close - completed.first().open
            } else 0.0
        val sequenceRange = completed.sumOf {
            (it.high - it.low).coerceAtLeast(1.0e-9)
        }
        val sequenceStrength =
            if (sequenceRange > 0.0) {
                (kotlin.math.abs(sequenceMove) / sequenceRange).coerceIn(0.0, 1.0)
            } else 0.0
        val sequenceDirection = when {
            bulls >= 4 && sequenceMove > 0.0 -> "CALL"
            bears >= 4 && sequenceMove < 0.0 -> "PUT"
            bulls >= 3 && sequenceMove > 0.0 -> "CALL"
            bears >= 3 && sequenceMove < 0.0 -> "PUT"
            else -> "NO TRADE"
        }

        if (direction == "NO TRADE" && sequenceDirection != "NO TRADE") {
            direction = sequenceDirection
        }

        val analysis = if (candleHistory.size >= 10) {
            try {
                CandleAnalyzer.analyzeHistory(
                    candleHistory.takeLast(MAX_HISTORY),
                    "1M"
                )
            } catch (_: Exception) {
                null
            }
        } else null

        val trend = analysis?.trend?.uppercase(java.util.Locale.US) ?: ""
        val analyzerDirection = when {
            trend.contains("BULLISH") -> "CALL"
            trend.contains("BEARISH") -> "PUT"
            (analysis?.bullishScore ?: 0) >= (analysis?.bearishScore ?: 0) + 8 -> "CALL"
            (analysis?.bearishScore ?: 0) >= (analysis?.bullishScore ?: 0) + 8 -> "PUT"
            else -> "NO TRADE"
        }

        var score = if (direction == "CALL" || direction == "PUT") 12 else 0

        score += when {
            bucketStrength >= 0.30 -> 30
            bucketStrength >= 0.20 -> 26
            bucketStrength >= 0.12 -> 22
            bucketStrength >= 0.08 -> 17
            bucketStrength >= 0.04 -> 12
            bucketStrength > 0.0 -> 5
            else -> 0
        }

        score += when {
            frameStrength >= 0.10 -> 8
            frameStrength >= 0.03 -> 5
            frameStrength > 0.0 -> 2
            else -> 0
        }

        score += when {
            bodyRatio >= 0.60 -> 20
            bodyRatio >= 0.40 -> 17
            bodyRatio >= 0.25 -> 13
            bodyRatio >= 0.15 -> 8
            bodyRatio >= 0.08 -> 4
            else -> 0
        }

        if (analyzerDirection != "NO TRADE" && analyzerDirection == direction) {
            score += 15
        }
        if (sequenceDirection != "NO TRADE" && sequenceDirection == direction) {
            score += 10
        }
        if (sequenceStrength >= 0.25) score += 5
        else if (sequenceStrength >= 0.12) score += 3

        val probability = score.coerceIn(0, 100)
        val strong =
            (direction == "CALL" || direction == "PUT") &&
            analyzerDirection == direction &&
            sequenceDirection == direction &&
            probability >= MIN_CONFIDENCE_TO_QUEUE

        if (strong && quickSignalDirection == "NONE") {
            quickSignal = direction
            quickSignalDirection = direction
            quickSignalEntry = runningCandle.close
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
        }

        sendQuickStatus(
            if (strong) direction else "NO TRADE",
            probability,
            0,
            if (strong) "5S STRONG SETUP" else "WAIT - 90% GATE"
        )
    }

'''
c = c[:start] + fn + c[end:]
cap.write_text(c)

c = cap.read_text()
if 'V18 quick activity frame error' not in c:
    anchor = '''        previousRunningCandleSignature =
            createCandleSignature(
                currentRunningCandle
            )
'''
    if anchor in c:
        inject = anchor + '''        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V18 quick activity frame error", e)
            }
        }
'''
        c = c.replace(anchor, inject, 1)
    else:
        raise SystemExit('V18 per-frame anchor missing')
cap.write_text(c)

a = candle.read_text()
a = a.replace(
    'val top = (height * TOP_RATIO).toInt().coerceIn(0, height - 240)',
    'val top = (height * 0.12f).toInt().coerceIn(0, height - 240)',
    1
)
a = a.replace(
    'val bottom = (height * BOTTOM_RATIO).toInt().coerceIn(top + 240, height)',
    'val bottom = (height * 0.72f).toInt().coerceIn(top + 240, height)',
    1
)
candle.write_text(a)

o = ov.read_text()
o = o.replace(
'''val liveConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (liveConfidence > 0) {
                            nextConfidence = liveConfidence
                        }''',
'''val liveConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (intent.hasExtra("quickProbability")) {
                            nextConfidence =
                                intent.getIntExtra("quickProbability", nextConfidence).coerceIn(0, 100)
                        } else if (liveConfidence > 0) {
                            nextConfidence = liveConfidence
                        }''',
1
)
ov.write_text(o)

cc = cap.read_text()
if 'V18 quick activity frame error' not in cc:
    raise SystemExit('V18 per-frame quick activity call missing')
if 'val probability = score.coerceIn(0, 100)' not in cc:
    raise SystemExit('V18 score missing')
if 'CandleAnalyzer.analyzeHistory' not in cc:
    raise SystemExit('V18 analyzer missing')
print('V18_FINAL_ENGINE_OK')
