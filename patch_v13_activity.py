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
