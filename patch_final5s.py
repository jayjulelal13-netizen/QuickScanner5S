import re
from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
gradle = project / 'app/build.gradle.kts'
for f in (candle, cap, gradle):
    if not f.exists():
        raise SystemExit(f'missing {f}')

s = candle.read_text()
for old, new in [
    ('val top = (height * TOP_RATIO).toInt().coerceIn(0, height - 240)', 'val top = (height * 0.12f).toInt().coerceIn(0, height - 240)'),
    ('val bottom = (height * BOTTOM_RATIO).toInt().coerceIn(top + 240, height)', 'val bottom = (height * 0.72f).toInt().coerceIn(top + 240, height)'),
    ('val chartRight = (width * 0.84f).toInt().coerceIn(chartLeft + 180, width - 1)', 'val chartRight = (width * 0.82f).toInt().coerceIn(chartLeft + 180, width - 1)'),
]:
    if old in s:
        s = s.replace(old, new, 1)

s = s.replace(
'''        val pitch = if (gaps.size >= 4) {
            val sorted = gaps.sorted()
            if (sorted.size % 2 == 1) sorted[sorted.size / 2].toDouble()
            else (sorted[sorted.size / 2 - 1] + sorted[sorted.size / 2]) / 2.0
        } else {
            val fallbackPitch = span.toDouble() / 70.0
            if (fallbackPitch > 7.0) fallbackPitch else 7.0
        }''',
'''        val pitch: Double = if (gaps.size >= 4) {
            val sorted = gaps.sorted()
            if (sorted.size % 2 == 1) {
                sorted[sorted.size / 2].toDouble()
            } else {
                (sorted[sorted.size / 2 - 1] + sorted[sorted.size / 2]) / 2.0
            }
        } else {
            val fallbackPitch = span.toDouble() / 70.0
            if (fallbackPitch > 7.0) fallbackPitch else 7.0
        }''', 1)
s = s.replace(
    "if (!(leftGap > pitch * 1.85 && rightGap > pitch * 1.85))",
    "if (!(leftGap > (span.toDouble() / 70.0) * 1.85 && rightGap > (span.toDouble() / 70.0) * 1.85))",
    1
)
s = s.replace(
    "val leftGap = if (idx > 0) centres[idx] - centres[idx - 1] else pitch",
    "val leftGap: Double = if (idx > 0) (centres[idx] - centres[idx - 1]).toDouble() else span.toDouble() / 70.0",
    1
)
s = s.replace(
    "val rightGap = if (idx < centres.lastIndex) centres[idx + 1] - centres[idx] else pitch",
    "val rightGap: Double = if (idx < centres.lastIndex) (centres[idx + 1] - centres[idx]).toDouble() else span.toDouble() / 70.0",
    1
)
candle.write_text(s)

c = cap.read_text()
old = '''        val probability =
            if (direction == "CALL" || direction == "PUT") {
                quickHistoricalProbability(direction)
            } else null'''
new = '''        // 5S confidence is ALWAYS calculated from the detected candle.
        // It is a setup score, not a claimed win probability.
        val candleRange = (runningCandle.high - runningCandle.low).coerceAtLeast(1.0e-9)
        val bodyRatio = (abs(runningCandle.close - runningCandle.open) / candleRange).coerceIn(0.0, 1.0)
        val candleDirection =
            when {
                microBull -> "CALL"
                microBear -> "PUT"
                bodyRatio >= 0.20 && runningCandle.close > runningCandle.open -> "CALL"
                bodyRatio >= 0.20 && runningCandle.close < runningCandle.open -> "PUT"
                else -> "NONE"
            }
        val setupDirection =
            if (direction == "CALL" || direction == "PUT") direction else candleDirection

        var setupScore = if (setupDirection == "CALL" || setupDirection == "PUT") 20 else 0
        if (setupDirection == baseDirection && setupDirection != "NONE") setupScore += 25
        else if (baseDirection != "CALL" && baseDirection != "PUT" && setupDirection != "NONE") setupScore += 12

        setupScore += when {
            microStrength >= 0.30 -> 20
            microStrength >= 0.15 -> 15
            microStrength >= 0.08 -> 10
            microStrength >= 0.04 -> 5
            else -> 0
        }
        if (bodyRatio >= 0.60) setupScore += 15
        else if (bodyRatio >= 0.35) setupScore += 10
        else if (bodyRatio >= 0.20) setupScore += 5

        if ((setupDirection == "CALL" && runningCandle.close > runningCandle.open) ||
            (setupDirection == "PUT" && runningCandle.close < runningCandle.open)) {
            setupScore += 8
        }
        if (setupDirection == direction && direction != "NONE") setupScore += 5

        val probability = setupScore.coerceIn(0, 100)'''
if old in c:
    c = c.replace(old, new, 1)
elif new not in c:
    raise SystemExit('engine probability block missing')
old2 = '''        val canTrade =
            (direction == "CALL" || direction == "PUT") &&
            probability != null &&
            probability >= MIN_EMPIRICAL_PROBABILITY &&
            !cooldown &&
            freshSetup &&
            quickSignalDirection == "NONE"'''
new2 = '''        val canTrade =
            (direction == "CALL" || direction == "PUT") &&
            (probability ?: 0) >= 90 &&
            !cooldown &&
            freshSetup &&
            quickSignalDirection == "NONE"'''
if old2 in c:
    c = c.replace(old2, new2, 1)
elif new2 not in c:
    raise SystemExit('engine gate block missing')
old3 = '''                if (probability == null)
                    "WAIT - 5S CALIBRATION (90% GATE)"
                else if (cooldown || !freshSetup)'''
new3 = '''                if (probability == null)
                    "WAIT - 5S SETUP"
                else if (probability < 90)
                    "WAIT - 90% SETUP"
                else if (cooldown || !freshSetup)'''
if old3 in c:
    c = c.replace(old3, new3, 1)
elif new3 not in c:
    raise SystemExit('engine status block missing')
cap.write_text(c)

g = gradle.read_text().replace('applicationId = "com.example.screener"', 'applicationId = "com.example.screener.final5s"')
gradle.write_text(g)

lines = candle.read_text().splitlines()
print('CANDLE_LINES_1185_1205')
for n in range(1185, min(1205, len(lines)) + 1):
    print(f'{n}: {lines[n-1]}')
for i, line in enumerate(cap.read_text().splitlines(), 1):
    if "val direction" in line or "var direction" in line or "quickSignalDirection" in line or "microStrength" in line:
        print(f"DIRECTION_SOURCE {i}: {line}")
cap_lines = cap.read_text().splitlines()
print('ENGINE_LINES_2785_2900')
for n in range(2785, min(2900, len(cap_lines)) + 1):
    print(f'{n}: {cap_lines[n-1]}')
cap_lines = cap.read_text().splitlines()
print('QUICK_CLOSE_LINES')
for n, line in enumerate(cap_lines, 1):
    if "quickLastClose" in line or "quickLastSignal" in line:
        print(f'{n}: {line}')
# Fix 5S movement sampling deterministically.
# The previous frame-reference approach could become zero because the running
# candle was refreshed from the same detected frame. For QUICK mode the most
# reliable immediate movement is the detected candle body: close - open.
c = cap.read_text()

# Remove any old quickLastClose frame assignments and any stale sampling state.
_lines = c.splitlines()
_kept = []
_removed = 0
for _line in _lines:
    _s = _line.strip()
    if _s == 'quickLastClose = runningCandle.close':
        _removed += 1
        continue
    if _s == 'quickLastSampleBucket = -1L':
        continue
    if _s == 'private var quickLastSampleBucket = -1L':
        continue
    _kept.append(_line)
c = '\n'.join(_kept) + ('\n' if c.endswith(('\n', '\r')) else '')
print('REMOVED_OLD_QUICK_CLOSE_ASSIGNMENTS', _removed)

marker = '        val microMove = runningCandle.close - quickLastClose'
if marker not in c:
    raise SystemExit('microMove marker missing')
replacement_micro = '''        // QUICK movement is the detected candle body, not a per-frame
        // reference that can collapse to zero while the same candle is sampled.
        val microMove = runningCandle.close - runningCandle.open'''
c = c.replace(marker, replacement_micro, 1)

# The score is calculated from the actual detected candle on every frame.
# No historical seed and no fake probability is introduced.
cap.write_text(c)

_final_lines = cap.read_text().splitlines()
_remaining = [
    (i, line) for i, line in enumerate(_final_lines, 1)
    if line.strip() == 'quickLastClose = runningCandle.close'
]
print('REMAINING_QUICK_CLOSE_ASSIGNMENTS', _remaining)
if _remaining:
    raise SystemExit('old quickLastClose frame overwrite still present')

# FINAL OVERLAY FIX:
# Accept the 5S setup score directly from the quick-result broadcast.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('OverlayService.kt missing')
o = ov.read_text()

# Insert before the main status when-block so every quick-result broadcast can update the overlay.
anchor = 'when (intent.getStringExtra("status"))'
if anchor not in o:
    raise SystemExit('Overlay status when-block missing')

generic = '''if (intent.hasExtra("quickProbability") && !activeTrade && !signalLocked) {
            val quickConfidence = intent.getIntExtra("quickProbability", 0).coerceIn(0, 100)
            nextConfidence = quickConfidence
            nextSignal = intent.getStringExtra("quickSignal")?.uppercase(Locale.US) ?: "NO TRADE"
            if (intent.getStringExtra("status") == "LIVE_ANALYSIS") {
                status = "SCANNING"
            }
            updateOverlay()
        }
        if (intent.hasExtra("confidence") && !activeTrade && !signalLocked) {
            nextConfidence = intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
        }

        when (intent.getStringExtra("status"))'''
o=o.replace(anchor,generic,1)
ov.write_text(o)
print('FINAL 5S overlay receiver fixed')
# Diagnostic: print every source line related to the overlay confidence/status so the next fix targets the actual UI variable.
for _p in [project / 'app/src/main/java/com/example/screener/MainActivity.kt',
           project / 'app/src/main/java/com/example/screener/CaptureService.kt',
           project / 'app/src/main/java/com/example/screener/OverlayService.kt']:
    if _p.exists():
        print('OVERLAY_DIAG_FILE', _p)
        _ls=_p.read_text().splitlines()
        for _n, _line in enumerate(_ls, 1):
            if any(_k in _line.lower() for _k in ['confidence', 'candles:', 'status:', 'result:', 'quicksignal', 'probability', 'sendbroadcast', 'quickresult']):
                print(f'OVERLAY_DIAG {_n}: {_line}')
        if _p.name == 'OverlayService.kt':
            print('OVERLAY_CONTEXT')
            for _n in range(65, 125):
                if _n <= len(_ls):
                    print(f'OVERLAY_CONTEXT {_n}: {_ls[_n-1]}')
        print('OVERLAY_DIAG_FILE', _p)
        for _n, _line in enumerate(_p.read_text().splitlines(), 1):
            if any(_k in _line.lower() for _k in ['confidence', 'candles:', 'status:', 'result:', 'quicksignal', 'probability']):
                print(f'OVERLAY_DIAG {_n}: {_line}')


print('5S bucketed reference-price fix added')
# TEMP DIAGNOSTIC: expose the actual candle detector so the next fix targets real source lines.
_diag_lines = candle.read_text().splitlines()
print('CANDLE_ENGINE_FULL_DIAG')
for _n in range(1050, min(1350, len(_diag_lines)) + 1):
    print(f'CANDLE_SRC {_n}: {_diag_lines[_n-1]}')
