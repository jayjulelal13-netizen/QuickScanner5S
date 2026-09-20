package com.example.screener

import android.graphics.Bitmap
import android.graphics.Color
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

data class AnalysisResult(
    val timeframe: String,
    val trend: String,
    val signal: String,
    val confidence: Int,
    val bullishScore: Int = 0,
    val bearishScore: Int = 0
)

object CandleAnalyzer {

    private const val MIN_CANDLES = 5
    private const val MAX_CANDLES = 300

    private const val TOP_RATIO = 0.20f
    private const val BOTTOM_RATIO = 0.76f

    private const val MIN_BRIGHTNESS = 60
    private const val MIN_SATURATION = 45

    private const val MIN_SPAN = 6
    private const val MAX_CANDLE_WIDTH = 14

    private const val MIN_SEQUENCE = 5
    private const val MAX_SPACING_RATIO = 0.45f
    private const val MAX_MISSED_CANDLE_GAP = 2.35f

    private const val SR_ZONE_RATIO = 0.08
    private const val STRONG_BODY_RATIO = 0.55
    private const val MIN_BODY_RATIO = 0.25
    private const val CHOP_RANGE_RATIO = 0.18
    private const val LEVEL_BUFFER_RATIO = 0.06
    private const val MIN_TREND_AGREEMENT = 3
    private const val MIN_SCORE_TO_TRADE = 82.0

    data class DetectedCandle(
        val open: Double,
        val high: Double,
        val low: Double,
        val close: Double,
        val bullish: Boolean
    )

    private data class Candidate(
        val candle: DetectedCandle,
        val center: Int,
        val width: Int,
        val span: Int
    )

    private data class StructureState(
        val higherHighs: Int,
        val higherLows: Int,
        val lowerHighs: Int,
        val lowerLows: Int
    )

    fun detectVisibleCandles(
        bitmap: Bitmap
    ): List<DetectedCandle> {
        return detectCandles(bitmap)
    }

    fun analyze(
        bitmap: Bitmap,
        timeframe: String
    ): AnalysisResult {

        val tf = normalizeTimeframe(timeframe)
        val detected = detectCandles(bitmap)

        if (detected.size < MIN_CANDLES + 1) {
            return waitingResult(tf)
        }

        val completed =
            detected
                .dropLast(1)
                .takeLast(MAX_CANDLES)

        if (completed.size < MIN_CANDLES) {
            return waitingResult(tf)
        }

        return analyzeCandles(completed, tf)
    }

    fun analyzeHistory(
        history: List<DetectedCandle>,
        timeframe: String
    ): AnalysisResult {

        val tf = normalizeTimeframe(timeframe)

        if (history.size < MIN_CANDLES) {
            return waitingResult(tf)
        }

        return analyzeCandles(
            history.takeLast(MAX_CANDLES),
            tf
        )
    }

    private fun analyzeCandles(
        candles: List<DetectedCandle>,
        tf: String
    ): AnalysisResult {
        if (candles.size < 25) return waitingResult(tf)

        // ========================================================
        // V9 ADAPTIVE SIGNAL ENGINE
        // Breakout + Pullback/Retest + Reversal
        //
        // The running candle is never supplied here by CaptureService.
        // This function therefore works only with completed candles.
        // ========================================================

        val recent = candles.takeLast(min(80, candles.size))
        val last = recent.last()
        val prev = recent.getOrNull(recent.lastIndex - 1)
        val closes = recent.map { it.close }

        val ema9 = ema(closes, 9)
        val ema21 = ema(closes, 21)
        val rsi14 = rsi(closes, 14)
        val atr14 = atr(recent, 14)
        val adx14 = adx(recent, 14)
        val stochK = stochastic(recent, 5, 3, 3)
        val previousStochK = if (recent.size >= 2) {
            stochastic(recent.dropLast(1), 5, 3, 3)
        } else stochK
        val previousRsi14 = if (recent.size >= 16) {
            rsi(recent.dropLast(1).map { it.close }, 14)
        } else rsi14

        if (!ema9.isFinite() || !ema21.isFinite() || !atr14.isFinite() || atr14 <= 0.0) {
            return waitingResult(tf)
        }

        val body = abs(last.close - last.open)
        val range = (last.high - last.low).coerceAtLeast(atr14 * 0.01)
        val bodyRatioNow = (body / range).coerceIn(0.0, 1.0)
        val closeLocation = ((last.close - last.low) / range).coerceIn(0.0, 1.0)

        // Recent structure only. Never use a 50+ candle breakout level.
        val levelWindow = recent.dropLast(1).takeLast(12)
        if (levelWindow.size < 8) return waitingResult(tf)

        val resistance = levelWindow.maxOf { it.high }
        val support = levelWindow.minOf { it.low }
        val buffer = max(atr14 * 0.08, abs(last.close) * 0.00003)

        val priorWindow = levelWindow.dropLast(2).takeLast(8)
        val priorResistance = if (priorWindow.size >= 5) priorWindow.maxOf { it.high } else resistance
        val priorSupport = if (priorWindow.size >= 5) priorWindow.minOf { it.low } else support

        val structure = calculateStructure(recent.takeLast(12))
        val structureBull = structure.higherHighs + structure.higherLows >
            structure.lowerHighs + structure.lowerLows
        val structureBear = structure.lowerHighs + structure.lowerLows >
            structure.higherHighs + structure.higherLows

        val bullishTrend = ema9 > ema21 && rsi14 >= 52.0 && adx14 >= 17.0 && (structureBull || rsi14 >= 56.0)
        val bearishTrend = ema9 < ema21 && rsi14 <= 48.0 && adx14 >= 17.0 && (structureBear || rsi14 <= 44.0)

        val stochBullish = stochK >= 45.0 && stochK <= 88.0 && stochK > previousStochK
        val stochBearish = stochK <= 55.0 && stochK >= 12.0 && stochK < previousStochK

        // --------------------------------------------------------
        // 1) BREAKOUT — genuine close outside recent structure
        // --------------------------------------------------------
        val bullBreakout =
            last.close > resistance + buffer &&
            last.open <= resistance + buffer * 0.50 &&
            last.bullish &&
            bodyRatioNow >= 0.50 &&
            closeLocation >= 0.68

        val bearBreakout =
            last.close < support - buffer &&
            last.open >= support - buffer * 0.50 &&
            !last.bullish &&
            bodyRatioNow >= 0.50 &&
            closeLocation <= 0.32

        // --------------------------------------------------------
        // 2) PULLBACK / RETEST — continuation after a break
        // --------------------------------------------------------
        val bullRetest =
            prev != null &&
            prev.close > priorResistance + buffer * 0.50 &&
            last.low <= priorResistance + buffer * 0.45 &&
            last.close > priorResistance + buffer * 0.20 &&
            last.bullish &&
            bodyRatioNow >= 0.30 &&
            closeLocation >= 0.55

        val bearRetest =
            prev != null &&
            prev.close < priorSupport - buffer * 0.50 &&
            last.high >= priorSupport - buffer * 0.45 &&
            last.close < priorSupport - buffer * 0.20 &&
            !last.bullish &&
            bodyRatioNow >= 0.30 &&
            closeLocation <= 0.45

        // --------------------------------------------------------
        // 3) REVERSAL — level rejection + momentum change
        // --------------------------------------------------------
        val nearSupport = last.low <= support + atr14 * 0.20
        val nearResistance = last.high >= resistance - atr14 * 0.20

        // Reversal must be a genuine turn, not just one opposite candle.
        // Require level rejection/engulfing + stochastic turn + RSI turn.
        val bullishRejection =
            isBullishRejection(last) || isBullishEngulfing(recent) || isMorningStar(recent)
        val bearishRejection =
            isBearishRejection(last) || isBearishEngulfing(recent) || isEveningStar(recent)

        val bullMomentumTurn =
            stochK > previousStochK + 3.0 &&
            rsi14 >= 45.0 &&
            rsi14 > previousRsi14

        val bearMomentumTurn =
            stochK < previousStochK - 3.0 &&
            rsi14 <= 55.0 &&
            rsi14 < previousRsi14

        val bullReversal =
            nearSupport &&
            bullishRejection &&
            bullMomentumTurn &&
            last.close > last.open &&
            closeLocation >= 0.55

        val bearReversal =
            nearResistance &&
            bearishRejection &&
            bearMomentumTurn &&
            last.close < last.open &&
            closeLocation <= 0.45

        // --------------------------------------------------------
        // Fake-break protection and market regime filter
        // --------------------------------------------------------
        val falseBull = isFalseBullishBreakout(recent)
        val falseBear = isFalseBearishBreakdown(recent)

        val chopWindow = recent.takeLast(10)
        var flips = 0
        var previousDirection = 0
        for (i in 1 until chopWindow.size) {
            val direction = when {
                chopWindow[i].close > chopWindow[i - 1].close -> 1
                chopWindow[i].close < chopWindow[i - 1].close -> -1
                else -> 0
            }
            if (direction != 0 && previousDirection != 0 && direction != previousDirection) flips++
            if (direction != 0) previousDirection = direction
        }

        val rangeSize = resistance - support
        val chop = flips >= 7 || rangeSize <= atr14 * 1.15

        // Range mode: frequent back-and-forth movement inside a bounded
        // recent structure. Only the boundaries are tradable; the middle
        // of the range remains NO TRADE.
        val preliminaryRangeMarket =
            flips >= 4 &&
            rangeSize <= atr14 * 4.0

        val extension = abs(last.close - ema21) / atr14
        val notOverextended = extension <= 1.35

        val resistanceTouches = levelWindow.count { abs(it.high - resistance) <= atr14 * 0.12 }
        val supportTouches = levelWindow.count { abs(it.low - support) <= atr14 * 0.12 }
        val meaningfulResistance = resistanceTouches >= 2
        val meaningfulSupport = supportTouches >= 2

        val rangeMarket =
            preliminaryRangeMarket &&
            meaningfulResistance &&
            meaningfulSupport

        // --------------------------------------------------------
        // Setup scores. Score is QUALITY, not probability of winning.
        // A signal must pass the hard filters below before confidence
        // is converted into a CALL/PUT.
        // --------------------------------------------------------
        var bullScore = 0.0
        var bearScore = 0.0

        if (bullBreakout) bullScore += 32.0
        if (bullRetest) bullScore += 34.0
        if (bullReversal) bullScore += 34.0
        if (bullishTrend) bullScore += 16.0
        if (structureBull) bullScore += 10.0
        if (adx14 >= 22.0) bullScore += 8.0
        if (rsi14 in 52.0..68.0) bullScore += 6.0
        if (stochBullish) bullScore += 7.0
        if (bodyRatioNow >= 0.55) bullScore += 6.0
        if (meaningfulResistance) bullScore += 5.0

        if (bearBreakout) bearScore += 32.0
        if (bearRetest) bearScore += 34.0
        if (bearReversal) bearScore += 34.0
        if (bearishTrend) bearScore += 16.0
        if (structureBear) bearScore += 10.0
        if (adx14 >= 22.0) bearScore += 8.0
        if (rsi14 in 32.0..48.0) bearScore += 6.0
        if (stochBearish) bearScore += 7.0
        if (bodyRatioNow >= 0.55) bearScore += 6.0
        if (meaningfulSupport) bearScore += 5.0

        if (falseBull) bullScore -= 30.0
        if (falseBear) bearScore -= 30.0
        if (chop) {
            bullScore -= 30.0
            bearScore -= 30.0
        }
        if (!notOverextended) {
            bullScore -= 18.0
            bearScore -= 18.0
        }

        bullScore = bullScore.coerceIn(0.0, 100.0)
        bearScore = bearScore.coerceIn(0.0, 100.0)

        val bullSetup = bullBreakout || bullRetest || bullReversal
        val bearSetup = bearBreakout || bearRetest || bearReversal

        // A setup needs at least three independent confirmations.
        val bullConfirmations = listOf(
            bullishTrend,
            structureBull,
            stochBullish,
            adx14 >= 17.0,
            bodyRatioNow >= 0.30,
            meaningfulResistance || bullReversal
        ).count { it }

        val bearConfirmations = listOf(
            bearishTrend,
            structureBear,
            stochBearish,
            adx14 >= 17.0,
            bodyRatioNow >= 0.30,
            meaningfulSupport || bearReversal
        ).count { it }

        // In a range, only a confirmed boundary reversal may bypass the
        // normal trend/chop block. Breakouts and pullbacks still need the
        // normal non-choppy regime.
        val bullRangeReversal = rangeMarket && bullReversal && !bearReversal
        val bearRangeReversal = rangeMarket && bearReversal && !bullReversal

        val callSetup =
            bullSetup &&
            !bearSetup &&
            (!chop || bullRangeReversal) &&
            !falseBull &&
            notOverextended &&
            bullConfirmations >= 4 &&
            bullScore >= 78.0 &&
            bullScore > bearScore + 15.0

        val putSetup =
            bearSetup &&
            !bullSetup &&
            (!chop || bearRangeReversal) &&
            !falseBear &&
            notOverextended &&
            bearConfirmations >= 4 &&
            bearScore >= 78.0 &&
            bearScore > bullScore + 15.0

        // Confidence is setup quality, not a win-rate claim.
        // Only strong setups reach the app's existing 90% trade gate.
        val confidence = when {
            callSetup -> (88.0 + bullScore * 0.075 + (bullConfirmations - 4) * 1.5)
                .roundToInt().coerceIn(90, 96)
            putSetup -> (88.0 + bearScore * 0.075 + (bearConfirmations - 4) * 1.5)
                .roundToInt().coerceIn(90, 96)
            else -> 0
        }

        if (callSetup && confidence >= 90) {
            val setupName = when {
                bullReversal -> "BULLISH REVERSAL"
                bullRetest -> "BULLISH PULLBACK"
                else -> "BULLISH BREAKOUT"
            }
            return AnalysisResult(tf, setupName, "CALL", confidence,
                bullScore.roundToInt(), bearScore.roundToInt())
        }

        if (putSetup && confidence >= 90) {
            val setupName = when {
                bearReversal -> "BEARISH REVERSAL"
                bearRetest -> "BEARISH PULLBACK"
                else -> "BEARISH BREAKOUT"
            }
            return AnalysisResult(tf, setupName, "PUT", confidence,
                bullScore.roundToInt(), bearScore.roundToInt())
        }

        val trend = when {
            rangeMarket && nearSupport -> "RANGE / SUPPORT"
            rangeMarket && nearResistance -> "RANGE / RESISTANCE"
            rangeMarket -> "RANGE / WAIT BOUNDARY"
            bullishTrend && bullScore > bearScore + 10.0 -> "BULLISH / WAIT SETUP"
            bearishTrend && bearScore > bullScore + 10.0 -> "BEARISH / WAIT SETUP"
            else -> "SIDEWAYS / WAIT SETUP"
        }

        return AnalysisResult(tf, trend, "NO TRADE", 0,
            bullScore.roundToInt(), bearScore.roundToInt())
    }

    private fun ema(values: List<Double>, period: Int): Double {
        if (values.isEmpty()) return Double.NaN
        val p = period.coerceAtLeast(2)
        val start = max(0, values.size - max(p * 3, p))
        var result = values[start]
        val alpha = 2.0 / (p + 1.0)
        for (i in start + 1 until values.size) {
            result = alpha * values[i] + (1.0 - alpha) * result
        }
        return result
    }

    private fun rsi(values: List<Double>, period: Int): Double {
        if (values.size <= period) return Double.NaN
        var gains = 0.0
        var losses = 0.0
        val start = values.size - period
        for (i in start until values.size) {
            val change = values[i] - values[i - 1]
            if (change >= 0) gains += change else losses -= change
        }
        if (losses == 0.0) return 100.0
        val rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))
    }

    private fun atr(candles: List<DetectedCandle>, period: Int): Double {
        if (candles.size < 2) return Double.NaN
        val trs = mutableListOf<Double>()
        for (i in 1 until candles.size) {
            val c = candles[i]
            val p = candles[i - 1]
            trs += max(c.high - c.low, max(abs(c.high - p.close), abs(c.low - p.close)))
        }
        return trs.takeLast(min(period, trs.size)).average()
    }

    private fun adx(candles: List<DetectedCandle>, period: Int): Double {
        if (candles.size < period + 2) return 0.0
        val tr = mutableListOf<Double>()
        val plusDm = mutableListOf<Double>()
        val minusDm = mutableListOf<Double>()
        for (i in 1 until candles.size) {
            val c = candles[i]
            val p = candles[i - 1]
            val up = c.high - p.high
            val down = p.low - c.low
            plusDm += if (up > down && up > 0) up else 0.0
            minusDm += if (down > up && down > 0) down else 0.0
            tr += max(c.high - c.low, max(abs(c.high - p.close), abs(c.low - p.close)))
        }
        val n = min(period, tr.size)
        if (n < period) return 0.0
        val trSum = tr.takeLast(n).sum()
        if (trSum <= 0.0) return 0.0
        val plusDi = 100.0 * plusDm.takeLast(n).sum() / trSum
        val minusDi = 100.0 * minusDm.takeLast(n).sum() / trSum
        val denom = plusDi + minusDi
        if (denom <= 0.0) return 0.0
        return 100.0 * abs(plusDi - minusDi) / denom
    }

    private fun stochastic(candles: List<DetectedCandle>, period: Int, smoothK: Int, smoothD: Int): Double {
        if (candles.size < period) return 50.0
        val ks = mutableListOf<Double>()
        val start = max(period - 1, candles.size - 6)
        for (i in start until candles.size) {
            val window = candles.subList(i - period + 1, i + 1)
            val high = window.maxOf { it.high }
            val low = window.minOf { it.low }
            val denom = high - low
            ks += if (denom <= 0.0) 50.0 else ((candles[i].close - low) / denom) * 100.0
        }
        return ks.takeLast(min(smoothK, ks.size)).average()
    }

    // ============================================================
    // STRUCTURE
    // ============================================================

    private fun calculateStructure(
        candles: List<DetectedCandle>
    ): StructureState {

        var higherHighs = 0
        var higherLows = 0
        var lowerHighs = 0
        var lowerLows = 0

        for (i in 2 until candles.size) {

            val a = candles[i - 2]
            val b = candles[i - 1]
            val c = candles[i]

            if (
                b.high > a.high &&
                c.high > b.high
            ) {
                higherHighs++
            }

            if (
                b.low > a.low &&
                c.low > b.low
            ) {
                higherLows++
            }

            if (
                b.high < a.high &&
                c.high < b.high
            ) {
                lowerHighs++
            }

            if (
                b.low < a.low &&
                c.low < b.low
            ) {
                lowerLows++
            }
        }

        return StructureState(
            higherHighs,
            higherLows,
            lowerHighs,
            lowerLows
        )
    }

    // ============================================================
    // TREND
    // ============================================================

    private fun directionalTrend(
        bull: Int,
        bear: Int,
        bullishMA: Boolean,
        bearishMA: Boolean,
        bullishStructure: Boolean,
        bearishStructure: Boolean
    ): String {

        return when {

            bull > bear &&
            bullishMA ->
                "BULLISH"

            bear > bull &&
            bearishMA ->
                "BEARISH"

            bullishStructure &&
            !bearishStructure ->
                "BULLISH"

            bearishStructure &&
            !bullishStructure ->
                "BEARISH"

            else ->
                "SIDEWAYS"
        }
    }

    // ============================================================
    // BODY RATIO
    // ============================================================

    private fun bodyRatio(
        candle: DetectedCandle
    ): Double {

        val totalRange =
            candle.high - candle.low

        if (
            totalRange <= 0.000001
        ) {
            return 0.0
        }

        val body =
            abs(
                candle.close -
                candle.open
            )

        return (
            body / totalRange
        ).coerceIn(
            0.0,
            1.0
        )
    }

    // ============================================================
    // BULLISH RETEST
    // ============================================================

    private fun isBullishRetest(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 4) {
            return false
        }

        val a =
            candles[candles.lastIndex - 3]

        val b =
            candles[candles.lastIndex - 2]

        val c =
            candles[candles.lastIndex - 1]

        val d =
            candles.last()

        val breakoutUp =
            b.close > a.high

        val retest =
            c.low <= b.close ||
            c.low <= b.high

        val recovery =
            d.bullish &&
            d.close > c.close

        return breakoutUp &&
            retest &&
            recovery
    }

    // ============================================================
    // BEARISH RETEST
    // ============================================================

    private fun isBearishRetest(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 4) {
            return false
        }

        val a =
            candles[candles.lastIndex - 3]

        val b =
            candles[candles.lastIndex - 2]

        val c =
            candles[candles.lastIndex - 1]

        val d =
            candles.last()

        val breakoutDown =
            b.close < a.low

        val retest =
            c.high >= b.close ||
            c.high >= b.low

        val recovery =
            !d.bullish &&
            d.close < c.close

        return breakoutDown &&
            retest &&
            recovery
    }

    // ============================================================
    // FALSE BULLISH BREAKOUT
    // ============================================================

    private fun isFalseBullishBreakout(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 3) {
            return false
        }

        val previous =
            candles.dropLast(1)

        val resistance =
            previous
                .takeLast(
                    min(8, previous.size)
                )
                .maxOf {
                    it.high
                }

        val current =
            candles.last()

        val brokeAbove =
            current.high > resistance

        val closedBackInside =
            current.close < resistance

        return brokeAbove &&
            closedBackInside &&
            !current.bullish
    }

    // ============================================================
    // FALSE BEARISH BREAKDOWN
    // ============================================================

    private fun isFalseBearishBreakdown(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 3) {
            return false
        }

        val previous =
            candles.dropLast(1)

        val support =
            previous
                .takeLast(
                    min(8, previous.size)
                )
                .minOf {
                    it.low
                }

        val current =
            candles.last()

        val brokeBelow =
            current.low < support

        val closedBackInside =
            current.close > support

        return brokeBelow &&
            closedBackInside &&
            current.bullish
    }

    // ============================================================
    // BULLISH ENGULFING
    // ============================================================

    private fun isBullishEngulfing(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 2) {
            return false
        }

        val previous =
            candles[candles.lastIndex - 1]

        val current =
            candles.last()

        return !previous.bullish &&
            current.bullish &&
            current.open <= previous.close &&
            current.close >= previous.open &&
            bodyRatio(current) >= 0.40
    }

    // ============================================================
    // BEARISH ENGULFING
    // ============================================================

    private fun isBearishEngulfing(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 2) {
            return false
        }

        val previous =
            candles[candles.lastIndex - 1]

        val current =
            candles.last()

        return previous.bullish &&
            !current.bullish &&
            current.open >= previous.close &&
            current.close <= previous.open &&
            bodyRatio(current) >= 0.40
    }

    // ============================================================
    // MORNING STAR
    // ============================================================

    private fun isMorningStar(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 3) {
            return false
        }

        val a =
            candles[candles.size - 3]

        val b =
            candles[candles.size - 2]

        val c =
            candles.last()

        val aBody =
            abs(a.close - a.open)

        val bBody =
            abs(b.close - b.open)

        val cBody =
            abs(c.close - c.open)

        if (aBody <= 0.000001) {
            return false
        }

        return !a.bullish &&
            bBody <= aBody * 0.55 &&
            c.bullish &&
            cBody >= aBody * 0.55 &&
            c.close >
            (a.open + a.close) / 2.0
    }

    // ============================================================
    // EVENING STAR
    // ============================================================

    private fun isEveningStar(
        candles: List<DetectedCandle>
    ): Boolean {

        if (candles.size < 3) {
            return false
        }

        val a =
            candles[candles.size - 3]

        val b =
            candles[candles.size - 2]

        val c =
            candles.last()

        val aBody =
            abs(a.close - a.open)

        val bBody =
            abs(b.close - b.open)

        val cBody =
            abs(c.close - c.open)

        if (aBody <= 0.000001) {
            return false
        }

        return a.bullish &&
            bBody <= aBody * 0.55 &&
            !c.bullish &&
            cBody >= aBody * 0.55 &&
            c.close <
            (a.open + a.close) / 2.0
    }

    // ============================================================
    // BULLISH REJECTION
    // ============================================================

    private fun isBullishRejection(
        candle: DetectedCandle
    ): Boolean {

        val body =
            abs(
                candle.close -
                candle.open
            )

        val safeBody =
            max(body, 0.000001)

        val lowerWick =
            min(
                candle.open,
                candle.close
            ) -
            candle.low

        return candle.bullish &&
            lowerWick > safeBody * 1.2
    }

    // ============================================================
    // BEARISH REJECTION
    // ============================================================

    private fun isBearishRejection(
        candle: DetectedCandle
    ): Boolean {

        val body =
            abs(
                candle.close -
                candle.open
            )

        val safeBody =
            max(body, 0.000001)

        val upperWick =
            candle.high -
            max(
                candle.open,
                candle.close
            )

        return !candle.bullish &&
            upperWick > safeBody * 1.2
    }

    // ============================================================
    // GREEN PIXEL
    // ============================================================

    private fun isGreen(
        pixel: Int
    ): Boolean {

        val r = Color.red(pixel)
        val g = Color.green(pixel)
        val b = Color.blue(pixel)

        val maxC =
            max(r, max(g, b))

        val minC =
            min(r, min(g, b))

        val saturation =
            maxC - minC

        return g >= MIN_BRIGHTNESS &&
            g > r + MIN_SATURATION &&
            g > b + 10 &&
            saturation >= MIN_SATURATION
    }

    // ============================================================
    // RED PIXEL
    // ============================================================

    private fun isRed(
        pixel: Int
    ): Boolean {

        val r = Color.red(pixel)
        val g = Color.green(pixel)
        val b = Color.blue(pixel)

        val maxC =
            max(r, max(g, b))

        val minC =
            min(r, min(g, b))

        val saturation =
            maxC - minC

        return r >= MIN_BRIGHTNESS &&
            r > g + MIN_SATURATION &&
            r > b + 10 &&
            saturation >= MIN_SATURATION
    }

    // ============================================================
    // CANDLE PIXEL
    // ============================================================

    private fun isCandlePixel(
        pixel: Int
    ): Boolean {

        return isGreen(pixel) ||
            isRed(pixel)
    }

    // ============================================================
    // TIMEFRAME
    // ============================================================

    private fun normalizeTimeframe(
        timeframe: String
    ): String {

        return when (
            timeframe.trim().uppercase()
        ) {

            "5M",
            "5 MIN",
            "5MIN",
            "5 MINUTE" ->
                "5M"

            "15M",
            "15 MIN",
            "15MIN",
            "15 MINUTE" ->
                "15M"

            else ->
                "1M"
        }
    }

    // ============================================================
    // WAITING
    // ============================================================

    private fun waitingResult(
        timeframe: String
    ): AnalysisResult {

        return AnalysisResult(
            timeframe = timeframe,
            trend = "WAITING",
            signal = "NO TRADE",
            confidence = 0,
            bullishScore = 0,
            bearishScore = 0
        )
    }

    // ============================================================
    // DETECT CANDLES
    // ============================================================

    private fun detectCandles(
        bitmap: Bitmap
    ): List<DetectedCandle> {
        /* V17: adaptive x-density detector.
         * The important fix is that the detector starts BELOW the Quotex
         * banner/status area.  A full-width green promo banner was previously
         * being interpreted as candle pixels, corrupting the candle pitch and
         * eventually returning zero candles.
         */
        val width = bitmap.width
        val height = bitmap.height
        if (width < 250 || height < 400) return emptyList()

        // Keep the scanner out of the top banner/overlay and the right price
        // scale/current-price bubble. These areas can contain the same green/red
        // pixels as candles and can corrupt candle spacing.
        val top = (height * TOP_RATIO).toInt().coerceIn(0, height - 240)
        val bottom = (height * BOTTOM_RATIO).toInt().coerceIn(top + 240, height)
        val chartLeft = (width * 0.015f).toInt().coerceAtLeast(0)
        val chartRight = (width * 0.84f).toInt().coerceIn(chartLeft + 180, width - 1)
        val chartHeight = bottom - top
        val span = chartRight - chartLeft + 1
        if (chartHeight < 200 || span < 150) return emptyList()

        val pixels = IntArray(span * chartHeight)
        bitmap.getPixels(pixels, 0, span, chartLeft, top, span, chartHeight)

        fun greenPixel(pixel: Int): Boolean {
            val r = Color.red(pixel)
            val g = Color.green(pixel)
            val b = Color.blue(pixel)
            return g >= 25 && g >= r + 10 && g >= b + 3 &&
                (g - min(r, b)) >= 12
        }

        fun redPixel(pixel: Int): Boolean {
            val r = Color.red(pixel)
            val g = Color.green(pixel)
            val b = Color.blue(pixel)
            return r >= 25 && r >= g + 10 && r >= b + 3 &&
                (r - min(g, b)) >= 12
        }

        val profile = IntArray(span)
        val greenProfile = IntArray(span)
        val redProfile = IntArray(span)

        var i = 0
        while (i < pixels.size) {
            val pixel = pixels[i]
            val x = i % span
            when {
                greenPixel(pixel) -> {
                    profile[x]++
                    greenProfile[x]++
                }
                redPixel(pixel) -> {
                    profile[x]++
                    redProfile[x]++
                }
            }
            i++
        }

        // Smooth only across neighbouring x-columns.  This preserves the
        // repeated candle rhythm while removing isolated anti-aliasing noise.
        val smooth = IntArray(span)
        for (x in 0 until span) {
            var sum = 0
            var n = 0
            for (dx in -2..2) {
                val xx = x + dx
                if (xx in 0 until span) {
                    sum += profile[xx]
                    n++
                }
            }
            smooth[x] = if (n == 0) 0 else sum / n
        }

        val threshold = max(2, (chartHeight * 0.0008f).roundToInt())
        val rawPeaks = mutableListOf<Int>()
        for (x in 2 until span - 2) {
            val v = smooth[x]
            if (v < threshold) continue
            if (v >= smooth[x - 1] && v >= smooth[x + 1] &&
                (v > smooth[x - 2] || v > smooth[x + 2])) {
                rawPeaks += x
            }
        }
        if (rawPeaks.size < MIN_SEQUENCE) return emptyList()

        // Median distance between neighbouring peaks gives the current zoom's
        // candle pitch.  Ignore tiny noise gaps and very large gaps.
        val gaps = rawPeaks.zipWithNext()
            .map { (a, b) -> b - a }
            .filter { it in 5..60 }
        val pitch = if (gaps.size >= 4) {
            val sorted = gaps.sorted()
            if (sorted.size % 2 == 1) sorted[sorted.size / 2].toDouble()
            else (sorted[sorted.size / 2 - 1] + sorted[sorted.size / 2]) / 2.0
        } else {
            max(7.0, span / 70.0)
        }

        val minDistance = max(4, (pitch * 0.58).roundToInt())
        val selected = mutableListOf<Int>()
        for (peak in rawPeaks.sortedByDescending { smooth[it] }) {
            if (peak < 3 || peak > span - 4) continue
            if (selected.none { abs(it - peak) < minDistance }) selected += peak
        }
        val centres = selected.sorted()
        if (centres.size < MIN_SEQUENCE) return emptyList()

        // Remove isolated coloured UI artifacts while retaining a candle at
        // either end of the visible sequence.
        val cleaned = mutableListOf<Int>()
        for (idx in centres.indices) {
            val leftGap = if (idx > 0) centres[idx] - centres[idx - 1] else pitch
            val rightGap = if (idx < centres.lastIndex) centres[idx + 1] - centres[idx] else pitch
            if (!(leftGap > pitch * 1.85 && rightGap > pitch * 1.85)) {
                cleaned += centres[idx]
            }
        }
        if (cleaned.size < MIN_SEQUENCE) return emptyList()

        val halfWindow = max(2, (pitch * 0.38).roundToInt())
        val candidates = mutableListOf<Candidate>()

        for (center in cleaned) {
            val left = max(0, center - halfWindow)
            val right = min(span - 1, center + halfWindow)
            var green = 0
            var red = 0
            var highY = chartHeight
            var lowY = -1
            var bodyTop = chartHeight
            var bodyBottom = -1
            var greenTop = chartHeight
            var greenBottom = -1
            var redTop = chartHeight
            var redBottom = -1

            for (x in left..right) {
                var y = 0
                while (y < chartHeight) {
                    val pixel = pixels[y * span + x]
                    if (greenPixel(pixel)) {
                        green++
                        if (y < greenTop) greenTop = y
                        if (y > greenBottom) greenBottom = y
                        if (y < highY) highY = y
                        if (y > lowY) lowY = y
                    } else if (redPixel(pixel)) {
                        red++
                        if (y < redTop) redTop = y
                        if (y > redBottom) redBottom = y
                        if (y < highY) highY = y
                        if (y > lowY) lowY = y
                    }
                    y++
                }
            }

            val total = green + red
            if (total < max(4, (chartHeight * 0.0015f).roundToInt())) continue
            if (highY >= lowY) continue

            val bullish = green >= red
            bodyTop = if (bullish) greenTop else redTop
            bodyBottom = if (bullish) greenBottom else redBottom
            if (bodyTop >= bodyBottom || bodyTop == chartHeight || bodyBottom < 0) continue

            val dominance = max(green, red).toDouble() / total.toDouble()
            if (dominance < 0.50) continue

            val candleSpan = lowY - highY + 1
            val bodySpan = bodyBottom - bodyTop + 1
            if (candleSpan < 4 || bodySpan < 2) continue

            val high = (chartHeight - highY).toDouble()
            val low = (chartHeight - lowY).toDouble()
            val bodyHigh = (chartHeight - bodyTop).toDouble()
            val bodyLow = (chartHeight - bodyBottom).toDouble()
            val open = if (bullish) bodyLow else bodyHigh
            val close = if (bullish) bodyHigh else bodyLow
            if (high <= low || open !in low..high || close !in low..high) continue

            candidates += Candidate(
                candle = DetectedCandle(open, high, low, close, bullish),
                center = center + chartLeft,
                width = right - left + 1,
                span = candleSpan
            )
        }

        if (candidates.size < MIN_SEQUENCE) return emptyList()

        val good = mutableListOf<Candidate>()
        for (candidate in candidates.sortedBy { it.center }) {
            if (good.isEmpty()) {
                good += candidate
            } else {
                val distance = candidate.center - good.last().center
                if (distance >= minDistance * 0.88) {
                    good += candidate
                } else if (candidate.span > good.last().span) {
                    good[good.lastIndex] = candidate
                }
            }
        }

        return if (good.size >= MIN_SEQUENCE) {
            good.takeLast(MAX_CANDLES).map { it.candle }
        } else {
            emptyList()
        }
    }

}
