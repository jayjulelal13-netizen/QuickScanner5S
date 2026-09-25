from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
if not candle.exists():
    raise SystemExit('CandleAnalyzer missing')
a = candle.read_text()
a = a.replace(
'''val leftGap = if (idx > 0) centres[idx] - centres[idx - 1] else pitch
            val rightGap = if (idx < centres.lastIndex) centres[idx + 1] - centres[idx] else pitch''',
'''val leftGap: Double =
                if (idx > 0) (centres[idx] - centres[idx - 1]).toDouble()
                else pitch
            val rightGap: Double =
                if (idx < centres.lastIndex) (centres[idx + 1] - centres[idx]).toDouble()
                else pitch''',
1
)
# Also handle already partially patched variants.
a = a.replace(
'''val leftGap = if (idx > 0) (centres[idx] - centres[idx - 1]).toDouble() else pitch
            val rightGap = if (idx < centres.lastIndex) (centres[idx + 1] - centres[idx]).toDouble() else pitch''',
'''val leftGap: Double =
                if (idx > 0) (centres[idx] - centres[idx - 1]).toDouble()
                else pitch
            val rightGap: Double =
                if (idx < centres.lastIndex) (centres[idx + 1] - centres[idx]).toDouble()
                else pitch''',
1
)
if 'val leftGap: Double' not in a or 'val rightGap: Double' not in a:
    raise SystemExit('V20 gap typing fix did not apply')
candle.write_text(a)
print('V20_CANDLE_GAP_TYPES_OK')
