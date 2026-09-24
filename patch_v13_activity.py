from pathlib import Path
import re
import os

project = Path(os.environ["PROJECT_DIR"])
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
analyzer = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"
main = project / "app/src/main/java/com/example/screener/MainActivity.kt"

if not cap.exists() or not analyzer.exists() or not main.exists():
    raise SystemExit("V13 required source files missing")

s = cap.read_text()

needle = '''        val currentRunningCandle =
            detected.last()

        val nowMillis ='''
insert = '''        val currentRunningCandle =
            detected.last()

        // 5S QUICK is an intrabar engine. Feed the current running candle
        // on every accepted capture frame, not only when closed-candle
        // history changes.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V13 quick activity update failed", e)
            }
        }

        val nowMillis ='''
if needle not in s:
    raise SystemExit("V13 currentRunningCandle insertion point missing")
if "V13 quick activity update failed" not in s:
    s = s.replace(needle, insert, 1)

old = '''        if (quickMode) {
            try {
                updateQuick5s(detected.last())
            } catch (e: Exception) {
                Log.e(TAG, "Legacy quick engine error", e)
            }
        }'''
if old in s:
    s = s.replace(old, "", 1)

s = re.sub(
    r'((?:private\s+)?(?:const\s+)?val\s+FRAME_INTERVAL\s*=\s*)\d+(?:L)?',
    r'\g<1>200L',
    s,
    count=1
)
cap.write_text(s)

a = analyzer.read_text()
marker = '''    fun analyze(
        bitmap: Bitmap,
        timeframe: String
    ): AnalysisResult {'''
helper = '''    /**
     * Running-candle activity for intrabar/5S mode.
     * Returns 0..100 and never claims win probability.
     */
    fun runningCandleActivity(candle: DetectedCandle): Int {
        val range = (candle.high - candle.low).coerceAtLeast(1.0e-9)
        val body = abs(candle.close - candle.open)
        val bodyRatio = (body / range).coerceIn(0.0, 1.0)

        return when {
            bodyRatio >= 0.60 -> 100
            bodyRatio >= 0.45 -> 90
            bodyRatio >= 0.30 -> 75
            bodyRatio >= 0.20 -> 60
            bodyRatio >= 0.10 -> 40
            bodyRatio > 0.0 -> 20
            else -> 0
        }
    }

'''
if "fun runningCandleActivity(candle: DetectedCandle)" not in a:
    if marker not in a:
        raise SystemExit("V13 CandleAnalyzer insertion point missing")
    a = a.replace(marker, helper + marker, 1)
analyzer.write_text(a)

m = main.read_text()
m = m.replace("Win Probability: \${probability}%", "Confidence: \${probability}%")
m = m.replace("Win Probability: \$probability%", "Confidence: \$probability%")
main.write_text(m)

c = cap.read_text()
if "V13 quick activity update failed" not in c:
    raise SystemExit("V13 live quick call missing")
if "updateQuick5s(detected.last())" in c:
    raise SystemExit("V13 duplicate history quick call remains")
if "200L" not in c:
    raise SystemExit("V13 frame interval fix missing")
if "fun runningCandleActivity(candle: DetectedCandle)" not in analyzer.read_text():
    raise SystemExit("V13 CandleAnalyzer activity helper missing")
if "Confidence:" not in main.read_text():
    raise SystemExit("V13 MainActivity label fix missing")

print("V13: per-frame 5S activity feed + CandleAnalyzer activity metric + MainActivity confidence label")


# V15 FINAL: CandleAnalyzer owns the live 5S activity score.
# The score is setup quality (0..100), not guaranteed win probability.
cap = Path(os.environ["PROJECT_DIR"]) / "app/src/main/java/com/example/screener/CaptureService.kt"
analyzer = Path(os.environ["PROJECT_DIR"]) / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"

a = analyzer.read_text()
helper = r'''
    fun quickActivityScore(
        history: List<DetectedCandle>,
        running: DetectedCandle,
        bucketOpen: Double
    ): Pair<String, Int> {
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
        if (recent.size < 3) return Pair(direction, 0)

        val bull = recent.count { it.close > it.open }
        val bear = recent.count { it.close < it.open }
        val agreement = if (direction == "CALL") bull else bear
        val recentRange = recent.sumOf {
            (it.high - it.low).coerceAtLeast(0.0)
        }.coerceAtLeast(1.0e-9)
        val recentMove = recent.last().close - recent.first().open
        val recentStrength = abs(recentMove) / recentRange
        val recentAgrees =
            if (direction == "CALL") recentMove > 0.0 else recentMove < 0.0

        var score = 0
        score += when {
            moveRatio >= 0.60 -> 40
            moveRatio >= 0.40 -> 34
            moveRatio >= 0.25 -> 26
            moveRatio >= 0.15 -> 18
            moveRatio >= 0.08 -> 10
            else -> 0
        }
        score += when {
            bodyRatio >= 0.70 -> 25
            bodyRatio >= 0.55 -> 20
            bodyRatio >= 0.40 -> 14
            bodyRatio >= 0.25 -> 8
            else -> 0
        }
        score += when {
            agreement >= 5 -> 20
            agreement >= 4 -> 15
            agreement >= 3 -> 8
            else -> 0
        }
        if (recentAgrees) score += 8
        if (recentStrength >= 0.20) score += 7
        else if (recentStrength >= 0.12) score += 4

        return Pair(direction, score.coerceIn(0, 100))
    }
'''
if "fun quickActivityScore(" not in a:
    pos = a.rfind("\n}")
    if pos < 0:
        raise SystemExit("V15 CandleAnalyzer closing brace missing")
    a = a[:pos] + "\n" + helper + a[pos:]
    analyzer.write_text(a)

s = cap.read_text()
start = s.find("private fun updateQuick5s")
if start < 0:
    raise SystemExit("V15 updateQuick5s missing")
part = s[start:]
marker = "val liveProbability = liveScore.coerceIn(0, 100)"
if marker in part:
    repl = '''val analyzerQuick =
                CandleAnalyzer.quickActivityScore(
                    candleHistory,
                    runningCandle,
                    quickLastClose
                )
            val liveDirectionFromAnalyzer = analyzerQuick.first
            val liveProbability = analyzerQuick.second.coerceIn(0, 100)'''
    part = part.replace(marker, repl, 1)
    part = part.replace(
        '''                liveDirection,
                liveProbability,''',
        '''                liveDirectionFromAnalyzer,
                liveProbability,''',
        1
    )
    s = s[:start] + part

# The quick engine must run on every accepted capture frame.
needle = '''        val currentRunningCandle =
            detected.last()

        val nowMillis ='''
insert = '''        val currentRunningCandle =
            detected.last()

        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V15 quick activity update failed", e)
            }
        }

        val nowMillis ='''
if needle in s and "V15 quick activity update failed" not in s:
    s = s.replace(needle, insert, 1)

# Remove the old history-only quick call to avoid double processing.
old_call = '''        if (quickMode) {
            try {
                updateQuick5s(detected.last())
            } catch (e: Exception) {
                Log.e(TAG, "Legacy quick engine error", e)
            }
        }'''
s = s.replace(old_call, "", 1)
cap.write_text(s)

if "fun quickActivityScore(" not in analyzer.read_text():
    raise SystemExit("V15 analyzer helper missing")
if "CandleAnalyzer.quickActivityScore(" not in cap.read_text():
    raise SystemExit("V15 capture -> analyzer bridge missing")
if "updateQuick5s(currentRunningCandle)" not in cap.read_text():
    raise SystemExit("V15 per-frame quick call missing")
print("V15 FINAL: per-frame 5S activity -> CandleAnalyzer -> confidence")
