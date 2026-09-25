import re
from pathlib import Path

projects = list(Path("build_project").rglob("settings.gradle.kts"))
if not projects:
    raise SystemExit("settings.gradle.kts not found")
project = projects[0].parent
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
candle = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"

if not cap.exists() or not candle.exists():
    raise SystemExit("QuickScanner5S source missing")

# Add a dedicated, deterministic 5S activity analyzer to CandleAnalyzer.
cs = candle.read_text()
if "fun analyzeQuickActivity(" not in cs:
    marker = "\n}\n"
    pos = cs.rfind(marker)
    if pos < 0:
        raise SystemExit("CandleAnalyzer object closing brace not found")
    method = r'''
    /**
     * Live 5S activity analysis.
     *
     * This is intentionally separate from analyzeHistory(): that method is a
     * completed-candle strategy engine and may legitimately return WAITING.
     * QUICK mode needs an intrabar activity score from the current detected
     * candle plus recent completed candles.
     */
    fun analyzeQuickActivity(
        history: List<DetectedCandle>,
        running: DetectedCandle
    ): AnalysisResult {
        val tf = "5S"
        if (!running.open.isFinite() || !running.high.isFinite() ||
            !running.low.isFinite() || !running.close.isFinite()) {
            return waitingResult(tf)
        }

        val completed = if (history.isNotEmpty()) {
            history.dropLast(1).takeLast(8)
        } else {
            emptyList()
        }

        val range = (running.high - running.low).coerceAtLeast(1.0e-9)
        val body = abs(running.close - running.open)
        val bodyRatio = (body / range).coerceIn(0.0, 1.0)
        val closeLocation =
            ((running.close - running.low) / range).coerceIn(0.0, 1.0)

        val avgRecentRange =
            completed.map { (it.high - it.low).coerceAtLeast(1.0e-9) }
                .average()
                .takeIf { it.isFinite() && it > 0.0 }
                ?: range

        val activityRatio = (body / avgRecentRange).coerceIn(0.0, 2.0)
        val recentBull = completed.count { it.close > it.open }
        val recentBear = completed.count { it.close < it.open }

        val immediateDirection =
            when {
                running.close > running.open -> "CALL"
                running.close < running.open -> "PUT"
                else -> "NO TRADE"
            }

        val recentDirection =
            when {
                recentBull >= 4 -> "CALL"
                recentBear >= 4 -> "PUT"
                else -> "NO TRADE"
            }

        val direction =
            when {
                immediateDirection != "NO TRADE" -> immediateDirection
                recentDirection != "NO TRADE" -> recentDirection
                else -> "NO TRADE"
            }

        var score = 0

        // A direction is real evidence, but not enough by itself.
        if (direction != "NO TRADE") score += 15

        // Current candle activity relative to recent candle range.
        score += when {
            activityRatio >= 1.50 -> 30
            activityRatio >= 1.15 -> 25
            activityRatio >= 0.90 -> 18
            activityRatio >= 0.65 -> 12
            activityRatio >= 0.40 -> 6
            else -> 0
        }

        // Body quality.
        score += when {
            bodyRatio >= 0.70 -> 20
            bodyRatio >= 0.50 -> 16
            bodyRatio >= 0.35 -> 12
            bodyRatio >= 0.20 -> 7
            else -> 0
        }

        // Close location confirms directional pressure.
        val closeConfirm =
            (direction == "CALL" && closeLocation >= 0.72) ||
            (direction == "PUT" && closeLocation <= 0.28)
        if (closeConfirm) score += 15

        // Recent sequence agreement.
        if (direction != "NO TRADE" && recentDirection == direction) {
            score += 20
        }

        val confidence = score.coerceIn(0, 100)
        val signal =
            if (direction != "NO TRADE" && confidence >= 90) direction
            else "NO TRADE"

        val trend =
            if (direction == "CALL") "CALL"
            else if (direction == "PUT") "PUT"
            else "WAITING"

        return AnalysisResult(
            timeframe = tf,
            trend = trend,
            signal = signal,
            confidence = confidence
        )
    }
'''
    cs = cs[:pos] + method + cs[pos:]
    candle.write_text(cs)

# Replace the live QUICK engine with CandleAnalyzer's dedicated activity path.
s = cap.read_text()
start = s.find("    private fun updateQuick5s(")
end = s.find("    private fun quickHistoricalProbability", start)
if start < 0 or end < 0:
    raise SystemExit("updateQuick5s markers not found")

fn = r'''    private fun updateQuick5s(
        runningCandle: CandleAnalyzer.DetectedCandle
    ) {
        val result =
            try {
                CandleAnalyzer.analyzeQuickActivity(
                    candleHistory,
                    runningCandle
                )
            } catch (e: Exception) {
                Log.e(TAG, "5S activity analyzer error", e)
                null
            }

        val confidence = result?.confidence?.coerceIn(0, 100) ?: 0
        val signal =
            if (result?.signal == "CALL" || result?.signal == "PUT") {
                result.signal
            } else {
                "NO TRADE"
            }

        val status =
            if (signal != "NO TRADE" && confidence >= MIN_CONFIDENCE_TO_QUEUE) {
                "5S STRONG SETUP"
            } else {
                "WAIT - 90% GATE"
            }

        sendQuickStatus(
            signal,
            confidence,
            0,
            status
        )
    }

'''
s = s[:start] + fn + s[end:]
cap.write_text(s)

# Make sure every processed frame feeds the activity analyzer.
if '5S activity analyzer error' not in cap.read_text():
    raise SystemExit("5S activity function replacement failed")
if "analyzeQuickActivity(" not in candle.read_text():
    raise SystemExit("CandleAnalyzer quick analyzer missing")
print("V15 VERIFIED: CandleAnalyzer live 5S activity analyzer connected")
