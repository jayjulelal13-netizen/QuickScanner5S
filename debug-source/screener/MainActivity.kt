package com.example.screener

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {

    companion object {
        private const val REQUEST_SCREEN_CAPTURE = 1001

        private const val ACTION_FRAME_STATUS =
            "com.example.screener.FRAME_STATUS"

        private const val ACTION_STOP_CAPTURE =
            "com.example.screener.STOP_CAPTURE"

        private const val ACTION_HIDE_OVERLAY =
            "com.example.screener.HIDE_OVERLAY"

        private const val CONFIDENCE_LEVEL = 90
    }

    private lateinit var signalBox: TextView
    private lateinit var statusText: TextView
    private lateinit var statisticsText: TextView

    private var receiverRegistered = false
    private var captureRunning = false

    private var selectedTimeframe = "1M"

    private var totalAnalyses = 0
    private var confirmedSignals = 0
    private var noTradeSignals = 0

    private var lastTimeframe = "1M"
    private var lastTrend = "WAITING"
    private var lastSignal = "NO TRADE"
    private var lastConfidence = 0
    private var lastCandleId = -1L
    private var lastConfirmed = false

    private var liveRemaining = 0L
    private var liveCandleCount = 0

    private val frameReceiver =
        object : BroadcastReceiver() {

            override fun onReceive(
                context: Context?,
                intent: Intent?
            ) {
                if (intent?.action != ACTION_FRAME_STATUS) {
                    return
                }

                val status =
                    intent.getStringExtra("status") ?: return

                val receivedTimeframe =
                    intent.getStringExtra("timeframe")

                if (!receivedTimeframe.isNullOrBlank()) {
                    lastTimeframe = receivedTimeframe
                }

                when (status) {

                    "CAPTURE_STARTED" -> {
                        captureRunning = true
                        showWaitingForChart()
                    }

                    "PROJECTION_STARTING" -> {
                        setStatus(
                            "SCREEN CAPTURE\nStarting..."
                        )
                    }

                    "PROJECTION_CREATED" -> {
                        setStatus(
                            "PROJECTION READY\n" +
                            "Timeframe: $selectedTimeframe"
                        )
                    }

                    "IMAGE_READER_CREATED" -> {
                        setStatus(
                            "READING SCREEN..."
                        )
                    }

                    "VIRTUAL_DISPLAY_CREATED" -> {
                        setStatus(
                            "SCREEN READY"
                        )
                    }

                    "FRAME_READY" -> {
                        if (!lastSignal.isNullOrEmpty()) {
                            // Keep current result.
                        }
                    }

                    "CANDLES_DETECTED" -> {

                        liveCandleCount =
                            intent.getIntExtra(
                                "count",
                                0
                            )

                        val tf =
                            intent.getStringExtra(
                                "timeframe"
                            ) ?: selectedTimeframe

                        setStatus(
                            "LIVE CHART DETECTED\n" +
                            "Candles: $liveCandleCount\n" +
                            "Timeframe: $tf"
                        )
                    }

                    "CANDLE_DETECTION_WAITING" -> {
                        setStatus(
                            "WAITING FOR REAL CANDLES\n" +
                            "No valid candle sequence yet"
                        )
                    }

                    "CANDLE_RUNNING" -> {

                        liveRemaining =
                            intent.getLongExtra(
                                "remaining",
                                1L
                            )

                        val tf =
                            intent.getStringExtra(
                                "timeframe"
                            ) ?: selectedTimeframe

                        updateLiveSignalBox(
                            liveRemaining,
                            tf
                        )
                    }

                    "HISTORY_WAITING" -> {
                        setStatus(
                            "CANDLE CLOSED\n" +
                            "Not enough completed candles\n" +
                            "Waiting for more history"
                        )
                    }

                    "QUICK_5S" -> {
                        handleQuick5s(intent)
                    }

                    "ANALYSIS_READY" -> {
                        // In 5S QUICK mode the service does not need to
                        // surface the normal 1M boundary result.
                        if (selectedTimeframe != "5S") {
                            handleAnalysis(intent)
                        }
                    }

                    "ANALYSIS_ERROR" -> {
                        setStatus(
                            "ANALYSIS ERROR\n" +
                            "Capture continues\n" +
                            "Waiting for next candle"
                        )
                    }

                    "FRAME_ERROR" -> {
                        setStatus(
                            "FRAME ERROR\n" +
                            "Waiting for next frame..."
                        )
                    }

                    "CAPTURE_ERROR" -> {
                        captureRunning = false
                        setStatus(
                            "CAPTURE ERROR\n" +
                            "Restart screen capture"
                        )
                    }

                    "PROJECTION_ERROR" -> {
                        captureRunning = false
                        setStatus(
                            "PROJECTION ERROR\n" +
                            "Start capture again"
                        )
                    }

                    "CAPTURE_STOPPED" -> {

                        captureRunning = false

                        signalBox.text =
                            "NEXT SIGNAL\n\n" +
                            "NO TRADE\n\n" +
                            "Capture stopped"

                        signalBox.setBackgroundColor(
                            Color.LTGRAY
                        )

                        setStatus(
                            "CAPTURE STOPPED\n" +
                            "Tap START SCREEN CAPTURE"
                        )
                    }
                }
            }
        }

    override fun onCreate(
        savedInstanceState: Bundle?
    ) {
        super.onCreate(savedInstanceState)

        // Keep launcher startup isolated from optional capture/overlay setup.
        // A failure in a permission/receiver check must never close the app.
        try {
            createUI()
        } catch (e: Throwable) {
            showStartupError(e)
            return
        }

        try {
            registerStatusReceiver()
        } catch (_: Throwable) {
            // Receiver is optional until capture starts.
        }

        try {
            showReadyStatus()
        } catch (_: Throwable) {
            setStatus("READY\nTap START SCREEN CAPTURE")
        }
    }

    private fun showStartupError(error: Throwable) {
        val message = error.message?.take(180) ?: error.javaClass.simpleName
        val view = TextView(this).apply {
            text = "BINOMO LIVE SCREENER\n\nSTARTUP ERROR\n\n$message"
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(32, 48, 32, 48)
        }
        setContentView(view)
    }

    private fun createUI() {

        val scroll =
            ScrollView(this)

        val root =
            LinearLayout(this).apply {
                orientation =
                    LinearLayout.VERTICAL

                setPadding(
                    18,
                    18,
                    18,
                    30
                )
            }

        scroll.addView(root)

        val title =
            TextView(this).apply {
                text =
                    "BINOMO LIVE SCREENER"

                textSize = 23f

                gravity =
                    Gravity.CENTER

                setPadding(
                    8,
                    12,
                    8,
                    18
                )
            }

        root.addView(
            title,
            fullWidth()
        )

        signalBox =
            TextView(this).apply {

                text =
                    defaultSignalText()

                textSize = 19f

                gravity =
                    Gravity.CENTER

                setPadding(
                    20,
                    32,
                    20,
                    32
                )

                setBackgroundColor(
                    Color.LTGRAY
                )
            }

        root.addView(
            signalBox,
            fullWidth()
        )

        val timeframeTitle =
            TextView(this).apply {

                text =
                    "SELECT TIMEFRAME"

                textSize = 17f

                gravity =
                    Gravity.CENTER

                setPadding(
                    8,
                    18,
                    8,
                    8
                )
            }

        root.addView(
            timeframeTitle,
            fullWidth()
        )

        val timeframeRow =
            LinearLayout(this).apply {

                orientation =
                    LinearLayout.HORIZONTAL

                gravity =
                    Gravity.CENTER

                setPadding(
                    0,
                    4,
                    0,
                    12
                )
            }

        val button1M =
            createTimeframeButton("1M")

        val button5M =
            createTimeframeButton("5M")

        val button15M =
            createTimeframeButton("15M")

        val button5S =
            createTimeframeButton("5S QUICK")

        timeframeRow.addView(
            button1M,
            equalWidth()
        )

        timeframeRow.addView(
            button5M,
            equalWidth()
        )

        timeframeRow.addView(
            button15M,
            equalWidth()
        )

        timeframeRow.addView(
            button5S,
            equalWidth()
        )

        root.addView(
            timeframeRow,
            fullWidth()
        )

        val selectedText =
            TextView(this).apply {

                text =
                    "Selected: 1M"

                textSize = 16f

                gravity =
                    Gravity.CENTER

                setPadding(
                    5,
                    5,
                    5,
                    15
                )

                tag = "selected_timeframe"
            }

        root.addView(
            selectedText,
            fullWidth()
        )

        val overlayButton =
            Button(this).apply {

                text =
                    "ENABLE OVERLAY"

                setOnClickListener {
                    openOverlayPermission()
                }
            }

        root.addView(
            overlayButton,
            fullWidth()
        )

        val startButton =
            Button(this).apply {

                text =
                    "START SCREEN CAPTURE"

                setOnClickListener {

                    setStatus(
                        "REQUESTING SCREEN CAPTURE...\n" +
                        "Timeframe: $selectedTimeframe"
                    )

                    requestScreenCapture()
                }
            }

        root.addView(
            startButton,
            fullWidth()
        )

        val stopButton =
            Button(this).apply {

                text =
                    "STOP CAPTURE"

                setOnClickListener {
                    stopCapture()
                }
            }

        root.addView(
            stopButton,
            fullWidth()
        )

        val resetButton =
            Button(this).apply {

                text =
                    "RESET SIGNAL"

                setOnClickListener {
                    resetSignal()
                }
            }

        root.addView(
            resetButton,
            fullWidth()
        )

        statisticsText =
            TextView(this).apply {

                text =
                    statisticsString()

                textSize = 16f

                gravity =
                    Gravity.CENTER

                setPadding(
                    10,
                    20,
                    10,
                    20
                )
            }

        root.addView(
            statisticsText,
            fullWidth()
        )

        val info =
            TextView(this).apply {

                text =
                    "LIVE ANALYZER\n\n" +
                    "1M = normal 1-minute trade.\n\n" +
                    "5M / 15M = higher-timeframe analysis.\n\n" +
                    "5S QUICK = keep the Quotex chart on 1M; " +
                    "the app uses live 5-second intrabar movement.\n\n" +
                    "The running candle is NOT used " +
                    "for completed-candle analysis.\n\n" +
                    "Analysis is generated once per " +
                    "selected timeframe candle boundary.\n\n" +
                    "CALL / PUT requires 90%+ confidence.\n\n" +
                    "Below 90% = NO TRADE."

                textSize = 14f

                setPadding(
                    10,
                    10,
                    10,
                    20
                )
            }

        root.addView(
            info,
            fullWidth()
        )

        statusText =
            TextView(this).apply {

                text =
                    "Status: Starting..."

                textSize = 15f

                setPadding(
                    10,
                    15,
                    10,
                    15
                )
            }

        root.addView(
            statusText,
            fullWidth()
        )

        setContentView(scroll)

        updateTimeframeButtons(
            button1M,
            button5M,
            button15M,
            button5S,
            selectedText
        )
    }

    private fun createTimeframeButton(
        timeframe: String
    ): Button {

        return Button(this).apply {

            text = timeframe

            textSize = if (timeframe == "5S QUICK") 12f else 14f
            minWidth = 0
            minimumWidth = 0

            setOnClickListener {

                if (captureRunning) {

                    setStatus(
                        "STOP CAPTURE FIRST\n" +
                        "Then change timeframe"
                    )

                    return@setOnClickListener
                }

                selectedTimeframe =
                    timeframe

                val row =
                    parent as? LinearLayout

                val selectedText =
                    findSelectedTimeframeText()

                if (row != null) {

                    val b1 =
                        row.getChildAt(0) as Button

                    val b5 =
                        row.getChildAt(1) as Button

                    val b15 =
                        row.getChildAt(2) as Button

                    val bQuick =
                        row.getChildAt(3) as Button

                    updateTimeframeButtons(
                        b1,
                        b5,
                        b15,
                        bQuick,
                        selectedText
                    )
                }

                signalBox.text =
                    defaultSignalText()

                setStatus(
                    "TIMEFRAME SELECTED\n" +
                    "$selectedTimeframe\n\n" +
                    when (selectedTimeframe) {
                        "5S" -> "Chart stays on 1M for 5S QUICK"
                        "5M" -> "Set Quotex chart to 5M"
                        "15M" -> "Set Quotex chart to 15M"
                        else -> "Set Quotex chart to 1M"
                    }
                )
            }
        }
    }

    private fun findSelectedTimeframeText():
        TextView? {

        val root =
            signalBox.parent as? ViewGroup
                ?: return null

        for (i in 0 until root.childCount) {

            val child =
                root.getChildAt(i)

            if (
                child is TextView &&
                child.tag ==
                "selected_timeframe"
            ) {
                return child
            }
        }

        return null
    }

    private fun updateTimeframeButtons(
        button1M: Button,
        button5M: Button,
        button15M: Button,
        button5S: Button,
        selectedText: TextView?
    ) {

        button1M.setBackgroundColor(
            if (selectedTimeframe == "1M")
                Color.DKGRAY
            else
                Color.LTGRAY
        )

        button5M.setBackgroundColor(
            if (selectedTimeframe == "5M")
                Color.DKGRAY
            else
                Color.LTGRAY
        )

        button15M.setBackgroundColor(
            if (selectedTimeframe == "15M")
                Color.DKGRAY
            else
                Color.LTGRAY
        )

        button5S.setBackgroundColor(
            if (selectedTimeframe == "5S")
                Color.DKGRAY
            else
                Color.LTGRAY
        )

        button1M.setTextColor(
            if (selectedTimeframe == "1M")
                Color.WHITE
            else
                Color.BLACK
        )

        button5M.setTextColor(
            if (selectedTimeframe == "5M")
                Color.WHITE
            else
                Color.BLACK
        )

        button15M.setTextColor(
            if (selectedTimeframe == "15M")
                Color.WHITE
            else
                Color.BLACK
        )

        button5S.setTextColor(
            if (selectedTimeframe == "5S")
                Color.WHITE
            else
                Color.BLACK
        )

        selectedText?.text =
            when (selectedTimeframe) {
                "5S" -> "Selected: 5S QUICK (Chart: 1M)"
                "5M" -> "Selected: 5M"
                "15M" -> "Selected: 15M"
                else -> "Selected: 1M"
            }
    }

    private fun requestScreenCapture() {

        try {

            val manager =
                getSystemService(
                    MEDIA_PROJECTION_SERVICE
                ) as MediaProjectionManager

            startActivityForResult(
                manager.createScreenCaptureIntent(),
                REQUEST_SCREEN_CAPTURE
            )

        } catch (e: Exception) {

            setStatus(
                "SCREEN CAPTURE ERROR\n" +
                e.message
            )
        }
    }

    @Deprecated(
        "Deprecated in Android API 31"
    )
    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: Intent?
    ) {

        super.onActivityResult(
            requestCode,
            resultCode,
            data
        )

        if (
            requestCode !=
            REQUEST_SCREEN_CAPTURE
        ) {
            return
        }

        if (
            resultCode != RESULT_OK ||
            data == null
        ) {

            setStatus(
                "SCREEN CAPTURE DENIED"
            )

            return
        }

        startCaptureService(
            resultCode,
            data
        )
    }

    private fun startCaptureService(
        resultCode: Int,
        data: Intent
    ) {

        try {

            val serviceIntent =
                Intent(
                    this,
                    CaptureService::class.java
                )

            serviceIntent.action =
                "com.example.screener.START_CAPTURE"

            serviceIntent.putExtra(
                "resultCode",
                resultCode
            )

            serviceIntent.putExtra(
                "data",
                data
            )

            serviceIntent.putExtra(
                "timeframe",
                if (selectedTimeframe == "5S") "1M" else selectedTimeframe
            )

            serviceIntent.putExtra(
                "quickMode",
                selectedTimeframe == "5S"
            )

            if (
                Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.O
            ) {

                startForegroundService(
                    serviceIntent
                )

            } else {

                startService(
                    serviceIntent
                )
            }

            captureRunning = true

            setStatus(
                "CAPTURE SERVICE STARTING...\n" +
                "Timeframe: $selectedTimeframe"
            )

        } catch (e: Exception) {

            captureRunning = false

            setStatus(
                "CAPTURE SERVICE ERROR\n" +
                e.message
            )
        }
    }

    private fun stopCapture() {

        try {

            val intent =
                Intent(
                    this,
                    CaptureService::class.java
                )

            intent.action =
                ACTION_STOP_CAPTURE

            startService(intent)

            // Immediate overlay removal command.
            val hideOverlay =
                Intent(
                    this,
                    OverlayService::class.java
                )

            hideOverlay.action =
                ACTION_HIDE_OVERLAY

            startService(
                hideOverlay
            )

            captureRunning = false

            setStatus(
                "STOPPING CAPTURE..."
            )

        } catch (e: Exception) {

            setStatus(
                "STOP ERROR\n" +
                e.message
            )
        }
    }

    private fun resetSignal() {

        totalAnalyses = 0
        confirmedSignals = 0
        noTradeSignals = 0

        lastTimeframe =
            selectedTimeframe

        lastTrend = "WAITING"
        lastSignal = "NO TRADE"
        lastConfidence = 0
        lastCandleId = -1L
        lastConfirmed = false

        liveRemaining = 0L
        liveCandleCount = 0

        signalBox.text =
            defaultSignalText()

        signalBox.setBackgroundColor(
            Color.LTGRAY
        )

        updateStatistics()

        setStatus(
            "RESET COMPLETE\n" +
            "Waiting for real chart capture..."
        )
    }

    private fun handleQuick5s(
        intent: Intent
    ) {
        if (selectedTimeframe != "5S") return

        val signal = intent.getStringExtra("quickSignal")
            ?.uppercase() ?: "NO TRADE"
        val probability = intent.getIntExtra("quickProbability", 0)
        val samples = intent.getIntExtra("quickSamples", 0)
        val quickStatus = intent.getStringExtra("quickStatus") ?: "WAITING"

        signalBox.text =
            "5S QUICK\n\n" +
            "$signal\n\n" +
            "Win Probability: ${probability}%\n" +
            "Samples: $samples\n" +
            "Chart: 1M\n" +
            "Status: $quickStatus"

        signalBox.setBackgroundColor(
            if (signal == "CALL" || signal == "PUT")
                Color.rgb(190, 240, 190)
            else
                Color.LTGRAY
        )

        setStatus(
            "5S QUICK\n" +
            "Signal: $signal\n" +
            "Win Probability: ${probability}%\n" +
            "Samples: $samples\n" +
            quickStatus
        )
    }

    private fun handleAnalysis(
        intent: Intent
    ) {

        val timeframe =
            intent.getStringExtra(
                "timeframe"
            ) ?: selectedTimeframe

        val trend =
            intent.getStringExtra(
                "trend"
            ) ?: "UNKNOWN"

        val signal =
            intent.getStringExtra(
                "signal"
            )?.uppercase()
                ?: "NO TRADE"

        val confidence =
            intent.getIntExtra(
                "confidence",
                0
            )

        val candleId =
            intent.getLongExtra(
                "candleId",
                -1L
            )

        val confirmed =
            (
                (signal == "CALL" ||
                 signal == "PUT") &&
                confidence >=
                    CONFIDENCE_LEVEL
            )

        totalAnalyses++

        if (confirmed) {
            confirmedSignals++
        } else {
            noTradeSignals++
        }

        lastTimeframe = timeframe
        lastTrend = trend
        lastSignal = signal
        lastConfidence = confidence
        lastCandleId = candleId
        lastConfirmed = confirmed

        val finalSignal =
            if (confirmed) {
                signal
            } else {
                "NO TRADE"
            }

        signalBox.text =
            "LAST ANALYSIS\n\n" +
            "$finalSignal\n\n" +
            "Confidence: $confidence%\n" +
            "Timeframe: $timeframe\n" +
            "Trend: $trend\n" +
            "Candle ID: $candleId\n" +
            "Status: " +
            if (confirmed)
                "CONFIRMED"
            else
                "NO TRADE"

        signalBox.setBackgroundColor(
            if (confirmed) {
                Color.rgb(
                    190,
                    240,
                    190
                )
            } else {
                Color.LTGRAY
            }
        )

        if (confirmed) {

            setStatus(
                "ANALYSIS READY\n" +
                "$timeframe CANDLE CLOSED\n" +
                "SIGNAL: $finalSignal\n" +
                "Confidence: $confidence%\n" +
                "Next: NEW $timeframe CANDLE"
            )

        } else {

            setStatus(
                "ANALYSIS READY\n" +
                "NO TRADE\n" +
                "Confidence: $confidence%\n" +
                "Waiting for next $timeframe candle..."
            )
        }

        updateStatistics()
    }

    private fun updateLiveSignalBox(
        remaining: Long,
        timeframe: String
    ) {

        val maxSeconds =
            when (timeframe) {
                "5M" -> 300L
                "15M" -> 900L
                else -> 60L
            }

        val r =
            remaining.coerceIn(
                1L,
                maxSeconds
            )

        if (lastCandleId == -1L) {

            signalBox.text =
                "LIVE CHART\n\n" +
                "🟢 CANDLE RUNNING\n\n" +
                "Close in: ${r}s\n" +
                "Timeframe: $timeframe\n" +
                "Candles detected: " +
                "$liveCandleCount\n\n" +
                "NO ANALYSIS YET\n" +
                "Waiting for REAL candle close"

            signalBox.setBackgroundColor(
                Color.LTGRAY
            )

            setStatus(
                "LIVE CAPTURE\n" +
                "$timeframe CANDLE RUNNING\n" +
                "Close in: ${r}s"
            )

            return
        }

        signalBox.text =
            "LAST ANALYSIS\n\n" +
            "Signal: " +
            if (lastConfirmed)
                lastSignal
            else
                "NO TRADE" +
            "\n\n" +
            "Confidence: $lastConfidence%\n" +
            "Timeframe: $lastTimeframe\n" +
            "Trend: $lastTrend\n" +
            "Candle ID: $lastCandleId\n\n" +
            "🟢 LIVE CANDLE RUNNING\n" +
            "Close in: ${r}s\n" +
            "NO NEW ANALYSIS"

        signalBox.setBackgroundColor(
            if (lastConfirmed) {
                Color.rgb(
                    190,
                    240,
                    190
                )
            } else {
                Color.LTGRAY
            }
        )

        setStatus(
            "LIVE CAPTURE\n" +
            "$timeframe CANDLE RUNNING\n" +
            "Close in: ${r}s\n" +
            "NO NEW ANALYSIS"
        )
    }

    private fun showWaitingForChart() {

        signalBox.text =
            "LIVE ANALYZER\n\n" +
            "NO CHART ANALYSIS YET\n\n" +
            "Screen capture is running.\n" +
            "Waiting for valid candle sequence...\n\n" +
            "Timeframe: $selectedTimeframe"

        signalBox.setBackgroundColor(
            Color.LTGRAY
        )
    }

    private fun defaultSignalText(): String {

        return (
            "NEXT SIGNAL\n\n" +
            "NO TRADE\n\n" +
            "Confidence: 0%\n" +
            "Timeframe: $selectedTimeframe\n" +
            "Trend: WAITING\n" +
            "Entry: WAITING\n" +
            "Status: WAITING"
        )
    }

    private fun updateStatistics() {

        val rate =
            if (totalAnalyses > 0) {
                confirmedSignals.toFloat() /
                    totalAnalyses.toFloat() *
                    100f
            } else {
                0f
            }

        statisticsText.text =
            "DEMO ANALYSIS STATS\n\n" +
            "Total analyses: $totalAnalyses\n" +
            "Confirmed 90%+: $confirmedSignals\n" +
            "NO TRADE: $noTradeSignals\n" +
            "Confirmation rate: " +
            String.format(
                "%.1f",
                rate
            ) +
            "%"
    }

    private fun statisticsString(): String {

        return (
            "DEMO ANALYSIS STATS\n\n" +
            "Total analyses: 0\n" +
            "Confirmed 90%+: 0\n" +
            "NO TRADE: 0\n" +
            "Confirmation rate: 0.0%"
        )
    }

    private fun setStatus(
        message: String
    ) {
        if (::statusText.isInitialized) {
            statusText.text = message
        }
    }

    private fun showReadyStatus() {

        if (Settings.canDrawOverlays(this)) {

            setStatus(
                "READY\n" +
                "Timeframe: $selectedTimeframe\n" +
                "Tap START SCREEN CAPTURE"
            )

        } else {

            setStatus(
                "OVERLAY PERMISSION REQUIRED\n" +
                "Tap ENABLE OVERLAY"
            )
        }
    }

    private fun registerStatusReceiver() {

        if (receiverRegistered) return

        val filter =
            IntentFilter(
                ACTION_FRAME_STATUS
            )

        try {

            if (
                Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.TIRAMISU
            ) {

                registerReceiver(
                    frameReceiver,
                    filter,
                    Context.RECEIVER_NOT_EXPORTED
                )

            } else {

                @Suppress("DEPRECATION")
                registerReceiver(
                    frameReceiver,
                    filter
                )
            }

            receiverRegistered = true

        } catch (_: Exception) {
            receiverRegistered = false
        }
    }

    private fun openOverlayPermission() {

        if (Settings.canDrawOverlays(this)) {

            startOverlayService()
            return
        }

        try {

            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse(
                        "package:$packageName"
                    )
                )
            )

        } catch (_: Exception) {

            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION
                )
            )
        }
    }

    private fun startOverlayService() {

        try {

            startService(
                Intent(
                    this,
                    OverlayService::class.java
                )
            )

            setStatus(
                "OVERLAY STARTED\n" +
                "Signal display active"
            )

        } catch (e: Exception) {

            setStatus(
                "OVERLAY ERROR\n" +
                e.message
            )
        }
    }

    private fun fullWidth():
        LinearLayout.LayoutParams {

        return LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
    }

    private fun equalWidth():
        LinearLayout.LayoutParams {

        return LinearLayout.LayoutParams(
            0,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            1f
        )
    }

    override fun onDestroy() {

        if (receiverRegistered) {

            try {
                unregisterReceiver(
                    frameReceiver
                )
            } catch (_: Exception) {
            }

            receiverRegistered = false
        }

        super.onDestroy()
    }
}
