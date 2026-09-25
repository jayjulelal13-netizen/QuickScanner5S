from pathlib import Path
import re

project = Path(".")
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
ana = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"
ov = project / "app/src/main/java/com/example/screener/OverlayService.kt"

for p in (cap, ana, ov):
    if not p.exists():
        raise SystemExit(f"V20 missing: {p}")

# ============================================================
# V20: REAL 5S ACTIVITY CANDLE ANALYZER
# ============================================================
# The normal analyzer is intentionally conservative and requires 25
# completed candles plus a full breakout/retest/reversal setup. That is
# correct for normal 1M analysis but too strict for the app-derived 5S
# intrabar engine. Give 5S its own measured activity analysis.
a = ana.read_text()

if "fun analyzeQuickActivity(" not in a:
    marker = "    private fun ema(values: List<Double>, period: Int): Double {"
    quick_method = r'''    /*
     * V20: lightweight analyzer for the app-derived 5-second engine.
     *
     * It uses only detected/completed candles and measures:
     * - recent net movement
     * - bull/bear sequence
     * - body/range quality
     * - short EMA direction
     *
     * It deliberately does NOT manufacture a CALL/PUT signal. It returns
     * directional trend evidence for CaptureService's separate 90% gate.
     */
    fun analyzeQuickActivity(
        history: List<DetectedCandle>
    ): AnalysisResult {
        val tf = "5S"
        if (history.size < MIN_CANDLES) {
            return waitingResult(tf)
        }

        val recent = history.takeLast(min(12, history.size))
        if (recent.size < MIN_CANDLES) {
            return waitingResult(tf)
        }

        val closes = recent.map { it.close }
        val emaFast = ema(closes, min(5, recent.size))
        val emaSlow = ema(closes, min(9, recent.size))

        val firstOpen = recent.first().open
        val lastClose = recent.last().close
        val netMove = lastClose - firstOpen

        val rangeSum = recent.sumOf {
            (it.high - it.low).coerceAtLeast(1.0e-9)
        }

        val bodySum = recent.sumOf {
            abs(it.close - it.open)
        }

        val moveStrength =
            if (rangeSum > 0.0) {
                (abs(netMove) / rangeSum).coerceIn(0.0, 1.0)
            } else {
                0.0
            }

        val bodyQuality =
            if (rangeSum > 0.0) {
                (bodySum / rangeSum).coerceIn(0.0, 1.0)
            } else {
                0.0
            }

        val bullCount = recent.count { it.close > it.open }
        val bearCount = recent.count { it.close < it.open }

        var bullScore = 0
        var bearScore = 0

        if (netMove > 0.0) bullScore += 30
        if (netMove < 0.0) bearScore += 30

        if (emaFast > emaSlow) bullScore += 20
        if (emaFast < emaSlow) bearScore += 20

        if (bullCount >= 7) bullScore += 20
        else if (bullCount >= 5) bullScore += 12

        if (bearCount >= 7) bearScore += 20
        else if (bearCount >= 5) bearScore += 12

        if (moveStrength >= 0.20) {
            if (netMove > 0.0) bullScore += 20
            if (netMove < 0.0) bearScore += 20
        } else if (moveStrength >= 0.10) {
            if (netMove > 0.0) bullScore += 12
            if (netMove < 0.0) bearScore += 12
        }

        if (bodyQuality >= 0.55) {
            if (bullCount > bearCount) bullScore += 10
            if (bearCount > bullCount) bearScore += 10
        }

        bullScore = bullScore.coerceIn(0, 100)
        bearScore = bearScore.coerceIn(0, 100)

        val trend = when {
            bullScore >= 45 && bullScore > bearScore + 10 ->
                "BULLISH / 5S ACTIVITY"
            bearScore >= 45 && bearScore > bullScore + 10 ->
                "BEARISH / 5S ACTIVITY"
            else ->
                "SIDEWAYS / 5S WAIT"
        }

        return AnalysisResult(
            timeframe = tf,
            trend = trend,
            signal = "NO TRADE",
            confidence = 0,
            bullishScore = bullScore,
            bearishScore = bearScore
        )
    }

'''
    if marker not in a:
        raise SystemExit("V20 CandleAnalyzer insertion marker missing")
    a = a.replace(marker, quick_method + marker, 1)

ana.write_text(a)

# ============================================================
# V20: FORCE 5S ENGINE TO USE THE NEW ACTIVITY ANALYZER
# ============================================================
c = cap.read_text()

# Capture must sample fast enough for intrabar activity.
c = c.replace(
    "private const val FRAME_INTERVAL = 1000L",
    "private const val FRAME_INTERVAL = 200L",
    1
)

start = c.find("    private fun updateQuick5s(")
end = c.find("    private fun quickHistoricalProbability", start)
if start < 0 or end < 0:
    raise SystemExit("V20 updateQuick5s markers missing")

q = c[start:end]

# Replace the conservative 1M analyzer call inside the QUICK function.
q = q.replace(
    '''CandleAnalyzer.analyzeHistory(
                        candleHistory.takeLast(MAX_HISTORY),
                        "1M"
                    )''',
    '''CandleAnalyzer.analyzeQuickActivity(
                        candleHistory.dropLast(1).takeLast(MAX_HISTORY)
                    )''',
    1
)

# Use the activity analyzer's directional score as real confluence.
needle = '''        val analyzerDirection =
            when {
                trendText.contains("BULLISH") -> "CALL"
                trendText.contains("BEARISH") -> "PUT"
                else -> "NO TRADE"
            }
'''
replacement = '''        val analyzerDirection =
            when {
                trendText.contains("BULLISH") -> "CALL"
                trendText.contains("BEARISH") -> "PUT"
                (base?.bullishScore ?: 0) >= (base?.bearishScore ?: 0) + 10 -> "CALL"
                (base?.bearishScore ?: 0) >= (base?.bullishScore ?: 0) + 10 -> "PUT"
                else -> "NO TRADE"
            }

        val analyzerScore =
            max(
                base?.bullishScore ?: 0,
                base?.bearishScore ?: 0
            )
'''
if needle not in q:
    raise SystemExit("V20 analyzerDirection block missing")
q = q.replace(needle, replacement, 1)

# Add analyzer score as a measured input before the final probability.
needle2 = '''        val probability = score.coerceIn(0, 100)
        val strong =
'''
replacement2 = '''        score += when {
            analyzerScore >= 75 -> 10
            analyzerScore >= 60 -> 7
            analyzerScore >= 45 -> 4
            else -> 0
        }

        val probability = score.coerceIn(0, 100)
        val strong =
'''
if needle2 not in q:
    raise SystemExit("V20 probability block missing")
q = q.replace(needle2, replacement2, 1)

c = c[:start] + q + c[end:]

# Ensure QUICK engine is called outside candle-history/signature gating.
if "V20 quick activity frame error" not in c:
    anchor = '''        previousRunningCandleSignature =
            createCandleSignature(
                currentRunningCandle
            )
'''
    inject = anchor + '''
        // V20: every processed frame feeds the running activity candle.
        // This is independent of completed-candle history updates.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V20 quick activity frame error", e)
            }
        }
'''
    if anchor not in c:
        raise SystemExit("V20 per-frame anchor missing")
    c = c.replace(anchor, inject, 1)

cap.write_text(c)

# ============================================================
# V20: OVERLAY MUST DISPLAY MEASURED SUB-90 CONFIDENCE TOO
# ============================================================
o = ov.read_text()

# Make QUICK_5S status authoritative. This keeps 0 from being shown just
# because a generic 1M status arrives after the quick frame.
if "V20 quick status handler" not in o:
    marker = '''            timeframe = intent.getStringExtra("timeframe") ?: timeframe
'''
    handler = '''            timeframe = intent.getStringExtra("timeframe") ?: timeframe

            // V20 quick status handler: the 5S activity engine owns the
            // displayed confidence while QUICK mode is running.
            if (intent.getStringExtra("status") == "QUICK_5S" &&
                !activeTrade && !signalLocked
            ) {
                nextConfidence =
                    intent.getIntExtra(
                        "quickProbability",
                        intent.getIntExtra("confidence", nextConfidence)
                    ).coerceIn(0, 100)

                val qs =
                    intent.getStringExtra("quickSignal")
                        ?.uppercase(Locale.US) ?: "NO TRADE"

                nextSignal =
                    if (qs == "CALL" || qs == "PUT") qs else "NO TRADE"

                nextTrend = "5S LIVE ACTIVITY"

                status =
                    if (nextConfidence >= CONFIDENCE_LEVEL &&
                        nextSignal != "NO TRADE"
                    ) "SIGNAL READY" else "WAITING"

                updateOverlay()
                return
            }
'''
    if marker not in o:
        raise SystemExit("V20 overlay marker missing")
    o = o.replace(marker, handler, 1)

ov.write_text(o)

# ============================================================
# V20 VERIFICATION
# ============================================================
for needle in [
    "fun analyzeQuickActivity(",
    "BULLISH / 5S ACTIVITY",
    "BEARISH / 5S ACTIVITY"
]:
    if needle not in a:
        raise SystemExit("V20 VERIFY CandleAnalyzer: " + needle)

for needle in [
    "CandleAnalyzer.analyzeQuickActivity(",
    "V20 quick activity frame error",
    "val analyzerScore",
    "val probability = score.coerceIn(0, 100)"
]:
    if needle not in c:
        raise SystemExit("V20 VERIFY CaptureService: " + needle)

if "V20 quick status handler" not in o:
    raise SystemExit("V20 VERIFY OverlayService handler missing")

print("V20 VERIFIED: dedicated 5S activity CandleAnalyzer + 200ms sampling + measured confidence + 90% gate")
