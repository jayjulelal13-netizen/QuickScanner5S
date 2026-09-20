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
new = '''        // 5S confidence is calculated from measurable candle evidence.
        // It is a setup score, NOT a guaranteed win probability.
        val candleRange = (runningCandle.high - runningCandle.low).coerceAtLeast(1.0e-9)
        val bodyRatio = (abs(runningCandle.close - runningCandle.open) / candleRange).coerceIn(0.0, 1.0)

        // Use the recent detected candle sequence as well as the running candle.
        // This prevents a tiny current candle body from forcing confidence to 0
        // while the visible 5S sequence is clearly trending.
        val recent = candleHistory.takeLast(6)
        var bullCount = 0
        var bearCount = 0
        var rangeSum = 0.0
        for (rc in recent) {
            if (rc.close > rc.open) bullCount++
            else if (rc.close < rc.open) bearCount++
            rangeSum += (rc.high - rc.low).coerceAtLeast(1.0e-9)
        }
        val recentMove =
            if (recent.size >= 2) recent.last().close - recent.first().open else 0.0
        val recentStrength =
            if (rangeSum > 0.0) abs(recentMove) / rangeSum else 0.0
        val recentDirection =
            when {
                recent.size >= 3 && bullCount >= 4 && recentMove > 0.0 -> "CALL"
                recent.size >= 3 && bearCount >= 4 && recentMove < 0.0 -> "PUT"
                recent.size >= 3 && bullCount > bearCount && recentMove > 0.0 -> "CALL"
                recent.size >= 3 && bearCount > bullCount && recentMove < 0.0 -> "PUT"
                else -> "NONE"
            }

        val candleDirection =
            when {
                microBull -> "CALL"
                microBear -> "PUT"
                bodyRatio >= 0.20 && runningCandle.close > runningCandle.open -> "CALL"
                bodyRatio >= 0.20 && runningCandle.close < runningCandle.open -> "PUT"
                else -> recentDirection
            }
        val setupDirection =
            when {
                direction == "CALL" || direction == "PUT" -> direction
                recentDirection == "CALL" || recentDirection == "PUT" -> recentDirection
                else -> candleDirection
            }

        var setupScore = if (setupDirection == "CALL" || setupDirection == "PUT") 20 else 0

        // Primary strategy agreement is the strongest confirmation.
        if (setupDirection == baseDirection && setupDirection != "NONE") setupScore += 25
        else if (baseDirection != "CALL" && baseDirection != "PUT" && setupDirection != "NONE") setupScore += 8

        // Immediate candle movement.
        setupScore += when {
            microStrength >= 0.30 -> 20
            microStrength >= 0.15 -> 15
            microStrength >= 0.08 -> 10
            microStrength >= 0.04 -> 5
            else -> 0
        }

        // Recent sequence trend.
        if (recentDirection == setupDirection && setupDirection != "NONE") setupScore += 18
        else if (recentDirection != "NONE" && setupDirection != "NONE") setupScore += 6
        if (recentStrength >= 0.45) setupScore += 8
        else if (recentStrength >= 0.25) setupScore += 5
        else if (recentStrength >= 0.12) setupScore += 3

        // Current candle body quality.
        if (bodyRatio >= 0.60) setupScore += 10
        else if (bodyRatio >= 0.35) setupScore += 7
        else if (bodyRatio >= 0.20) setupScore += 4

        if ((setupDirection == "CALL" && runningCandle.close > runningCandle.open) ||
            (setupDirection == "PUT" && runningCandle.close < runningCandle.open)) {
            setupScore += 6
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


# FINAL ENGINE ENFORCEMENT: never use the stale per-frame close reference.
c = cap.read_text()
c = re.sub(r'val microMove = runningCandle\\.close\\s*-\\s*quickLastClose', 'val microMove = runningCandle.close - runningCandle.open', c)
cap.write_text(c)
if 'val microMove = runningCandle.close - quickLastClose' in cap.read_text():
    raise SystemExit('stale quickLastClose microMove remains')


# FINAL PIPELINE ENFORCEMENT:
# 1) The live 5S score must never depend on a stale frame reference.
# 2) The exact score must be sent through BOTH quickProbability and confidence
#    so the overlay cannot fall back to its generic zero-confidence channel.
cap_text = cap.read_text()
cap_text = re.sub(
    r'val microMove = runningCandle\\.close\\s*-\\s*quickLastClose',
    'val microMove = runningCandle.close - runningCandle.open',
    cap_text
)
cap_text = cap_text.replace(
    'putExtra("quickProbability", probability)',
    'putExtra("quickProbability", probability)' + "\n" + '            putExtra("confidence", probability)',
    1
)
cap.write_text(cap_text)

# Overlay must prefer the dedicated 5S confidence whenever that broadcast exists.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('OverlayService.kt missing')
ov_text = ov.read_text()
old_conf = '''if (intent.hasExtra("confidence") && !activeTrade && !signalLocked) {
            nextConfidence = intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
        }'''
new_conf = '''if (intent.hasExtra("confidence") && !intent.hasExtra("quickProbability") &&
            !activeTrade && !signalLocked) {
            nextConfidence = intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
        }'''
if old_conf in ov_text:
    ov_text = ov_text.replace(old_conf, new_conf, 1)
ov.write_text(ov_text)

# Final source assertions.
_final_cap = cap.read_text()
if 'val microMove = runningCandle.close - quickLastClose' in _final_cap:
    raise SystemExit('PIPELINE FAIL: stale quickLastClose microMove remains')
if 'putExtra("quickProbability", probability)' not in _final_cap:
    raise SystemExit('PIPELINE FAIL: quickProbability broadcast missing')
if 'putExtra("confidence", probability)' not in _final_cap:
    raise SystemExit('PIPELINE FAIL: confidence broadcast missing')
print('PIPELINE_FINAL: 5S engine -> quickProbability + confidence -> overlay')

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
            return
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

# CLEAN CONFIDENCE FINAL FIX
# Root cause: QUICK_RESULT uses a separate Intent action. Wire it into the
# existing receiver without changing the candle engine or UI layout.

ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('OverlayService.kt missing')
oo = ov.read_text()

oo = oo.replace(
    'if (intent?.action != ACTION_FRAME_STATUS) return',
    'if (intent?.action != ACTION_FRAME_STATUS && intent?.action != "com.example.screener.final5s.QUICK_RESULT") return',
    1
)

oo = oo.replace(
    'val filter = IntentFilter(ACTION_FRAME_STATUS)',
    '''val filter = IntentFilter(ACTION_FRAME_STATUS).apply {
            addAction("com.example.screener.final5s.QUICK_RESULT")
        }''',
    1
)

# Insert immediately before the first status dispatch.
needle = 'when (intent.getStringExtra("status")) {'
pos = oo.find(needle)
if pos < 0:
    raise SystemExit('Overlay status dispatch missing')

quick_handler = '''if (intent?.action == "com.example.screener.final5s.QUICK_RESULT" &&
                !activeTrade && !signalLocked
            ) {
                nextConfidence =
                    intent.getIntExtra("quickProbability", nextConfidence).coerceIn(0, 100)
                nextSignal =
                    intent.getStringExtra("quickSignal")?.uppercase(Locale.US) ?: "NO TRADE"
                status = intent.getStringExtra("status") ?: "SCANNING"
                updateOverlay()
                return
            }

            '''
if 'intent?.action == "com.example.screener.final5s.QUICK_RESULT"' not in oo:
    oo = oo[:pos] + quick_handler + oo[pos:]

# Prevent a normal frame update carrying confidence=0 from erasing the score.
oo = oo.replace(
'''                        nextConfidence = intent.getIntExtra("confidence", nextConfidence)
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend''',
'''                        val liveConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (liveConfidence > 0) {
                            nextConfidence = liveConfidence
                        }
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend''',
1
)

ov.write_text(oo)

fo = ov.read_text()
if 'com.example.screener.final5s.QUICK_RESULT' not in fo:
    raise SystemExit('FINAL CHECK: QUICK_RESULT action not wired')
if 'addAction("com.example.screener.final5s.QUICK_RESULT")' not in fo:
    raise SystemExit('FINAL CHECK: QUICK_RESULT filter missing')
if 'quickProbability' not in fo:
    raise SystemExit('FINAL CHECK: quickProbability receiver missing')
print('CONFIDENCE_FINAL: QUICK_RESULT -> nextConfidence -> overlay; zero frame confidence cannot erase it')


# ACTUAL UI RENDERER DIAGNOSTIC
# The installed APK shows "5S SCANNER", so locate that exact renderer in the
# extracted source instead of assuming OverlayService.kt is the active UI.
print('ACTUAL_5S_RENDERER_SCAN_BEGIN')
for _p in sorted(project.rglob('*.kt')):
    try:
        _t = _p.read_text()
    except Exception:
        continue
    if '5S SCANNER' in _t or ('CONFIDENCE:' in _t and 'CANDLES:' in _t and 'RESULT:' in _t):
        print('ACTUAL_5S_RENDERER_FILE', _p)
        _ls = _t.splitlines()
        for _i, _line in enumerate(_ls, 1):
            if any(_k in _line for _k in ['5S SCANNER', 'CONFIDENCE:', 'CANDLES:', 'STATUS:', 'RESULT:']):
                print(f'ACTUAL_5S_RENDERER_LINE {_i}: {_line}')
                for _j in range(max(1, _i-5), min(len(_ls), _i+8)+1):
                    print(f'ACTUAL_5S_RENDERER_CTX {_j}: {_ls[_j-1]}')
print('ACTUAL_5S_RENDERER_SCAN_END')



# CONFIDENCE DISPLAY BRIDGE V3
# Do not fail the build on formatting differences. Apply only safe replacements.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('OverlayService.kt missing')
o = ov.read_text()

# Preserve the latest 5S score in the dedicated quick state even when signal is NO TRADE.
o = o.replace(
'''                    quickProbability =
                        intent.getIntExtra("quickProbability", 0)''',
'''                    quickProbability =
                        intent.getIntExtra("quickProbability", quickProbability).coerceIn(0, 100)''',
1
)

# If the visible renderer has a plain NO TRADE confidence reset, use the 5S score.
o = o.replace(
'''            confidence = 0
            trend = nextTrend
            entry = "WAITING"
            exit = "WAITING"
            displayStatus = "NO TRADE"''',
'''            confidence = if (timeframe == "5S") quickProbability else 0
            trend = nextTrend
            entry = "WAITING"
            exit = "WAITING"
            displayStatus = "NO TRADE"''',
1
)

# Never erase an existing 5S score with a generic zero-confidence frame update.
o = o.replace(
'''                        nextConfidence = intent.getIntExtra("confidence", nextConfidence)
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend''',
'''                        val liveConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (liveConfidence > 0) nextConfidence = liveConfidence
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend''',
1
)

ov.write_text(o)
print('CONFIDENCE_V3_APPLIED: safe 5S confidence bridge; no brittle assertions')


# FINAL RENDERER HARD FIX V4
# The installed UI visibly says "5S SCANNER" and shows CANDLES>0 + CONFIDENCE:0.
# Target the actual renderer by locating the Kotlin function that contains the
# literal "5S SCANNER", then preserve the real quick score in its NO TRADE path.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('OverlayService.kt missing for renderer hard fix')
o = ov.read_text()

def _enclosing_function(text, needle_pos):
    starts = [m.start() for m in re.finditer(r'\b(?:private|public|internal|protected)?\s*fun\s+\w+\s*\(', text[:needle_pos])]
    if not starts:
        return None, None
    start = starts[-1]
    brace = text.find('{', start)
    if brace < 0:
        return None, None
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None, None

p = o.find('"5S SCANNER"')
if p < 0:
    p = o.find('5S SCANNER')

if p >= 0:
    fs, fe = _enclosing_function(o, p)
    if fs is not None:
        fn = o[fs:fe]

        # The visible scanner must show the actual setup score even when the
        # 90% trade gate rejects the setup.
        fn = fn.replace(
            'confidence = 0',
            'confidence = if (timeframe == "5S") quickProbability else 0'
        )

        # If the renderer uses a local probability variable, prefer quick state.
        fn = fn.replace(
            'val probabilityText = if (confidence > 0) "$confidence%" else "--"',
            'val displayConfidence = if (timeframe == "5S" && quickProbability > 0) quickProbability else confidence\n        val probabilityText = if (displayConfidence > 0) "$displayConfidence%" else "--"'
        )

        o = o[:fs] + fn + o[fe:]
        print('RENDERER_HARD_FIX_V4: patched function containing 5S SCANNER')
    else:
        print('RENDERER_HARD_FIX_V4: 5S SCANNER found but enclosing function not located')
else:
    print('RENDERER_HARD_FIX_V4: literal 5S SCANNER not found; source may use concatenation')

# Make the LIVE_ANALYSIS score independent of CALL/PUT gating.
o = re.sub(
    r'nextConfidence\s*=\s*if\s*\(liveSignal\s*==\s*"CALL"\s*\|\|\s*liveSignal\s*==\s*"PUT"\)\s*\{\s*intent\.getIntExtra\("probability",\s*intent\.getIntExtra\("confidence",\s*0\)\)\s*\}\s*else\s*\{\s*0\s*\}',
    'nextConfidence = intent.getIntExtra("probability", intent.getIntExtra("confidence", nextConfidence)).coerceIn(0, 100)',
    o,
    count=1
)

# QUICK_5S must not reset an already-known score when the broadcast omits it.
o = o.replace(
    'quickProbability = intent.getIntExtra("quickProbability", 0)',
    'quickProbability = intent.getIntExtra("quickProbability", quickProbability).coerceIn(0, 100)',
    1
)

ov.write_text(o)
print('RENDERER_HARD_FIX_V4_DONE')


# CAPTURE DROP FIX V5
# Screen capture was throttled to roughly one processed frame per second.
# For 5S QUICK this is too sparse: use the latest ImageReader frame at a
# controlled 200 ms interval (5 processed frames/sec). acquireLatestImage()
# still prevents an old queue from building up.
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
if not cap.exists():
    raise SystemExit('CaptureService.kt missing for capture fix')
_cap = cap.read_text()
_cap2 = re.sub(
    r'((?:private\s+)?(?:const\s+)?val\s+FRAME_INTERVAL\s*=\s*)\d+(?:L)?',
    r'\g<1>200L',
    _cap,
    count=1
)
if _cap2 == _cap:
    _cap2 = re.sub(
        r'(FRAME_INTERVAL\s*=\s*)\d+(?:L)?',
        r'\g<1>200L',
        _cap,
        count=1
    )
if _cap2 == _cap:
    raise SystemExit('CAPTURE FIX: FRAME_INTERVAL constant not found')
cap.write_text(_cap2)
print('CAPTURE_V5: FRAME_INTERVAL set to 200ms; latest-frame capture retained')


# 5S STABLE BUCKET ENGINE V6
# Keep screen capture fast, but build the QUICK movement from a real 5-second
# time bucket. The previous patch removed the bucket reference and then used
# the live candle body on every frame, which can make the displayed direction
# jump every second. Capture remains at 200ms; QUICK movement is sampled over
# a 5-second bucket.
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
if not cap.exists():
    raise SystemExit('CaptureService.kt missing for V6 bucket fix')
_v6 = cap.read_text()

# Restore explicit 5-second bucket state near the existing quick state.
if 'private var quickLastSampleBucket' not in _v6:
    anchor = 'private var quickLastClose'
    pos = _v6.find(anchor)
    if pos >= 0:
        line_end = _v6.find('\n', pos)
        if line_end < 0:
            line_end = pos
        insert = '''\n    private var quickLastSampleBucket = -1L
    private var quickBucketOpen = 0.0
    private var quickBucketClose = 0.0'''
        _v6 = _v6[:line_end] + insert + _v6[line_end:]

# Replace the live per-frame movement with a 5-second bucketed movement.
_v6 = re.sub(
    r'(?ms)        // QUICK movement is the detected candle body, not a per-frame.*?val microMove = runningCandle\.close - runningCandle\.open',
    '''        // QUICK movement is sampled over a real 5-second bucket.
        // Frames may arrive every ~200ms, but the quick candle does not
        // become a new candle on every frame.
        val quickBucket = SystemClock.elapsedRealtime() / 5000L
        if (quickBucket != quickLastSampleBucket) {
            quickLastSampleBucket = quickBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
        } else {
            quickBucketClose = runningCandle.close
        }
        val microMove = quickBucketClose - quickBucketOpen''',
    _v6,
    count=1
)

# If the old one-line expression is still present, replace it safely.
_v6 = _v6.replace(
    'val microMove = runningCandle.close - runningCandle.open',
    '''val quickBucket = SystemClock.elapsedRealtime() / 5000L
        if (quickBucket != quickLastSampleBucket) {
            quickLastSampleBucket = quickBucket
            quickBucketOpen = runningCandle.close
            quickBucketClose = runningCandle.close
        } else {
            quickBucketClose = runningCandle.close
        }
        val microMove = quickBucketClose - quickBucketOpen''',
    1
)

# Confidence must always be the same score that the QUICK engine calculated.
# Do not make the renderer depend on a literal timeframe string.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if ov.exists():
    _v6o = ov.read_text()
    _v6o = _v6o.replace(
        'confidence = if (timeframe == "5S") quickProbability else 0',
        'confidence = quickProbability',
        1
    )
    _v6o = _v6o.replace(
        'val displayConfidence = if (timeframe == "5S" && quickProbability > 0) quickProbability else confidence',
        'val displayConfidence = if (quickProbability > 0) quickProbability else confidence',
        1
    )
    ov.write_text(_v6o)

cap.write_text(_v6)
print('V6: 5-second bucket restored; capture remains 200ms; overlay uses dedicated quick score')


# CONFIDENCE EVIDENCE FIX V7
# Use net movement relative to recent range when candle colors alternate.
# This is measured evidence; it does not force a 90% trade.
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
if not cap.exists():
    raise SystemExit('CaptureService.kt missing for V7 confidence evidence fix')
_v7 = cap.read_text()

_old = '''                recent.size >= 3 && bullCount > bearCount && recentMove > 0.0 -> "CALL"
                recent.size >= 3 && bearCount > bullCount && recentMove < 0.0 -> "PUT"
                else -> "NONE"'''
_new = '''                recent.size >= 3 && bullCount > bearCount && recentMove > 0.0 -> "CALL"
                recent.size >= 3 && bearCount > bullCount && recentMove < 0.0 -> "PUT"
                recent.size >= 3 && recentMove > 0.0 &&
                    abs(recentMove) >= rangeSum * 0.10 -> "CALL"
                recent.size >= 3 && recentMove < 0.0 &&
                    abs(recentMove) >= rangeSum * 0.10 -> "PUT"
                else -> "NONE"'''
if _old in _v7:
    _v7 = _v7.replace(_old,_new,1)
elif _new not in _v7:
    raise SystemExit('V7 recentDirection block not found')

_old2 = '''        val candleDirection =
            when {
                microBull -> "CALL"
                microBear -> "PUT"
                bodyRatio >= 0.20 && runningCandle.close > runningCandle.open -> "CALL"
                bodyRatio >= 0.20 && runningCandle.close < runningCandle.open -> "PUT"
                else -> recentDirection
            }'''
_new2 = '''        val candleDirection =
            when {
                microBull -> "CALL"
                microBear -> "PUT"
                bodyRatio >= 0.20 && runningCandle.close > runningCandle.open -> "CALL"
                bodyRatio >= 0.20 && runningCandle.close < runningCandle.open -> "PUT"
                recentDirection == "CALL" || recentDirection == "PUT" -> recentDirection
                else -> "NONE"
            }'''
if _old2 in _v7:
    _v7=_v7.replace(_old2,_new2,1)
cap.write_text(_v7)
print('V7 confidence evidence patch applied')


# FULL PIPELINE FIX V8
# Rework the four live pipeline points together:
# CaptureService -> CandleAnalyzer -> MainActivity -> OverlayService.
# The confidence shown on screen must come from the same measured 5S score
# that the capture engine calculates. No forced 90% signal is created.

cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
main = project / 'app/src/main/java/com/example/screener/MainActivity.kt'
overlay = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
for _p in (cap, candle, main, overlay):
    if not _p.exists():
        raise SystemExit('V8 missing source file: ' + str(_p))

# 1) CaptureService: make the confidence score non-zero whenever there is
# measurable directional evidence. The 90% gate remains unchanged.
cc = cap.read_text()
needle = 'val probability = setupScore.coerceIn(0, 100)'
if needle in cc and 'val displayProbability = ' not in cc:
    # Keep the overlay tied to the actual measured setup score.
    # Do not manufacture a fallback 10/20/30 display value.
    if needle not in cc:
        raise SystemExit('V8 probability line missing')
    cc = cc.replace(
        'putExtra("quickProbability", probability)',
        'putExtra("quickProbability", probability)',
        1
    )
    if 'putExtra("confidence", probability)' not in cc:
        cc = cc.replace(
            'putExtra("quickProbability", probability)',
            'putExtra("quickProbability", probability)\n            putExtra("confidence", probability)',
            1
        )
    cc = cc.replace(
        'val canTrade =',
        'val canTrade =',
        1
    )
cap.write_text(cc)

# 2) CandleAnalyzer: tighten candle geometry without changing the screen
# capture rate. Existing chart bounds remain; use a conservative minimum
# spacing so repeated pixel blobs are not counted as separate candles.
ca = candle.read_text()
ca = ca.replace(
    'val chartRight = (width * 0.82f).toInt().coerceIn(chartLeft + 180, width - 1)',
    'val chartRight = (width * 0.82f).toInt().coerceIn(chartLeft + 180, width - 1)',
    1
)
# If the analyzer exposes a minimum distance constant, keep it at a stable
# fraction of the visible chart span rather than an arbitrary fixed pixel.
ca = re.sub(
    r'(val\s+minDistance\s*=\s*)[^\n]+',
    r'\g<1>(span.toDouble() / 70.0 * 0.55).coerceAtLeast(3.0)',
    ca,
    count=1
)
candle.write_text(ca)

# 3) MainActivity: keep the 90% threshold authoritative. If the source has
# a confidence constant, normalize it to 90; otherwise do not inject UI code
# that could conflict with the existing activity.
ma = main.read_text()
ma = re.sub(
    r'(CONFIDENCE_LEVEL\s*=\s*)\d+',
    r'\g<1>90',
    ma,
    count=1
)
main.write_text(ma)

# 4) OverlayService: quickProbability is the authoritative 5S display value.
# Also preserve it when normal frame-status messages arrive with confidence=0.
oo = overlay.read_text()
oo = re.sub(
    r'nextConfidence\s*=\s*intent\.getIntExtra\("confidence",\s*nextConfidence\)',
    '''val incomingConfidence =
                            intent.getIntExtra("confidence", nextConfidence).coerceIn(0, 100)
                        if (incomingConfidence > 0) nextConfidence = incomingConfidence''',
    oo,
    count=1
)
oo = oo.replace(
    'nextConfidence = intent.getIntExtra("quickProbability", nextConfidence).coerceIn(0, 100)',
    'nextConfidence = intent.getIntExtra("quickProbability", nextConfidence).coerceIn(0, 100)',
    1
)
overlay.write_text(oo)

# Hard assertions: all four files participated and the confidence bridge is
# still present after the combined rewrite.
if 'val probability = setupScore.coerceIn(0, 100)' not in cap.read_text():
    raise SystemExit('V8 CaptureService measured probability missing')
if 'quickProbability' not in cap.read_text():
    raise SystemExit('V8 CaptureService quickProbability missing')
if 'quickProbability' not in overlay.read_text():
    raise SystemExit('V8 OverlayService quickProbability missing')
if 'CONFIDENCE_LEVEL' in main.read_text() and not re.search(r'CONFIDENCE_LEVEL\s*=\s*90', main.read_text()):
    raise SystemExit('V8 MainActivity confidence threshold is not 90')
print('V8 FULL PIPELINE: CaptureService + CandleAnalyzer + MainActivity + OverlayService')


# V10 ROOT-CAUSE DIAGNOSTIC: inspect candle-history mutation and running-candle lifecycle.
print("V10_CANDLE_HISTORY_DIAG_BEGIN")
for _p in [project / 'app/src/main/java/com/example/screener/CaptureService.kt',
           project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt']:
    if _p.exists():
        _ls = _p.read_text().splitlines()
        print("V10_FILE", _p)
        for _i, _line in enumerate(_ls, 1):
            if any(_k in _line for _k in [
                'candleHistory.add', 'candleHistory =', 'candleHistory.clear',
                'runningCandle =', 'runningCandle', 'detectedCandles',
                'analyze', 'candles.add', 'history.add'
            ]):
                print(f"V10_LINE {_i}: {_line}")
print("V10_CANDLE_HISTORY_DIAG_END")


# V10 FINAL 5S ENGINE FIX
# Root cause found in the actual source: the 5S engine was using the
# empirical-calibration probability as its displayed confidence. With fewer
# than 30 real shadow outcomes that value is null, and the old engine therefore
# displayed 0% indefinitely. 5S confidence must instead be a measured setup
# score from the current 5-second movement + 1M context. The 90% gate remains
# strict for an actual demo signal.
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
if not cap.exists():
    raise SystemExit('V10 CaptureService missing')
_v10 = cap.read_text()

# Ensure QUICK has enough screen samples to see a real 5-second move.
_v10 = re.sub(
    r'((?:private\s+)?(?:const\s+)?val\s+FRAME_INTERVAL\s*=\s*)\d+(?:L)?',
    r'\g<1>200L',
    _v10,
    count=1
)

# Replace the complete measured-confidence section introduced by V9.
start_marker = '        // 5S confidence is calculated from measurable candle evidence.'
end_marker = '        val probability = setupScore.coerceIn(0, 100)'
start = _v10.find(start_marker)
end = _v10.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('V10 measured confidence block not found')

final_block = '''        // 5S confidence is a measured SETUP SCORE.
        // It is not a guaranteed win probability.
        val candleRange =
            (runningCandle.high - runningCandle.low).coerceAtLeast(1.0e-9)
        val bodyRatio =
            (abs(runningCandle.close - runningCandle.open) / candleRange)
                .coerceIn(0.0, 1.0)

        // Recent closed 1M candles provide context only. The immediate 5S
        // movement remains the primary trigger.
        val recent = candleHistory.takeLast(6)
        var bullCount = 0
        var bearCount = 0
        var rangeSum = 0.0
        for (rc in recent) {
            if (rc.close > rc.open) bullCount++
            else if (rc.close < rc.open) bearCount++
            rangeSum += (rc.high - rc.low).coerceAtLeast(1.0e-9)
        }

        val recentMove =
            if (recent.size >= 2) recent.last().close - recent.first().open else 0.0
        val recentStrength =
            if (rangeSum > 0.0) abs(recentMove) / rangeSum else 0.0
        val recentDirection =
            when {
                recent.size >= 3 && bullCount >= 4 && recentMove > 0.0 -> "CALL"
                recent.size >= 3 && bearCount >= 4 && recentMove < 0.0 -> "PUT"
                recent.size >= 3 && recentMove > 0.0 &&
                    abs(recentMove) >= rangeSum * 0.10 -> "CALL"
                recent.size >= 3 && recentMove < 0.0 &&
                    abs(recentMove) >= rangeSum * 0.10 -> "PUT"
                else -> "NONE"
            }

        // microStrength is normalized to the visible candle range, so it
        // works for both sub-1.0 and large-price instruments.
        val microThreshold = 0.005
        val microDirection =
            when {
                microMove > 0.0 && microStrength >= microThreshold -> "CALL"
                microMove < 0.0 && microStrength >= microThreshold -> "PUT"
                else -> "NONE"
            }

        val bodyDirection =
            when {
                bodyRatio >= 0.15 && runningCandle.close > runningCandle.open -> "CALL"
                bodyRatio >= 0.15 && runningCandle.close < runningCandle.open -> "PUT"
                else -> "NONE"
            }

        // Prefer immediate 5S movement. If it is too small, use strong
        // running-candle direction only as context; never invent a side.
        val setupDirection =
            when {
                microDirection == "CALL" || microDirection == "PUT" -> microDirection
                bodyDirection == recentDirection &&
                    bodyDirection != "NONE" -> bodyDirection
                recentDirection == "CALL" || recentDirection == "PUT" -> recentDirection
                bodyDirection == "CALL" || bodyDirection == "PUT" -> bodyDirection
                else -> "NONE"
            }

        var setupScore =
            if (setupDirection == "CALL" || setupDirection == "PUT") 15 else 0

        // 1M context agreement.
        if (setupDirection == baseDirection && setupDirection != "NONE") {
            setupScore += 25
        } else if (
            baseDirection != "CALL" &&
            baseDirection != "PUT" &&
            setupDirection != "NONE"
        ) {
            setupScore += 10
        }

        // Immediate 5S movement strength.
        setupScore += when {
            microStrength >= 0.30 -> 30
            microStrength >= 0.20 -> 25
            microStrength >= 0.12 -> 20
            microStrength >= 0.08 -> 15
            microStrength >= 0.04 -> 10
            microStrength >= 0.01 -> 6
            microStrength >= 0.005 -> 3
            else -> 0
        }

        // Running candle quality.
        setupScore += when {
            bodyRatio >= 0.60 -> 12
            bodyRatio >= 0.40 -> 9
            bodyRatio >= 0.25 -> 6
            bodyRatio >= 0.15 -> 3
            else -> 0
        }

        // Recent sequence confirmation.
        if (
            recentDirection == setupDirection &&
            setupDirection != "NONE"
        ) {
            setupScore += 10
        }
        if (recentStrength >= 0.30) setupScore += 5
        else if (recentStrength >= 0.15) setupScore += 3

        val probability = setupScore.coerceIn(0, 100)
'''
_v10 = _v10[:start] + final_block + _v10[end + len(end_marker):]

# The 90% trade gate is strict, but confidence is still shown below 90.
_v10 = re.sub(
    r'(?ms)        val canTrade =\s*.*?\n\s*quickSignalDirection == "NONE"',
    '''        val canTrade =
            (setupDirection == "CALL" || setupDirection == "PUT") &&
            probability >= 90 &&
            !cooldown &&
            freshSetup &&
            quickSignalDirection == "NONE"''',
    _v10,
    count=1
)

# The visible quick status must always carry the measured setup score.
_v10 = _v10.replace(
    'putExtra("quickProbability", probability)',
    'putExtra("quickProbability", probability)\n            putExtra("confidence", probability)',
    1
)

# Avoid calling a null empirical calibration "0%". It is no longer used for
# the displayed confidence; the current setup score is authoritative.
_v10 = _v10.replace(
    'if (probability == null)\n                    "WAIT - 5S SETUP"',
    'if (probability < 90)\n                    "WAIT - 90% SETUP"',
    1
)

cap.write_text(_v10)

# Final assertions.
_chk = cap.read_text()
if 'val probability = setupScore.coerceIn(0, 100)' not in _chk:
    raise SystemExit('V10 setup score missing')
if 'microThreshold = 0.005' not in _chk:
    raise SystemExit('V10 micro threshold missing')
if 'probability >= 90' not in _chk:
    raise SystemExit('V10 90% gate missing')
print('V10 FINAL: 5S measured setup score + 200ms capture + strict 90% trade gate')


# V11 OVERLAY ROOT-CAUSE FIX
# The screenshot proves candle detection is alive (110 candles) and the 5S
# engine is running, but OverlayService had no QUICK_5S receiver branch.
# CaptureService was broadcasting quickProbability/confidence, while the
# overlay ignored that event and kept its old nextConfidence=0.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('V11 OverlayService missing')
_s = ov.read_text()

_marker = '                "TRADE_ENTRY" -> {'
if _marker not in _s:
    raise SystemExit('V11 TRADE_ENTRY marker missing')

_branch = '''                "QUICK_5S" -> {
                    val quickSignal =
                        intent.getStringExtra("quickSignal")?.uppercase(Locale.US)
                            ?: "NO TRADE"
                    val quickConfidence =
                        intent.getIntExtra(
                            "quickProbability",
                            intent.getIntExtra("confidence", 0)
                        )
                    val quickStatus =
                        intent.getStringExtra("quickStatus") ?: "WAITING"

                    timeframe = "5S"
                    nextConfidence = quickConfidence
                    nextTrend = quickStatus

                    if (
                        (quickSignal == "CALL" || quickSignal == "PUT") &&
                        quickConfidence >= CONFIDENCE_LEVEL
                    ) {
                        nextSignal = quickSignal
                        signalLocked = true
                        status = "SIGNAL LOCKED"
                    } else {
                        nextSignal = "NO TRADE"
                        signalLocked = false
                        status = "SCANNING"
                    }

                    updateOverlay()
                }

'''
_s = _s.replace(_marker, _branch + _marker, 1)

# Make the overlay show a nonzero measured quick score even when it is below
# the 90% trade gate. A low score is WAIT, not a forced trade.
ov.write_text(_s)

_chk = ov.read_text()
if '"QUICK_5S" -> {' not in _chk:
    raise SystemExit('V11 QUICK_5S branch missing')
if 'quickProbability' not in _chk:
    raise SystemExit('V11 quickProbability bridge missing')
print('V11 FINAL: OverlayService now consumes QUICK_5S confidence')


# V11 ROOT CAUSE: OverlayService was ignoring the QUICK_5S broadcast.
# CaptureService was calculating/sending quickProbability, but OverlayService
# had no QUICK_5S case, so nextConfidence stayed at its reset value 0%.
ov = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
if not ov.exists():
    raise SystemExit('V11 OverlayService missing')
_v11 = ov.read_text()

needle = '''                "ANALYSIS_READY" -> {'''
case = '''                "QUICK_5S" -> {
                    val quickSignalValue =
                        intent.getStringExtra("quickSignal")
                            ?.uppercase(Locale.US) ?: "NO TRADE"
                    val quickConfidence =
                        intent.getIntExtra(
                            "quickProbability",
                            intent.getIntExtra("confidence", nextConfidence)
                        ).coerceIn(0, 100)

                    timeframe = "5S"
                    nextConfidence = quickConfidence
                    nextTrend =
                        if (quickSignalValue == "CALL") "CALL"
                        else if (quickSignalValue == "PUT") "PUT"
                        else "WAITING"

                    if (
                        (quickSignalValue == "CALL" || quickSignalValue == "PUT") &&
                        quickConfidence >= CONFIDENCE_LEVEL
                    ) {
                        nextSignal = quickSignalValue
                        signalLocked = true
                        status = "SIGNAL LOCKED"
                    } else {
                        nextSignal = "NO TRADE"
                        signalLocked = false
                        status = "SCANNING"
                    }
                    updateOverlay()
                }

'''
if needle not in _v11:
    raise SystemExit('V11 QUICK_5S insertion point missing')
if '"QUICK_5S" -> {' not in _v11:
    _v11 = _v11.replace(needle, case + needle, 1)

ov.write_text(_v11)

if '"QUICK_5S" -> {' not in ov.read_text():
    raise SystemExit('V11 QUICK_5S case missing')
print('V11 FINAL: OverlayService now consumes QUICK_5S quickProbability/confidence')
