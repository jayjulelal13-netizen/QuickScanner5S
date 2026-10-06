from pathlib import Path

files = []
for p in Path("build_project").rglob("OverlayService.kt"):
    files.append(p)
if not files:
    raise SystemExit("OverlayService.kt not found under build_project")

for target in files:
    src = target.read_text(encoding="utf-8")
    if "private var chartAvailable = false" not in src:
        src = src.replace("private var signalLocked = false",
                          "private var signalLocked = false\n    private var chartAvailable = false", 1)
    src = src.replace('"CAPTURE_STARTED" -> {\n                    resetState()',
                      '"CAPTURE_STARTED" -> {\n                    chartAvailable = false\n                    resetState()', 1)
    src = src.replace('"CAPTURE_STOPPED" -> {\n                    removeOverlayNow()',
                      '"CAPTURE_STOPPED" -> {\n                    chartAvailable = false\n                    removeOverlayNow()', 1)
    src = src.replace('"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {',
                      '"CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {\n                    chartAvailable = false', 1)
    target.write_text(src, encoding="utf-8")
print("CHART-GATE base patch applied to", len(files), "OverlayService file(s)")
