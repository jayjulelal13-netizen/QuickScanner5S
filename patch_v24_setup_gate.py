from pathlib import Path
import re

projects = list(Path(".").rglob("settings.gradle.kts"))
if not projects:
    raise SystemExit("V24: settings.gradle.kts not found")

project = projects[0].parent
cap = project / "app/src/main/java/com/example/screener/CaptureService.kt"
if not cap.exists():
    raise SystemExit("V24: CaptureService.kt not found")

c = cap.read_text()

start = c.find("    private fun updateQuick5s(")
end = c.find("    private fun quickHistoricalProbability", start)

if start < 0 or end < 0:
    raise SystemExit("V24: quick engine boundaries not found")

quick = c[start:end]

# Root-cause fix:
# The old 5S engine treated empirical historical win probability as a
# mandatory second gate. That can show e.g. Setup Confidence 93% while
# Win Prob is 14%, producing NO TRADE even though the configured setup
# gate is 90%. Win probability remains diagnostic only.
quick = quick.replace(
    "probability != null &&\n            probability >= MIN_EMPIRICAL_PROBABILITY",
    "confidence >= MIN_CONFIDENCE_TO_QUEUE"
)
quick = quick.replace(
    "probability != null && probability >= MIN_EMPIRICAL_PROBABILITY",
    "confidence >= MIN_CONFIDENCE_TO_QUEUE"
)

# Remove the redundant null check if the gate was split across lines.
quick = re.sub(
    r"probability\s*!=\s*null\s*&&\s*\n?\s*probability\s*>=\s*MIN_EMPIRICAL_PROBABILITY",
    "confidence >= MIN_CONFIDENCE_TO_QUEUE",
    quick
)

# If the quick engine still names the historical value 'probability',
# keep it only for display/calibration and make the actual status use
# the measured setup confidence.
quick = quick.replace(
    'sendQuickStatus(\n                direction,\n                probability ?: 0,',
    'sendQuickStatus(\n                direction,\n                confidence,'
)
quick = quick.replace(
    'sendQuickStatus(\n                if (strong) direction else "NO TRADE",\n                probability ?: 0,',
    'sendQuickStatus(\n                if (strong) direction else "NO TRADE",\n                confidence,'
)

# Some earlier revisions used a direct canTrade block.
# Make sure confidence is the only 90% gate for the quick setup.
quick = re.sub(
    r"val canTrade\s*=\s*\((.*?)\)\s*&&\s*probability\s*!=\s*null\s*&&\s*probability\s*>=\s*MIN_EMPIRICAL_PROBABILITY",
    lambda m: "val canTrade = (" + m.group(1) + ") && confidence >= MIN_CONFIDENCE_TO_QUEUE",
    quick,
    flags=re.S
)

c = c[:start] + quick + c[end:]

# Defensive source-level verification.
new_quick = c[start:end]
if "MIN_EMPIRICAL_PROBABILITY" in new_quick:
    raise SystemExit("V24 VERIFY FAIL: empirical probability is still a trade gate")

if "MIN_CONFIDENCE_TO_QUEUE" not in new_quick:
    raise SystemExit("V24 VERIFY FAIL: 90% setup gate missing")

if "sendQuickStatus" not in new_quick:
    raise SystemExit("V24 VERIFY FAIL: quick status output missing")

cap.write_text(c)
print("V24 OK: 5S trade gate now uses measured Setup Confidence >= 90%; empirical Win Prob is diagnostic only")
