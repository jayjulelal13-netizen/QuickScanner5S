from pathlib import Path

projects = list(Path('.').rglob('settings.gradle.kts'))
if not projects:
    raise SystemExit('settings.gradle.kts not found')
project = projects[0].parent
candle = project / 'app/src/main/java/com/example/screener/CandleAnalyzer.kt'
cap = project / 'app/src/main/java/com/example/screener/CaptureService.kt'
overlay = project / 'app/src/main/java/com/example/screener/OverlayService.kt'
gradle = project / 'app/build.gradle.kts'
for f in (candle, cap, overlay, gradle):
    if not f.exists():
        raise SystemExit(f'missing {f}')

s = candle.read_text()
for old, new in [
    ('val top = (height * TOP_RATIO).toInt().coerceIn(0, height - 240)', 'val top = (height * 0.12f).toInt().coerceIn(0, height - 240)'),
    ('val bottom = (height * BOTTOM_RATIO).toInt().coerceIn(top + 240, height)', 'val bottom = (height * 0.72f).toInt().coerceIn(top + 240, height)'),
    ('val chartRight = (width * 0.84f).toInt().coerceIn(chartLeft + 180, width - 1)', 'val chartRight = (width * 0.82f).toInt().coerceIn(chartLeft + 180, width - 1)'),
    ('val pitch = if (gaps.size >= 4)', 'val pitch: Double = if (gaps.size >= 4)'),
    ('max(7.0, span / 70.0)', '(if (span / 70.0 > 7.0) span / 70.0 else 7.0)'),
    ('val minDistance = max(4, (pitch * 0.58).roundToInt())', 'val minDistance = max(4, (pitch * 0.52).roundToInt())'),
    ('val halfWindow = max(2, (pitch * 0.38).roundToInt())', 'val halfWindow = max(2, (pitch * 0.32).roundToInt())'),
    ('if (!(leftGap > pitch * 1.85 && rightGap > pitch * 1.85)) {', 'if (!((leftGap.toString().toDoubleOrNull() ?: 0.0) > 12.95 && (rightGap.toString().toDoubleOrNull() ?: 0.0) > 12.95)) {'),
]:
    if old not in s:
        raise SystemExit('detector pattern missing: ' + old)
    s = s.replace(old, new, 1)
candle.write_text(s)

c = cap.read_text()
if 'import android.graphics.Color' not in c:
    lines = c.splitlines()
    insert_at = 0
    while insert_at < len(lines) and lines[insert_at].startswith('package '):
        insert_at += 1
    lines.insert(insert_at, 'import android.graphics.Color')
    c = '\n'.join(lines) + ('\n' if c.endswith('\n') else '')
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
old4 = '''        val detected =
            try {

                CandleAnalyzer
                    .detectVisibleCandles(
                        bitmap
                    )

            } catch (e: Exception) {'''
new4 = '''        // A chart must contain coloured candle pixels spread across the plot area.
        // This blocks icons/buttons from being reported as candles when no chart is visible.
        val chartLeft = (bitmap.width * 0.02f).toInt().coerceAtLeast(0)
        val chartRight = (bitmap.width * 0.82f).toInt().coerceAtMost(bitmap.width - 1)
        val chartTop = (bitmap.height * 0.10f).toInt().coerceAtLeast(0)
        val chartBottom = (bitmap.height * 0.74f).toInt().coerceAtMost(bitmap.height)
        var coloured = 0
        var darkPixels = 0
        var sampledPixels = 0
        var luminanceSum = 0L
        val bins = IntArray(12)
        if (chartRight > chartLeft && chartBottom > chartTop) {
            for (y in chartTop until chartBottom step 4) {
                for (x in chartLeft..chartRight step 3) {
                    val p = bitmap.getPixel(x, y)
                    val r = Color.red(p)
                    val g = Color.green(p)
                    val b = Color.blue(p)
                    val lum = (r * 299 + g * 587 + b * 114) / 1000
                    sampledPixels++
                    luminanceSum += lum.toLong()
                    if (lum <= 80) darkPixels++
                    val green = g >= 80 && g > r + 20 && g > b + 10
                    val red = r >= 80 && r > g + 20 && r > b + 10
                    if (green || red) {
                        coloured++
                        val bin = (((x - chartLeft) * 12) / maxOf(1, chartRight - chartLeft)).coerceIn(0, 11)
                        bins[bin]++
                    }
                }
            }
        }
        val activeBins = bins.count { it >= 3 }
        val darkRatio = darkPixels.toDouble() / maxOf(1, sampledPixels)
        val averageLuminance = luminanceSum.toDouble() / maxOf(1, sampledPixels)
        // Home screen/wallpaper and launcher icons can contain red/green pixels too.
        // A real Quotex-style chart has a predominantly dark, low-luminance plot.
        val chartBackgroundLooksReal = darkRatio >= 0.55 && averageLuminance <= 85.0
        if (coloured < 90 || activeBins < 5 || !chartBackgroundLooksReal) {
            resetWhenChartIsMissing()
            sendCandleCount(0)
            sendStatus("NO_CHART_WAITING")
            return
        }

        val detected =
            try {

                CandleAnalyzer
                    .detectVisibleCandles(
                        bitmap
                    )

            } catch (e: Exception) {'''
if old4 not in c:
    raise SystemExit('chart gate insertion point missing')
c = c.replace(old4, new4, 1)

# Keep the live overlay useful even when there is no CALL/PUT setup yet.
# For NO TRADE, show directional setup strength below the 90% trade gate.
old5 = '''            val liveProbability =
                if (result.signal == "CALL" || result.signal == "PUT") {
                    calculateEmpiricalProbability(
                        candleHistory.takeLast(MAX_HISTORY),
                        result.signal
                    )
                } else {
                    null
                }'''
new5 = '''            val liveProbability =
                if (result.signal == "CALL" || result.signal == "PUT") {
                    result.confidence.coerceIn(0, 100)
                } else {
                    maxOf(result.bullishScore, result.bearishScore).coerceIn(0, 89)
                }'''
if old5 not in c:
    raise SystemExit('live confidence block missing')
c = c.replace(old5, new5, 1)
cap.write_text(c)

# The quick engine broadcasts a dedicated QUICK_5S status. The overlay must consume it.
o = overlay.read_text()
anchor = '''            when (intent.getStringExtra("status")) {
'''
if anchor not in o:
    raise SystemExit('overlay when anchor missing')
if '"QUICK_5S" -> {' not in o:
    insert = '''            when (intent.getStringExtra("status")) {
                "QUICK_5S" -> {
                    val quickSignal = intent.getStringExtra("quickSignal")?.uppercase(Locale.US) ?: "NO TRADE"
                    val quickConfidence = intent.getIntExtra("quickProbability", 0).coerceIn(0, 100)
                    val quickStatus = intent.getStringExtra("quickStatus") ?: "WAITING"
                    nextConfidence = quickConfidence
                    nextSignal = if (quickSignal == "CALL" || quickSignal == "PUT") quickSignal else "NO TRADE"
                    nextTrend = "5S"
                    signalLocked = quickSignal == "CALL" || quickSignal == "PUT"
                    status = quickStatus
                    updateOverlay()
                }
'''
    o = o.replace(anchor, insert, 1)
overlay.write_text(o)

g = gradle.read_text().replace('applicationId = "com.example.screener"', 'applicationId = "com.example.screener.final5s"')
gradle.write_text(g)
print('FINAL 5S candle + engine + live confidence + QUICK_5S overlay fix applied')