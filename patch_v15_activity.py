import re
from pathlib import Path

projects = list(Path("build_project").rglob("settings.gradle.kts"))
if not projects:
    projects = list(Path("build_project").rglob("settings.gradle"))
if not projects:
    raise SystemExit("Android project not found")

project = projects[0].parent
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
analyzer = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"

if not cap.exists() or not analyzer.exists():
    raise SystemExit("required source missing")

# Ensure the analyzer has a dedicated live 5S activity score.
a = analyzer.read_text()
if "fun quickActivityScore(" not in a:
    marker = "\n}\n"
    pos = a.rfind(marker)
    if pos < 0:
        raise SystemExit("CandleAnalyzer closing brace not found")
    method = r'''
    /**
     * Live 5S setup-strength score. This is a measured setup score,
     * not a guaranteed win probability.
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
        val move = running.close - bucketOpen
        val bodyRatio =
            (abs(running.close - running.open) / range).coerceIn(0.0, 1.0)
        val moveRatio =
            (abs(move) / range).coerceIn(0.0, 1.0)

        val direction = when {
            move > 0.0 -> "CALL"
            move < 0.0 -> "PUT"
            running.close > running.open -> "CALL"
            running.close < running.open -> "PUT"
            else -> "NO TRADE"
        }
        if (direction == "NO TRADE") return Pair(direction, 0)

        val recent = history.takeLast(6)
        val bull = recent.count { it.close > it.open }
        val bear = recent.count { it.close < it.open }
        val agreement = if (direction == "CALL") bull else bear

        val recentRange = recent.sumOf {
            (it.high - it.low).coerceAtLeast(0.0)
        }.coerceAtLeast(1.0e-9)
        val recentMove =
            if (recent.size >= 2) recent.last().close - recent.first().open else 0.0
        val recentStrength = abs(recentMove) / recentRange
        val recentAgrees =
            if (direction == "CALL") recentMove > 0.0 else recentMove < 0.0

        var score = 15

        score += when {
            moveRatio >= 0.60 -> 40
            moveRatio >= 0.40 -> 34
            moveRatio >= 0.25 -> 26
            moveRatio >= 0.15 -> 18
            moveRatio >= 0.08 -> 10
            moveRatio >= 0.02 -> 5
            else -> 0
        }

        score += when {
            bodyRatio >= 0.70 -> 25
            bodyRatio >= 0.55 -> 20
            bodyRatio >= 0.40 -> 14
            bodyRatio >= 0.25 -> 9
            bodyRatio >= 0.15 -> 5
            bodyRatio > 0.0 -> 2
            else -> 0
        }

        if (agreement >= 5) score += 20
        else if (agreement >= 4) score += 15
        else if (agreement >= 3) score += 8

        if (recentAgrees) score += 5
        if (recentStrength >= 0.20) score += 5
        else if (recentStrength >= 0.12) score += 3

        return Pair(direction, score.coerceIn(0, 100))
    }
'''
    a = a[:pos] + method + a[pos:]
    analyzer.write_text(a)

s = cap.read_text()

# Make sure bucket state exists.
if "private var quickBucketOpen" not in s:
    anchor = "private var quickLastClose = Double.NaN"
    if anchor not in s:
        raise SystemExit("quick state anchor missing")
    s = s.replace(anchor, anchor + """
    private var quickBucketOpen = Double.NaN
    private var quickBucketClose = Double.NaN
    private var quickLastSampleBucket = -1L""", 1)

start = s.find("    private fun updateQuick5s(")
end = s.find("    private fun quickHistoricalProbability", start)
if start < 0 or end < 0:
    raise SystemExit("updateQuick5s boundaries missing")

new_fn = r'''    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
        val nowBucket = SystemClock.elapsedRealtime() / 5000L

        if (quickBucketId < 0L) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickLastClose = runningCandle.close
            sendQuickStatus("NO TRADE", 0, 0, "5S WARMING")
            return
        }

        if (nowBucket != quickBucketId) {
            quickBucketId = nowBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
            quickLastClose = runningCandle.close
        } else {
            quickBucketClose = runningCandle.close
        }

        val analyzed =
            try {
                CandleAnalyzer.quickActivityScore(
                    candleHistory,
                    runningCandle,
                    quickBucketOpen
                )
            } catch (e: Exception) {
                Log.e(TAG, "5S CandleAnalyzer activity error", e)
                Pair("NO TRADE", 0)
            }

        val direction = analyzed.first
        val confidence = analyzed.second.coerceIn(0, 100)

        val tradeReady =
            (direction == "CALL" || direction == "PUT") &&
                confidence >= MIN_CONFIDENCE_TO_QUEUE &&
                quickSignalDirection == "NONE"

        if (tradeReady) {
            quickSignal = direction
            quickSignalDirection = direction
            quickSignalEntry = runningCandle.close
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
        }

        sendQuickStatus(
            if (tradeReady) direction else "NO TRADE",
            confidence,
            0,
            if (confidence >= MIN_CONFIDENCE_TO_QUEUE) {
                "5S STRONG SETUP"
            } else {
                "WAIT - 90% GATE"
            }
        )
    }

'''
s = s[:start] + new_fn + s[end:]

# Dedicated 5S confidence is sent on every analyzer update.
send = s.find("private fun sendQuickStatus")
if send >= 0:
    tail = s[send:]
    if 'putExtra("quickProbability", probability)' in tail and 'putExtra("confidence", probability)' not in tail:
        tail = tail.replace(
            'putExtra("quickProbability", probability)',
            'putExtra("quickProbability", probability)\n            putExtra("confidence", probability)',
            1
        )
        s = s[:send] + tail

cap.write_text(s)

# Final checks.
assert "CandleAnalyzer.quickActivityScore(" in s
assert "updateQuick5s(currentRunningCandle)" in s
assert "WAIT - 90% GATE" in s
assert "fun quickActivityScore(" in analyzer.read_text()
print("V15 FINAL OK: every capture frame -> CandleAnalyzer quick activity -> live confidence -> strict 90% gate")
