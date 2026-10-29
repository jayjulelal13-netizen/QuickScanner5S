from pathlib import Path
import os

root = Path(os.environ["PROJECT_DIR"]) / "app/src/main/java/com/example/screener"
main, cap, ov = (root / x for x in ("MainActivity.kt", "CaptureService.kt", "OverlayService.kt"))
for p in (main, cap, ov):
    if not p.exists(): raise SystemExit("Missing source: " + str(p))

m = main.read_text()
repls = [
('private var selectedTimeframe = "1M"', 'private var selectedTimeframe = "1 MIN"'),
('private var lastTimeframe = "1M"', 'private var lastTimeframe = "1 MIN"'),
('createTimeframeButton("1M")', 'createTimeframeButton("1 MIN")'),
('createTimeframeButton("5M")', 'createTimeframeButton("5 SEC")'),
('createTimeframeButton("15M")', 'createTimeframeButton("10 SEC")'),
('createTimeframeButton("5S QUICK")', 'createTimeframeButton("15 SEC")'),
('selectedTimeframe == "5S QUICK"', 'selectedTimeframe != "1 MIN"'),
('selectedTimeframe != "5S QUICK"', 'selectedTimeframe == "1 MIN"'),
('"5S QUICK" -> "Chart stays on 1M for 5S QUICK"', '"5 SEC" -> "Live chart; 5-second analysis"'),
('"5M" -> "Set Quotex chart to 5M"', '"10 SEC" -> "Live chart; 10-second analysis"'),
('"15M" -> "Set Quotex chart to 15M"', '"15 SEC" -> "Live chart; 15-second analysis"'),
('else -> "Set Quotex chart to 1M"', 'else -> "Live chart; 1-minute analysis"'),
('"5S QUICK" -> "Selected: 5S QUICK (Chart: 1M)"', '"5 SEC" -> "Selected: 5 SEC"'),
('"5M" -> "Selected: 5M"', '"10 SEC" -> "Selected: 10 SEC"'),
('"15M" -> "Selected: 15M"', '"15 SEC" -> "Selected: 15 SEC"'),
('else -> "Selected: 1M"', 'else -> "Selected: 1 MIN"'),
('selectedTimeframe == "1M"', 'selectedTimeframe == "1 MIN"'),
('selectedTimeframe == "5M"', 'selectedTimeframe == "5 SEC"'),
('selectedTimeframe == "15M"', 'selectedTimeframe == "10 SEC"'),
('selectedTimeframe == "5S QUICK"', 'selectedTimeframe == "15 SEC"'),
('textSize = if (timeframe == "5S QUICK") 12f else 14f', 'textSize = 12f'),
('if (selectedTimeframe != "1 MIN") {\n                            handleAnalysis(intent)', 'if (selectedTimeframe == "1 MIN") {\n                            handleAnalysis(intent)'),
('selectedTimeframe == "5S QUICK"', 'selectedTimeframe != "1 MIN"'),
]
for a,b in repls: m = m.replace(a,b)
# Repair title and help text so UI reflects the new choices.
m = m.replace('"BINOMO LIVE SCREENER"', '"QUICKSCANNER 5S"')
m = m.replace('Selected: 1M', 'Selected: 1 MIN')
m = m.replace('1M = normal 1-minute trade.', '1 MIN = one-minute analysis.')
m = m.replace('5M / 15M = higher-timeframe analysis.', '5 SEC / 10 SEC / 15 SEC = short-window analysis.')
m = m.replace('5S QUICK = keep the Quotex chart on 1M; ', '')
m = m.replace('the app uses live 5-second intrabar movement.', 'the app uses live intrabar movement for the selected duration.')
main.write_text(m)

c = cap.read_text()
c = c.replace('        private const val QUICK_BUCKET_MS = 5000L\n', '')
if 'private var quickBucketMs = 5000L' not in c:
    anchor = '    private var quickBucketId = -1L'
    if anchor not in c: raise SystemExit("Quick bucket field not found")
    c = c.replace(anchor, '    private var quickBucketMs = 5000L\n' + anchor, 1)
c = c.replace('QUICK_BUCKET_MS', 'quickBucketMs')
pattern = r'        quickMode\s*=.*?if \(quickMode\) \{\s*selectedTimeframe = "1S"\s*\}'
new = '''        val requestedTimeframe = intent?.getStringExtra("timeframe") ?: "1 MIN"
        quickMode = intent?.getBooleanExtra("quickMode", false) ?: false
        quickBucketMs = when (requestedTimeframe.uppercase(Locale.US)) {
            "5 SEC" -> 5000L
            "10 SEC" -> 10000L
            "15 SEC" -> 15000L
            else -> 5000L
        }
        selectedTimeframe = normalizeTimeframe(if (quickMode) "1S" else requestedTimeframe)'''
c, count = re.subn(pattern, lambda _: new, c, count=1, flags=re.S)
if count == 0 and 'val requestedTimeframe = intent?.getStringExtra("timeframe")' not in c:
    raise SystemExit("CaptureService start-timeframe block not found")
cap.write_text(c)

o = ov.read_text()
o = o.replace('private var timeframe = "5S"', 'private var timeframe = "5 SEC"')
o = o.replace('timeframe = "5S"', 'timeframe = "5 SEC"')
o = o.replace('nextConfidence = strength.coerceAtLeast(90)', 'nextConfidence = strength')
o = o.replace('"5S QUICK\\n" +', '"QUICKSCANNER\\nTIMEFRAME: $timeframe\\n" +')
o = o.replace('"CHART: LINE\\n" +', '"CHART: CANDLE DETECTION\\n" +')
o = o.replace('"MOMENTUM: ${shownConfidence}%" +', '"SETUP STRENGTH: ${shownConfidence}%" +')
o = o.replace('"STATUS: ${if (signalLocked) "LOCKED 5 SEC" else status}\\n" +', '"STATUS: ${if (signalLocked) "SIGNAL LOCKED" else status}\\n" +')
old = '''    private fun updateOverlay() {
        overlayView?.post { overlayView?.text = buildOverlayText() }
    }'''
new = '''    private fun updateOverlay() {
        overlayView?.post {
            val view = overlayView ?: return@post
            view.text = buildOverlayText()
            val signal = if (signalLocked) nextSignal else "NO TRADE"
            val color = when (signal) {
                "CALL" -> Color.rgb(0, 220, 90)
                "PUT" -> Color.rgb(255, 65, 65)
                else -> Color.LTGRAY
            }
            view.setTextColor(color)
            view.background = GradientDrawable().apply {
                setColor(Color.BLACK)
                setStroke(dp(2), color)
                cornerRadius = dp(8).toFloat()
            }
        }
    }'''
if old not in o: raise SystemExit("Overlay update function not found")
o = o.replace(old, new, 1).replace('maxLines = 5', 'maxLines = 7').replace('dp(178),', 'dp(205),')
ov.write_text(o)
print("Applied requested timeframe labels, real 5/10/15-second buckets, and signal colors.")
