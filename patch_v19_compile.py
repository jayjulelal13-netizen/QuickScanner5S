from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
if not cap.exists() or not candle.exists():
    raise SystemExit('source missing')

c = cap.read_text()
if 'private var quickPrevFrameClose' not in c:
    marker = 'private var quickLastClose = Double.NaN'
    if marker not in c:
        raise SystemExit('quickLastClose declaration missing')
    c = c.replace(
        marker,
        marker + '\n    private var quickPrevFrameClose = Double.NaN',
        1
    )
cap.write_text(c)

a = candle.read_text()
start = a.find('        val gaps = rawPeaks.zipWithNext()')
end = a.find('        val minDistance =', start)
if start < 0 or end < 0:
    raise SystemExit('CandleAnalyzer pitch block missing')

block = '''        val gaps: List<Int> = rawPeaks.zipWithNext()
            .map { pair -> pair.second - pair.first }
            .filter { gap -> gap in 5..60 }

        val pitch: Double =
            if (gaps.size >= 4) {
                val sorted: List<Double> = gaps
                    .map { it.toDouble() }
                    .sorted()
                if (sorted.size % 2 == 1) {
                    sorted[sorted.size / 2]
                } else {
                    val a = sorted[sorted.size / 2 - 1]
                    val b = sorted[sorted.size / 2]
                    (a + b) / 2.0
                }
            } else {
                val fallbackPitch = span.toDouble() / 70.0
                if (fallbackPitch > 7.0) fallbackPitch else 7.0
            }

'''
a = a[:start] + block + a[end:]
candle.write_text(a)

# Final compile guards.
cc = cap.read_text()
aa = candle.read_text()
if 'private var quickPrevFrameClose' not in cc:
    raise SystemExit('V19 quick frame state missing')
if 'val gaps: List<Int>' not in aa or 'val pitch: Double' not in aa:
    raise SystemExit('V19 pitch typing fix missing')
print('V19_COMPILE_FIX_OK')
