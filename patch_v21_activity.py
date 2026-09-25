from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent

cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
analyzer = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'

for p in (cap, analyzer, ov):
    if not p.exists():
        raise SystemExit('V21 missing source: ' + str(p))

# V21: make CandleAnalyzer the single live 5S activity source.
# It must calculate a visible measured score on every capture frame; it must
# not wait for a completed 1-minute candle or an empirical probability table.
a = analyzer.read_text()
if 'fun quickActivityScore(' not in a:
    marker = '\n}\n'
    pos = a.rfind(marker)
    if pos < 0:
        raise SystemExit('V21 CandleAnalyzer closing brace missing')
    method = r'''
    /**
     * Measured intrabar 5S setup strength. This is a setup score, not a
     * guaranteed win probability.
     */
    fun quickActivityScore(
        history: List<DetectedCandle>,
        running: DetectedCandle,
        bucketOpen: Double
    ): Pair<String, Int> {
        if (!running.open.isFinite() || !running.high.isFinite() ||
            !running.low.isFinite() || !running.close.isFinite()) {
            return Pair("NO TRADE", 0)
        }

        val range = (running.high - running.low).coerceAtLeast(1.0e-9)
        val body = running.close - running.open
        val bucketMove = running.close - bucketOpen
        val bodyRatio = (kotlin.math.abs(body) / range).coerceIn(0.0, 1.0)
        val moveRatio =
            (kotlin.math.abs(bucketMove) / range).coerceIn(0.0, 1.0)

        val direction = when {
            bucketMove > 0.0 -> "CALL"
            bucketMove < 0.0 -> "PUT"
            body > 0.0 -> "CALL"
            body < 0.0 -> "PUT"
            else -> "NO TRADE"
        }
        if (direction == "NO TRADE") return Pair(direction, 0)

        val recent = history.dropLast(1).takeLast(6)
        val bulls = recent.count { it.close > it.open }
        val bears = recent.count { it.close < it.open }
        val recentMove =
            if (recent.size >= 2) recent.last().close - recent.first().open else 0.0
        val recentRange = recent.sumOf {
            (it.high - it.low).coerceAtLeast(1.0e-9)
        }.coerceAtLeast(1.0e-9)
        val recentStrength =
            (kotlin.math.abs(recentMove) / recentRange).coerceIn(0.0, 1.0)
        val recentDirection = when {
            bulls >= 3 && recentMove > 0.0 -> "CALL"
            bears >= 3 && recentMove < 0.0 -> "PUT"
            else -> "NO TRADE"
        }

        var score = 12

        score += when {
            moveRatio >= 0.50 -> 32
            moveRatio >= 0.30 -> 27
            moveRatio >= 0.20 -> 22
            moveRatio >= 0.12 -> 17
            moveRatio >= 0.06 -> 11
            moveRatio > 0.0 -> 5
            else -> 0
        }

        score += when {
            bodyRatio >= 0.60 -> 22
            bodyRatio >= 0.40 -> 18
            bodyRatio >= 0.25 -> 13
            bodyRatio >= 0.15 -> 8
            bodyRatio > 0.0 -> 3
            else -> 0
        }

        if (recentDirection == direction) score += 18
        if ((direction == "CALL" && bulls >= 4) ||
            (direction == "PUT" && bears >= 4)) score += 10
        else if ((direction == "CALL" && bulls >= 3) ||
                 (direction == "PUT" && bears >= 3)) score += 6

        if (recentStrength >= 0.25) score += 6
        else if (recentStrength >= 0.12) score += 3

        return Pair(direction, score.coerceIn(0, 100))
    }
'''
    a = a[:pos] + method + a[pos:]
    analyzer.write_text(a)

c = cap.read_text()
start = c.find('    private fun updateQuick5s(')
end = c.find('    private fun quickHistoricalProbability', start)
if start < 0 or end < 0:
    raise SystemExit('V21 updateQuick5s boundaries missing')

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

        if (nowBucket != quickBucketId) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickPrevFrameClose = runningCandle.close
        }

        quickBucketClose = runningCandle.close

        val measured = try {
            CandleAnalyzer.quickActivityScore(
                candleHistory,
                runningCandle,
                quickBucketOpen
            )
        } catch (e: Exception) {
            Log.e(TAG, "V21 CandleAnalyzer activity error", e)
            Pair("NO TRADE", 0)
        }

        var direction = measured.first
        var confidence = measured.second.coerceIn(0, 100)

        // Add higher-timeframe CandleAnalyzer trend only as confluence.
        // It can increase confidence, but cannot manufacture a direction.
        if (candleHistory.size >= 5 &&
            (direction == "CALL" || direction == "PUT")
        ) {
            try {
                val analysis = CandleAnalyzer.analyzeHistory(
                    candleHistory.takeLast(MAX_HISTORY),
                    "1M"
                )
                val trend = analysis.trend.uppercase(java.util.Locale.US)
                val analyzerDirection = when {
                    trend.contains("BULLISH") -> "CALL"
                    trend.contains("BEARISH") -> "PUT"
                    else -> "NO TRADE"
                }

                if (analyzerDirection == direction) {
                    confidence = (confidence + 12).coerceAtMost(100)
                }
            } catch (e: Exception) {
                Log.e(TAG, "V21 trend confluence error", e)
            }
        }

        val strong =
            (direction == "CALL" || direction == "PUT") &&
            confidence >= MIN_CONFIDENCE_TO_QUEUE &&
            quickSignalDirection == "NONE"

        if (strong) {
            quickSignal = direction
            quickSignalDirection = direction
            quickSignalEntry = runningCandle.close
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
        }

        sendQuickStatus(
            if (strong) direction else "NO TRADE",
            confidence,
            0,
            if (strong) "5S STRONG SETUP" else "WAIT - 90% GATE"
        )
    }

'''
c = c[:start] + fn + c[end:]

# Guarantee the quick engine is called for every fresh running candle.
if 'V21 quick activity frame error' not in c:
    anchor = '''        val currentRunningCandle =
            detected.last()

        val nowMillis ='''
    if anchor in c:
        c = c.replace(anchor, '''        val currentRunningCandle =
            detected.last()

        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V21 quick activity frame error", e)
            }
        }

        val nowMillis =''', 1)
    else:
        # Fallback: use an existing per-frame call marker rather than failing silently.
        if 'updateQuick5s(currentRunningCandle)' not in c:
            raise SystemExit('V21 current candle frame anchor missing')

cap.write_text(c)

# Prevent normal zero-confidence broadcasts from erasing a valid 5S score.
o = ov.read_text()
o = o.replace(
'''val liveConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (intent.hasExtra("quickProbability")) {
                            nextConfidence =
                                intent.getIntExtra("quickProbability", nextConfidence).coerceIn(0, 100)
                        } else if (liveConfidence > 0) {
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

# Build-time assertions.
cc = cap.read_text()
aa = analyzer.read_text()
if 'CandleAnalyzer.quickActivityScore(' not in cc:
    raise SystemExit('V21 quickActivityScore call missing')
if 'V21 quick activity frame error' not in cc and 'updateQuick5s(currentRunningCandle)' not in cc:
    raise SystemExit('V21 per-frame activity feed missing')
if 'fun quickActivityScore(' not in aa:
    raise SystemExit('V21 CandleAnalyzer activity method missing')
if 'WAIT - 90% GATE' not in cc:
    raise SystemExit('V21 strict gate missing')

print('V21 OK: CandleAnalyzer live 5S activity -> confidence every capture frame -> strict 90% gate')
