from pathlib import Path
import re
import os

project = Path(os.environ["PROJECT_DIR"])
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
analyzer = project / "app/src/main/java/com/example/screener/CandleAnalyzer.kt"
main = project / "app/src/main/java/com/example/screener/MainActivity.kt"

for p in (cap, analyzer, main):
    if not p.exists():
        raise SystemExit("V13 required source missing: " + str(p))

s = cap.read_text()

anchor = """        val currentRunningCandle =
            detected.last()

        val nowMillis ="""
insert = """        val currentRunningCandle =
            detected.last()

        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V13 quick activity update failed", e)
            }
        }

        val nowMillis ="""
if "V13 quick activity update failed" not in s:
    if anchor not in s:
        raise SystemExit("V13 per-frame insertion point missing")
    s = s.replace(anchor, insert, 1)

old = """        if (quickMode) {
            try {
                updateQuick5s(detected.last())
            } catch (e: Exception) {
                Log.e(TAG, "Legacy quick engine error", e)
            }
        }"""
s = s.replace(old, "", 1)

s = re.sub(
    r'((?:private\s+)?(?:const\s+)?val\s+FRAME_INTERVAL\s*=\s*)\d+(?:L)?',
    r'\g<1>200L',
    s,
    count=1
)
cap.write_text(s)

s = cap.read_text()
if "private var quickBucketOpen" not in s:
    marker = "private var quickLastClose = Double.NaN"
    if marker not in s:
        raise SystemExit("V13 quick state anchor missing")
    s = s.replace(
        marker,
        marker + """
    private var quickBucketOpen = Double.NaN
    private var quickBucketClose = Double.NaN
    private var quickLastSampleBucket = -1L""",
        1
    )
    cap.write_text(s)

assert "V13 quick activity update failed" in cap.read_text()
assert "updateQuick5s(currentRunningCandle)" in cap.read_text()
assert "200L" in cap.read_text()
print("V13 CLEAN OK: per-frame 5S feed + 200ms capture + quick bucket state")
