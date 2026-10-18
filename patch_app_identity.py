#!/usr/bin/env python3
import os, re
from pathlib import Path

project = Path(os.environ["PROJECT_DIR"])
gradle_files = [project / "app/build.gradle.kts", project / "app/build.gradle"]
gradle = next((p for p in gradle_files if p.exists()), None)
if gradle is None:
    raise SystemExit("App Gradle file not found")
text = gradle.read_text(encoding="utf-8")
pattern = r'applicationId\s*(?:=\s*)?["\']([^"\']+)["\']'
match = re.search(pattern, text)
if not match:
    raise SystemExit("Could not find applicationId; refusing unsafe blind edit")
old_id = match.group(1)
new_id = "com.example.quickscanner5s"
if old_id == new_id:
    print("Unique applicationId already set")
else:
    text = text[:match.start(1)] + new_id + text[match.end(1):]
    gradle.write_text(text, encoding="utf-8")
    print(f"Changed applicationId: {old_id} -> {new_id}")

manifest = project / "app/src/main/AndroidManifest.xml"
m = manifest.read_text(encoding="utf-8")
if 'android:label="QuickScanner5S"' not in m:
    m2, count = re.subn(r'android:label="[^"]*"', 'android:label="QuickScanner5S"', m, count=1)
    if count:
        manifest.write_text(m2, encoding="utf-8")
        print("Set launcher label to QuickScanner5S")
    else:
        # Prefer application label; add if none exists.
        m2, count = re.subn(r'<application\b', '<application android:label="QuickScanner5S"', m, count=1)
        if not count:
            raise SystemExit("Could not safely set app label")
        manifest.write_text(m2, encoding="utf-8")
else:
    print("App label already set")
