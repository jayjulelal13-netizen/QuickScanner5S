package com.example.screener

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast
import java.util.Locale
import kotlin.math.roundToInt

class OverlayService : Service() {

    companion object {
        private const val ACTION_FRAME_STATUS = "com.example.screener.FRAME_STATUS"
        const val ACTION_HIDE_OVERLAY = "com.example.screener.HIDE_OVERLAY"
        private const val CONFIDENCE_LEVEL = 90
    }

    private lateinit var windowManager: WindowManager
    private var overlayView: TextView? = null
    private var receiverRegistered = false

    private var timeframe = "5S"
    private var nextSignal = "NO TRADE"
    private var nextConfidence = 0
    private var nextTrend = "WAITING"
    private var signalLocked = false

    private var activeSignal = "NONE"
    private var activeConfidence = 0
    private var activeEntry = Double.NaN
    private var activeTrade = false

    private var lastEntry = Double.NaN
    private var lastExit = Double.NaN
    private var lastResult = "NONE"

    private var status = "WAITING"
    private var candleCount = 0
    private val recentResults = ArrayDeque<String>(5)

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != ACTION_FRAME_STATUS) return

            timeframe = intent.getStringExtra("timeframe") ?: timeframe

            if (intent.hasExtra("count")) {
                candleCount = intent.getIntExtra("count", candleCount)
            }

            when (intent.getStringExtra("status")) {
                "CAPTURE_STARTED" -> {
                    resetState()
                    timeframe = "5S"
                    recentResults.clear()
                    status = "WAITING"
                    ensureOverlay()
                    updateOverlay()
                }

                "PROJECTION_STARTING", "IMAGE_READER_CREATED", "VIRTUAL_DISPLAY_CREATED",
                "FRAME_READY", "CANDLES_DETECTED", "CANDLE_DETECTION_WAITING", "HISTORY_WAITING",
                "LIVE_ANALYSIS", "CANDLE_RUNNING", "CANDLE_WAITING", "WAITING_NEW_CANDLE",
                "RESULT_WAITING_CANDLE_CONFIRMATION", "ANALYSIS_ERROR", "FRAME_ERROR" -> {
                    if (intent.getStringExtra("status") == "LIVE_ANALYSIS" &&
                        !activeTrade && !signalLocked
                    ) {
                        nextConfidence = intent.getIntExtra("confidence", nextConfidence)
                        nextTrend = intent.getStringExtra("trend") ?: nextTrend
                    }

                    if (!activeTrade && !signalLocked) status = "SCANNING"
                    updateOverlay()
                }

                "ANALYSIS_READY" -> {
                    val signal = intent.getStringExtra("signal")?.uppercase(Locale.US) ?: "NO TRADE"
                    val confidence = intent.getIntExtra("confidence", 0)
                    val trend = intent.getStringExtra("trend") ?: "UNKNOWN"

                    if ((signal == "CALL" || signal == "PUT") && confidence >= CONFIDENCE_LEVEL) {
                        nextSignal = signal
                        nextConfidence = confidence
                        nextTrend = trend
                        signalLocked = true
                        status = "SIGNAL LOCKED"
                    } else {
                        nextSignal = "NO TRADE"
                        nextConfidence = confidence
                        nextTrend = trend
                        signalLocked = false
                        status = "NO TRADE"
                    }
                    updateOverlay()
                }

                "TRADE_ENTRY" -> {
                    val signal = intent.getStringExtra("signal")?.uppercase(Locale.US) ?: "NO TRADE"
                    if (signal != "CALL" && signal != "PUT") return

                    activeSignal = signal
                    activeConfidence = intent.getIntExtra("confidence", nextConfidence)
                    activeEntry = intent.getDoubleExtra("entryPrice", Double.NaN)
                    lastEntry = activeEntry
                    activeTrade = true

                    nextSignal = "NO TRADE"
                    nextConfidence = 0
                    nextTrend = "WAITING"
                    signalLocked = false
                    status = "TRADE RUNNING"
                    updateOverlay()
                }

                "RESULT_READY" -> {
                    lastResult = intent.getStringExtra("result")?.uppercase(Locale.US) ?: "DRAW"
                    lastEntry = intent.getDoubleExtra("entryPrice", lastEntry)
                    lastExit = intent.getDoubleExtra("exitPrice", Double.NaN)

                    val normalized = when (lastResult) {
                        "WIN", "WON" -> "WIN"
                        "LOSS", "LOST" -> "LOSS"
                        else -> "DRAW"
                    }
                    if (recentResults.size >= 5) recentResults.removeFirst()
                    recentResults.addLast(normalized)

                    activeTrade = false
                    activeSignal = "NONE"
                    activeConfidence = 0
                    activeEntry = Double.NaN
                    status = "WAITING"
                    updateOverlay()
                }

                "CAPTURE_STOPPED" -> {
                    removeOverlayNow()
                    resetState()
                }

                "CAPTURE_ERROR", "PROJECTION_ERROR", "VIRTUAL_DISPLAY_ERROR" -> {
                    if (!activeTrade) status = "ERROR"
                    updateOverlay()
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        ensureOverlay()
        registerReceiverSafe()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_HIDE_OVERLAY) {
            removeOverlayNow()
            stopSelf()
            return START_NOT_STICKY
        }
        ensureOverlay()
        updateOverlay()
        return START_STICKY
    }

    private fun resetState() {
        timeframe = "5S"
        nextSignal = "NO TRADE"
        nextConfidence = 0
        nextTrend = "WAITING"
        signalLocked = false
        activeSignal = "NONE"
        activeConfidence = 0
        activeEntry = Double.NaN
        activeTrade = false
        lastEntry = Double.NaN
        lastExit = Double.NaN
        lastResult = "NONE"
        status = "WAITING"
        candleCount = 0
        recentResults.clear()
    }

    private fun ensureOverlay() {
        if (overlayView != null) return

        val background = GradientDrawable().apply {
            setColor(Color.BLACK)
            setStroke(dp(1), Color.rgb(57, 255, 20))
            cornerRadius = dp(8).toFloat()
        }

        overlayView = TextView(this).apply {
            textSize = 11f
            setTextColor(Color.WHITE)
            setBackground(background)
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            includeFontPadding = false
            maxLines = 5
            typeface = android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL)
        }

        val params = WindowManager.LayoutParams(
            dp(178),
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        )

        params.gravity = Gravity.TOP or Gravity.END
        params.x = dp(8)
        params.y = dp(42)

        try {
            windowManager.addView(overlayView, params)
        } catch (_: Exception) {
            overlayView = null
            Toast.makeText(this, "Overlay permission required", Toast.LENGTH_LONG).show()
        }
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).roundToInt()

    private fun buildOverlayText(): String {
        val shownConfidence = when {
            activeTrade -> activeConfidence
            signalLocked -> nextConfidence
            else -> nextConfidence
        }

        val shownStatus = when {
            activeTrade && activeSignal == "CALL" -> "CALL"
            activeTrade && activeSignal == "PUT" -> "PUT"
            signalLocked && nextSignal == "CALL" && nextConfidence >= CONFIDENCE_LEVEL -> "CALL"
            signalLocked && nextSignal == "PUT" && nextConfidence >= CONFIDENCE_LEVEL -> "PUT"
            else -> "WAITING"
        }

        val resultText = if (recentResults.isEmpty()) {
            "-"
        } else {
            val wins = recentResults.count { it == "WIN" }
            val total = recentResults.size
            "$wins/$total"
        }

        return "5S SCANNER\n" +
            "CONFIDENCE: ${shownConfidence}%\n" +
            "CANDLES: $candleCount\n" +
            "STATUS: $shownStatus\n" +
            "RESULT: $resultText"
    }

    private fun formatPrice(value: Double): String {
        if (value.isNaN() || value.isInfinite()) return "WAITING"
        return String.format(Locale.US, "%.2f", value)
    }

    private fun updateOverlay() {
        overlayView?.post { overlayView?.text = buildOverlayText() }
    }

    private fun removeOverlayNow() {
        val view = overlayView ?: return
        overlayView = null
        try { windowManager.removeViewImmediate(view) } catch (_: Exception) {}
    }

    private fun registerReceiverSafe() {
        if (receiverRegistered) return
        val filter = IntentFilter(ACTION_FRAME_STATUS)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("DEPRECATION") registerReceiver(receiver, filter)
            }
            receiverRegistered = true
        } catch (_: Exception) {
            receiverRegistered = false
        }
    }

    override fun onDestroy() {
        if (receiverRegistered) {
            try { unregisterReceiver(receiver) } catch (_: Exception) {}
            receiverRegistered = false
        }
        removeOverlayNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
