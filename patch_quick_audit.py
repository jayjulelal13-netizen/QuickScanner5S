#!/usr/bin/env python3
from pathlib import Path
import os

target = Path(os.environ["PROJECT_DIR"]) / "app/src/main/java/com/example/screener/CaptureService.kt"
s = target.read_text(encoding="utf-8")

anchor = '    private var quickLastResult = "WAITING FOR SETTLEMENT"\n'
state = '''    private var quickAuditDirection = "NONE"
    private var quickAuditEntry = Double.NaN
    private var quickAuditStartedAt = 0L
    private var quickAuditDetails = ""
'''
if "private var quickAuditDirection" not in s:
    if anchor not in s: raise SystemExit("Audit state insertion anchor missing")
    s = s.replace(anchor, anchor + state, 1)

settle_anchor = '''            quickLastResult = when {
                price == quickSignalEntry -> "DRAW"
                won -> "WIN"
                else -> "LOSS"
            }'''
settle_add = settle_anchor + '''
            appendQuickAudit(
                direction = quickAuditDirection,
                entry = quickAuditEntry,
                exit = price,
                result = quickLastResult,
                startedAt = quickAuditStartedAt,
                details = quickAuditDetails
            )
            quickAuditDirection = "NONE"
            quickAuditEntry = Double.NaN
            quickAuditStartedAt = 0L
            quickAuditDetails = ""'''
if "appendQuickAudit(" not in s:
    if settle_anchor not in s: raise SystemExit("Settlement insertion anchor missing")
    s = s.replace(settle_anchor, settle_add, 1)

signal_anchor = '''            quickSignalEntry = price
            quickActiveUntilBucket = nowBucket + 1L'''
signal_add = '''            quickSignalEntry = price
            quickAuditDirection = direction
            quickAuditEntry = price
            quickAuditStartedAt = System.currentTimeMillis()
            quickAuditDetails = quickOverlayDetails
            quickActiveUntilBucket = nowBucket + 1L'''
if "quickAuditStartedAt = System.currentTimeMillis()" not in s:
    if signal_anchor not in s: raise SystemExit("Signal entry insertion anchor missing")
    s = s.replace(signal_anchor, signal_add, 1)

if "private fun appendQuickAudit(" not in s:
    method = r'''
    private fun appendQuickAudit(
        direction: String,
        entry: Double,
        exit: Double,
        result: String,
        startedAt: Long,
        details: String
    ) {
        if (direction != "CALL" && direction != "PUT") return
        val stamp = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US)
            .format(java.util.Date(startedAt))
        fun csv(value: String): String = "\"" + value.replace("\"", "\"\"")
            .replace("\n", " ").replace("\r", " ") + "\""
        val row = listOf(
            csv(stamp), direction, entry.toString(), exit.toString(), result,
            csv("APP_PROXY_NEXT_BUCKET"), csv(details)
        ).joinToString(",")
        val prefsKey = "quick_signal_audit_csv"
        val header = "timestamp,direction,entry_price,exit_price,app_proxy_result,result_type,setup_details"
        val old = probabilityPrefs.getString(prefsKey, header) ?: header
        val rows = (old.lines().filter { it.isNotBlank() && it != header } + row).takeLast(100)
        probabilityPrefs.edit().putString(prefsKey, (listOf(header) + rows).joinToString("\n")).apply()
    }

'''
    marker = "    private fun updateQuick5s("
    idx = s.find(marker)
    if idx < 0: raise SystemExit("Audit method insertion point missing")
    s = s[:idx] + method + s[idx:]

target.write_text(s, encoding="utf-8")
print("Persistent audit log added: last 100 settled CALL/PUT signals.")
