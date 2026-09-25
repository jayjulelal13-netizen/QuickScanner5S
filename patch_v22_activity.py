from pathlib import Path
import re

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('V22 settings.gradle.kts not found')
project = projects[0].parent
analyzer = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'

a = analyzer.read_text()
start = a.find('    fun quickActivityScore(')
if start < 0:
    raise SystemExit('V22 quickActivityScore missing')
# Find the matching method closing brace.
brace = a.find('{', start)
depth = 0
end = -1
for i in range(brace, len(a)):
    if a[i] == '{':
        depth += 1
    elif a[i] == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break
if end < 0:
    raise SystemExit('V22 quickActivityScore end missing')

method = r'''    fun quickActivityScore(
        history: List<DetectedCandle>,
        running: DetectedCandle,
        bucketOpen: Double
    ): Pair<String, Int> {
        if (!running.open.isFinite() || !running.high.isFinite() ||
            !running.low.isFinite() || !running.close.isFinite() ||
            !bucketOpen.isFinite()) {
            return Pair("NO TRADE", 0)
        }

        val range = (running.high - running.low).coerceAtLeast(1.0e-9)
        val closeMove = running.close - bucketOpen

        // Use the full intrabar excursion, not only close-to-open. Screen
        // sampling can keep close unchanged for several frames while the
        // wick/high/low is already moving.
        val upExcursion = running.high - bucketOpen
        val downExcursion = bucketOpen - running.low
        val excursion = max(abs(upExcursion), abs(downExcursion))
        val excursionMove = when {
            upExcursion > 0.0 && upExcursion >= downExcursion -> upExcursion
            downExcursion > 0.0 -> -downExcursion
            else -> closeMove
        }

        val moveRatio = (excursion / range).coerceIn(0.0, 1.0)
        val bodyRatio =
            (abs(running.close - running.open) / range).coerceIn(0.0, 1.0)

        val recent = history.dropLast(1).takeLast(6)
        val bulls = recent.count { it.close > it.open }
        val bears = recent.count { it.close < it.open }
        val recentMove =
            if (recent.size >= 2) recent.last().close - recent.first().open else 0.0
        val recentRange = recent.sumOf {
            (it.high - it.low).coerceAtLeast(1.0e-9)
        }.coerceAtLeast(1.0e-9)
        val recentStrength =
            (abs(recentMove) / recentRange).coerceIn(0.0, 1.0)

        val direction = when {
            excursionMove > 0.0 -> "CALL"
            excursionMove < 0.0 -> "PUT"
            running.close > running.open -> "CALL"
            running.close < running.open -> "PUT"
            bulls >= 3 && recentMove > 0.0 -> "CALL"
            bears >= 3 && recentMove < 0.0 -> "PUT"
            else -> "NO TRADE"
        }
        if (direction == "NO TRADE") return Pair(direction, 0)

        val recentDirection = when {
            bulls >= 3 && recentMove > 0.0 -> "CALL"
            bears >= 3 && recentMove < 0.0 -> "PUT"
            else -> "NO TRADE"
        }

        var score = 15
        score += when {
            moveRatio >= 0.75 -> 42
            moveRatio >= 0.55 -> 38
            moveRatio >= 0.40 -> 32
            moveRatio >= 0.28 -> 25
            moveRatio >= 0.16 -> 17
            moveRatio >= 0.08 -> 9
            else -> 3
        }
        score += when {
            bodyRatio >= 0.70 -> 22
            bodyRatio >= 0.50 -> 18
            bodyRatio >= 0.35 -> 14
            bodyRatio >= 0.22 -> 9
            bodyRatio > 0.0 -> 4
            else -> 0
        }

        if (recentDirection == direction) score += 16
        if ((direction == "CALL" && bulls >= 4) ||
            (direction == "PUT" && bears >= 4)) score += 8
        else if ((direction == "CALL" && bulls >= 3) ||
                 (direction == "PUT" && bears >= 3)) score += 5

        if (recentStrength >= 0.25) score += 7
        else if (recentStrength >= 0.12) score += 3

        // If recent candles strongly oppose the live excursion, suppress the
        // setup instead of manufacturing a high confidence value.
        if ((direction == "CALL" && bears >= 5) ||
            (direction == "PUT" && bulls >= 5)) {
            score -= 15
        }

        return Pair(direction, score.coerceIn(0, 100))
    }'''
a = a[:start] + method + a[end:]
analyzer.write_text(a)

c = cap.read_text()
# Ensure V22's analyzer result is used on every frame and remains the only
# source for displayed quick confidence. Replace only the measured call block.
old = '''        val measured = try {
            CandleAnalyzer.quickActivityScore(
                candleHistory,
                runningCandle,
                quickBucketOpen
            )
        } catch (e: Exception) {
            Log.e(TAG, "V21 CandleAnalyzer activity error", e)
            Pair("NO TRADE", 0)
        }'''
new = '''        val measured = try {
            CandleAnalyzer.quickActivityScore(
                candleHistory,
                runningCandle,
                quickBucketOpen
            )
        } catch (e: Exception) {
            Log.e(TAG, "V22 CandleAnalyzer activity error", e)
            Pair("NO TRADE", 0)
        }'''
if old in c:
    c = c.replace(old, new, 1)
elif 'CandleAnalyzer.quickActivityScore(' not in c:
    raise SystemExit('V22 analyzer call missing')

# Explicitly mark the live feed so future patches cannot accidentally move
# updateQuick5s behind the history-change gate.
if 'V22 per-frame quick activity' not in c:
    marker = '        quickBucketClose = runningCandle.close\n'
    if marker in c:
        c = c.replace(marker, marker + '        // V22 per-frame quick activity: analyzer runs on every captured frame.\n', 1)

cap.write_text(c)

if 'fun quickActivityScore(' not in analyzer.read_text():
    raise SystemExit('V22 analyzer method missing after write')
if 'CandleAnalyzer.quickActivityScore(' not in cap.read_text():
    raise SystemExit('V22 analyzer call missing after write')
print('V22 OK: intrabar high/low excursion + body + recent candle confluence')
