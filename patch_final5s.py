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
candle.write_text(s)

c = cap.read_text()
old = '''        val probability =
            if (direction == "CALL" || direction == "PUT") {
                quickHistoricalProbability(direction)
            } else null'''
new = '''        // 5S confidence is a deterministic setup score, not a claimed win rate.
        val probability =
            if (direction == "CALL" || direction == "PUT") {
                var score = 30
                if (baseDirection == direction) score += 25
                score += (microStrength.coerceIn(0.0, 1.0) * 30.0).roundToInt()
                if ((direction == "CALL" && runningCandle.bullish) ||
                    (direction == "PUT" && !runningCandle.bullish)) score += 5
                score.coerceIn(0, 100)
            } else null'''
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
print('CANDLE_LINES_1170_1220')
for n in range(1170, min(1220, len(lines)) + 1):
    print(f'{n}: {lines[n-1]}')
print('FINAL 5S patch applied')
