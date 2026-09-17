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
    ('val minDistance = max(4, (pitch * 0.58).roundToInt())', 'val minDistance = max(4, (pitch * 0.52).roundToInt())'),
    ('val halfWindow = max(2, (pitch * 0.38).roundToInt())', 'val halfWindow = max(2, (pitch * 0.32).roundToInt())'),
]:
    if old not in s:
        raise SystemExit('detector pattern missing: ' + old)
    s = s.replace(old, new, 1)
candle.write_text(s)

c = cap.read_text()
old = '''        val probability =
            if (direction == "CALL" || direction == "PUT") {
                quickHistoricalProbability(direction)
            } else null'''
new = '''        // 5S confidence is a deterministic setup score, not a claimed win rate.
        // Empirical shadow samples are still collected for testing, but they do
        // not block the scanner from producing a setup score.
        val probability =
            if (direction == "CALL" || direction == "PUT") {
                var score = 30
                if (baseDirection == direction) score += 25
                val edge = if (base != null) {
                    abs(base.bullishScore - base.bearishScore).coerceAtMost(40)
                } else 0
                score += (edge * 0.75).roundToInt()
                score += (microStrength.coerceIn(0.0, 1.0) * 30.0).roundToInt()
                if ((direction == "CALL" && runningCandle.bullish) ||
                    (direction == "PUT" && !runningCandle.bullish)) score += 5
                score.coerceIn(0, 100)
            } else null'''
if old not in c:
    raise SystemExit('engine probability block missing')
c = c.replace(old, new, 1)
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
if old2 not in c:
    raise SystemExit('engine gate block missing')
c = c.replace(old2, new2, 1)
old3 = '''                if (probability == null)
                    "WAIT - 5S CALIBRATION (90% GATE)"
                else if (cooldown || !freshSetup)'''
new3 = '''                if (probability == null)
                    "WAIT - 5S SETUP"
                else if (probability < 90)
                    "WAIT - 90% SETUP"
                else if (cooldown || !freshSetup)'''
if old3 not in c:
    raise SystemExit('engine status block missing')
c = c.replace(old3, new3, 1)
cap.write_text(c)

g = gradle.read_text().replace('applicationId = "com.example.screener"', 'applicationId = "com.example.screener.final5s"')
gradle.write_text(g)
print('FINAL 5S candle + engine patch applied')
