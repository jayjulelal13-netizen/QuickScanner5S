package com.example.screener

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class CaptureService : Service() {

    companion object {

        private const val TAG = "BinomoCapture"

        private const val CHANNEL_ID =
            "live_screener"

        private const val NOTIFICATION_ID = 10

        private const val ACTION_STATUS =
            "com.example.screener.FRAME_STATUS"

        const val STOP_CAPTURE =
            "com.example.screener.STOP_CAPTURE"

        /*
         * One processed frame per second.
         */
        private const val FRAME_INTERVAL = 200L

        private const val MIN_HISTORY = 5
        private const val MAX_HISTORY = 300

        /*
         * FINAL SIGNAL:
         *
         * Signal is generated ONLY in the final 2 seconds
         * of the CURRENT candle.
         *
         * That signal belongs to the NEXT candle.
         */
        private const val SIGNAL_WINDOW_SECONDS = 2L

        /*
         * Detector values are screen-relative.
         * These are NOT broker prices.
         */
        private const val CANDLE_MATCH_TOLERANCE = 3.0

        /*
         * Used only to detect whether the rightmost candle
         * is genuinely different from the previous running candle.
         */
        private const val NEW_CANDLE_MIN_DIFFERENCE = 1.0
    }

    private val mainHandler =
        Handler(Looper.getMainLooper())

    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null

    private var captureThread: HandlerThread? = null
    private var captureHandler: Handler? = null

    @Volatile
    private var running = false

    private var frameCount = 0
    private var lastCaptureTime = 0L

    // ============================================================
    // TIMEFRAME
    // ============================================================

    private var selectedTimeframe = "1M"

    // 5S QUICK is an app-derived 5-second mode running on a 1M Quotex chart.
    // quickMode controls the separate quick overlay/engine.
    private var quickMode = false

    /*
     * Current real-time period according to wall clock.
     */
    private var currentPeriodId = -1L

    /*
     * Source candle for which final signal was generated.
     *
     * Example:
     * currentPeriodId = 100
     * signalPeriodId = 100
     *
     * Trade belongs to 101.
     */
    private var lastSignalPeriodId = -1L

    /*
     * Anti-repeat protection: after a confirmed CALL/PUT, require
     * at least two complete new candles before another signal can
     * be issued. This prevents back-to-back entries in the same
     * short-term market move.
     */
    private var lastConfirmedSignalPeriodId = -1L
    private var lastConfirmedSignal = "NO TRADE"
    private val MIN_SIGNAL_GAP_CANDLES = 3L
    private val MIN_CONFIDENCE_TO_QUEUE = 90

        // Empirical probability gates. These are measured from completed
        // trades/backtests, not converted from the analyzer quality score.
        private val MIN_EMPIRICAL_SAMPLES = 30
        private val MIN_EMPIRICAL_PROBABILITY = 90

        // 5-second quick mode uses the same 1M chart and derives a live
        // intrabar move from successive screen frames. No 15s/30s chart
        // selection is required.
        private val QUICK_BUCKET_MS = 5000L
        private val QUICK_COOLDOWN_BUCKETS = 2L

    private var lastVisibleSignature = ""

    private val candleHistory =
        mutableListOf<CandleAnalyzer.DetectedCandle>()

    /*
     * Last rightmost candle observed.
     *
     * IMPORTANT:
     * This is updated continuously so that at the boundary
     * we can determine whether a NEW candle actually appeared.
     */
    private var previousRunningCandle:
        CandleAnalyzer.DetectedCandle? = null

    private var previousRunningCandleSignature = ""

    /*
     * ============================================================
     * NEW PERIOD WAIT STATE
     * ============================================================
     *
     * When wall-clock period changes, we DO NOT immediately
     * assume that the chart detector has already switched
     * to the new candle.
     *
     * We keep checking until the new rightmost candle is
     * actually visible.
     */
    private var waitingForNewCandle = false

    private var pendingPeriodId = -1L

    private var pendingOldPeriodId = -1L

    // ============================================================
    // QUEUED SIGNAL
    // ============================================================

    private var queuedSignal = "NO TRADE"
    private var queuedConfidence = 0
    private var queuedTrend = "WAITING"

    /*
     * This is the CURRENT source candle period.
     * Trade belongs to queuedSignalPeriodId + 1.
     */
    private var queuedSignalPeriodId = -1L

    // ============================================================
    // ACTIVE TRADE
    // ============================================================

    private var activeSignal = "NO TRADE"
    private var activeConfidence = 0

    /*
     * Exact candle period being traded.
     */
    private var activeTradePeriodId = -1L

    /*
     * Entry = OPEN of exact trade candle.
     */
    private var activeEntryPrice = Double.NaN

    /*
     * Snapshot only for candle identity validation.
     */
    private var activeEntryHigh = Double.NaN
    private var activeEntryLow = Double.NaN

    private var activeTradeCandleSignature = ""

    private var activeTradeStarted = false

    // ============================================================
    // RESULT
    // ============================================================

    private var lastResult = "NONE"
    private var lastResultSignal = "NONE"

    private var lastResultEntry = Double.NaN
    private var lastResultExit = Double.NaN

    private var wins = 0
    private var losses = 0
    private var draws = 0

    // ============================================================
    // CONSERVATIVE RISK FILTER (DEMO ONLY)
    // ============================================================
    // After one loss, block the next candle.
    // After two consecutive losses, block the next 3 candles.
    private var consecutiveLosses = 0
    private var cooldownPeriodsRemaining = 0

    // ============================================================
    // 5-SECOND QUICK SETUP
    // ============================================================
    private data class QuickPressureCandle(val bucket: Long, val open: Double, var high: Double, var low: Double, var close: Double)
    private var quickPressureCandle: QuickPressureCandle? = null
    private val quickPressureHistory = mutableListOf<QuickPressureCandle>()

    private var quickBucketId = -1L
    private var quickLastClose = Double.NaN
    private var quickPrevFrameClose = Double.NaN
    private var quickBucketOpen = Double.NaN
    private var quickBucketClose = Double.NaN
    private var quickLastSampleBucket = -1L
    private var quickLastSignalBucket = -1L
    private var quickSignal = "NO TRADE"
    private var quickSignalEntry = Double.NaN
    private var quickSignalDirection = "NONE"
    private var quickActiveUntilBucket = -1L
    private var quickWins = 0
    private var quickLosses = 0
    private var quickLastSetupKey = ""
    private var quickLastSetupBucket = -1L

    private var lineSignalDirection = "NONE"
    private var lineSignalEntryY = Double.NaN
    private var lineSignalUntilMs = 0L
    private var lineLastSignalMs = 0L
    private val lineSamples = ArrayDeque<Pair<Long, Double>>()

    // Shadow 5-second observations build the empirical calibration before
    // any real 5-second signal is allowed through the 90% gate.
    private var quickShadowDirection = "NONE"
    private var quickShadowEntry = Double.NaN
    private var quickShadowUntilBucket = -1L

    private val probabilityPrefs by lazy {
        getSharedPreferences("probability_calibration_v10", Context.MODE_PRIVATE)
    }

    /*
     * Prevent duplicate result.
     */
    private var resultProcessedPeriodId = -1L

    // ============================================================
    // PROJECTION CALLBACK
    // ============================================================

    private val projectionCallback =
        object : MediaProjection.Callback() {

            override fun onStop() {

                Log.d(
                    TAG,
                    "MediaProjection stopped"
                )

                if (running) {
                    sendStatus(
                        "CAPTURE_STOPPED"
                    )
                }

                releaseCapture()
                stopForegroundSafe()
                stopSelf()
            }
        }

    // ============================================================
    // CREATE
    // ============================================================

    override fun onCreate() {

        super.onCreate()

        createNotificationChannel()
        startCaptureThread()
    }

    private fun startCaptureThread() {

        if (captureThread != null) {
            return
        }

        captureThread =
            HandlerThread(
                "BinomoCaptureThread"
            ).also {

                it.start()

                captureHandler =
                    Handler(it.looper)
            }
    }

    private fun stopCaptureThread() {

        try {
            captureHandler
                ?.removeCallbacksAndMessages(null)
        } catch (_: Exception) {
        }

        captureHandler = null

        try {
            captureThread?.quitSafely()
        } catch (_: Exception) {
        }

        captureThread = null
    }

    // ============================================================
    // START COMMAND
    // ============================================================

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {

        /*
         * STOP immediately.
         */
        if (
            intent?.action ==
            STOP_CAPTURE
        ) {

            sendStatus(
                "CAPTURE_STOPPED"
            )

            releaseCapture()
            stopForegroundSafe()
            stopSelf()

            return START_NOT_STICKY
        }

        quickMode =
            intent?.getBooleanExtra("quickMode", false) ?: false

        selectedTimeframe =
            normalizeTimeframe(
                intent?.getStringExtra("timeframe") ?: "1M"
            )

        // 5S QUICK is an app-derived 5-second mode. Binomo 5ST requires a 1-second broker chart; quickMode observes the
        // live 1-second screen frames and derives the 5-second demo window.
        if (quickMode) {
            selectedTimeframe = "1S"
        }

        try {

            startForegroundNotification()

        } catch (e: Exception) {

            Log.e(
                TAG,
                "Foreground start failed",
                e
            )

            sendStatus(
                "CAPTURE_ERROR"
            )

            stopSelf()

            return START_NOT_STICKY
        }

        val resultCode =
            intent?.getIntExtra(
                "resultCode",
                Activity.RESULT_CANCELED
            )
                ?: Activity.RESULT_CANCELED

        val data =
            getProjectionIntent(intent)

        if (
            resultCode != Activity.RESULT_OK ||
            data == null
        ) {

            sendStatus(
                "PROJECTION_ERROR"
            )

            stopForegroundSafe()
            stopSelf()

            return START_NOT_STICKY
        }

        releaseCapture()

        resetAnalysisState()

        startCapture(
            resultCode,
            data
        )

        return START_NOT_STICKY
    }

    // ============================================================
    // RESET
    // ============================================================

    private fun resetAnalysisState() {

        frameCount = 0
        lastCaptureTime = 0L

        quickBucketId = -1L
        quickPressureCandle = null
        quickPressureHistory.clear()
        quickLastClose = Double.NaN
        quickLastSignalBucket = -1L
        quickSignal = "NO TRADE"
        quickSignalEntry = Double.NaN
        quickSignalDirection = "NONE"
        quickActiveUntilBucket = -1L
        quickShadowDirection = "NONE"
        quickShadowEntry = Double.NaN
        quickShadowUntilBucket = -1L
        quickLastSetupKey = ""
        quickLastSetupBucket = -1L

        lineSignalDirection = "NONE"
        lineSignalEntryY = Double.NaN
        lineSignalUntilMs = 0L
        lineLastSignalMs = 0L
        lineSamples.clear()

        currentPeriodId = -1L
        lastSignalPeriodId = -1L

        lastVisibleSignature = ""

        candleHistory.clear()

        previousRunningCandle = null
        previousRunningCandleSignature = ""

        waitingForNewCandle = false
        pendingPeriodId = -1L
        pendingOldPeriodId = -1L

        queuedSignal = "NO TRADE"
        queuedConfidence = 0
        queuedTrend = "WAITING"
        queuedSignalPeriodId = -1L

        activeSignal = "NO TRADE"
        activeConfidence = 0
        activeTradePeriodId = -1L

        activeEntryPrice = Double.NaN
        activeEntryHigh = Double.NaN
        activeEntryLow = Double.NaN

        activeTradeCandleSignature = ""

        activeTradeStarted = false

        lastResult = "NONE"
        lastResultSignal = "NONE"

        lastResultEntry = Double.NaN
        lastResultExit = Double.NaN

        wins = 0
        losses = 0
        draws = 0

        consecutiveLosses = 0
        cooldownPeriodsRemaining = 0

        quickBucketId = -1L
        quickPressureCandle = null
        quickPressureHistory.clear()
        quickLastClose = Double.NaN
        quickLastSignalBucket = -1L
        quickSignal = "NO TRADE"
        quickSignalEntry = Double.NaN
        quickSignalDirection = "NONE"
        quickActiveUntilBucket = -1L
        quickLastSetupKey = ""
        quickLastSetupBucket = -1L
        quickShadowDirection = "NONE"
        quickShadowEntry = Double.NaN
        quickShadowUntilBucket = -1L
        quickWins = probabilityPrefs.getInt("quick_wins", 0)
        quickLosses = probabilityPrefs.getInt("quick_losses", 0)

        resultProcessedPeriodId = -1L
    }

    // ============================================================
    // TIMEFRAME
    // ============================================================

    private fun normalizeTimeframe(
        value: String
    ): String {

        return when (
            value.trim().uppercase()
        ) {

            "5M",
            "5 MIN",
            "5MIN",
            "5 MINUTE" ->
                "5M"

            "15M",
            "15 MIN",
            "15MIN",
            "15 MINUTE" ->
                "15M"

            "5S",
            "5 SEC",
            "5SEC",
            "5 SECOND",
            "5 SECONDS",
            "5S QUICK" ->
                "5S"

            else ->
                "1M"
        }
    }

    private fun timeframeMinutes(): Long {

        return when (selectedTimeframe) {

            "5M" -> 5L
            "15M" -> 15L
            "5S" -> 0L

            else -> 1L
        }
    }

    private fun timeframePeriodMillis(): Long {

        return when (selectedTimeframe) {
            "5S" -> 5_000L
            else -> timeframeMinutes() * 60_000L
        }
    }

    private fun currentPeriod(
        now: Long
    ): Long {

        // 5S QUICK is NOT a real 5-second broker candle.
        // The broker/chart stays on 1M and the quick engine observes
        // live movement in 5-second buckets. Therefore the normal
        // candle lifecycle must remain 1M while quickMode is active.
        val periodMs =
            if (quickMode) 60_000L else timeframePeriodMillis()

        return now / periodMs
    }

    private fun secondsToNextBoundary(): Long {

        // In 5S QUICK, the 5-second timing belongs exclusively to
        // updateQuick5s(). Do not make the main candle engine switch
        // to a 5-second candle lifecycle.
        val periodMs =
            if (quickMode) 60_000L else timeframePeriodMillis()

        val now =
            System.currentTimeMillis()

        val next =
            (
                now / periodMs + 1L
            ) * periodMs

        return (
            (
                next - now + 999L
            ) / 1000L
        ).coerceIn(
            1L,
            if (quickMode) 60L else if (selectedTimeframe == "5S") 5L else timeframeMinutes() * 60L
        )
    }

    // ============================================================
    // NOTIFICATION
    // ============================================================

    private fun createNotificationChannel() {

        if (
            Build.VERSION.SDK_INT >=
            Build.VERSION_CODES.O
        ) {

            val manager =
                getSystemService(
                    Context.NOTIFICATION_SERVICE
                ) as NotificationManager

            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Live Screener",
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
    }

    private fun startForegroundNotification() {

        val text =
            "$selectedTimeframe candle capture running"

        val notification =
            if (
                Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.O
            ) {

                Notification.Builder(
                    this,
                    CHANNEL_ID
                )
                    .setContentTitle(
                        "BINOMO LIVE SCREENER"
                    )
                    .setContentText(text)
                    .setSmallIcon(
                        android.R.drawable.ic_menu_view
                    )
                    .setOngoing(true)
                    .build()

            } else {

                @Suppress("DEPRECATION")
                Notification.Builder(this)
                    .setContentTitle(
                        "BINOMO LIVE SCREENER"
                    )
                    .setContentText(text)
                    .setSmallIcon(
                        android.R.drawable.ic_menu_view
                    )
                    .setOngoing(true)
                    .build()
            }

        if (
            Build.VERSION.SDK_INT >=
            Build.VERSION_CODES.Q
        ) {

            startForeground(
                NOTIFICATION_ID,
                notification,
                android.content.pm.ServiceInfo
                    .FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )

        } else {

            startForeground(
                NOTIFICATION_ID,
                notification
            )
        }
    }

    // ============================================================
    // PROJECTION
    // ============================================================

    private fun getProjectionIntent(
        intent: Intent?
    ): Intent? {

        if (intent == null) {
            return null
        }

        return if (
            Build.VERSION.SDK_INT >=
            Build.VERSION_CODES.TIRAMISU
        ) {

            intent.getParcelableExtra(
                "data",
                Intent::class.java
            )

        } else {

            @Suppress("DEPRECATION")
            intent.getParcelableExtra(
                "data"
            )
        }
    }

    private fun startCapture(
        resultCode: Int,
        data: Intent
    ) {

        try {

            sendStatus(
                "PROJECTION_STARTING"
            )

            val manager =
                getSystemService(
                    Context.MEDIA_PROJECTION_SERVICE
                ) as MediaProjectionManager

            projection =
                manager.getMediaProjection(
                    resultCode,
                    data
                )

            if (projection == null) {

                sendStatus(
                    "PROJECTION_ERROR"
                )

                stopForegroundSafe()
                stopSelf()

                return
            }

            projection?.registerCallback(
                projectionCallback,
                mainHandler
            )

            val metrics =
                resources.displayMetrics

            val screenWidth =
                metrics.widthPixels

            val screenHeight =
                metrics.heightPixels

            val densityDpi =
                metrics.densityDpi

            if (
                screenWidth <= 0 ||
                screenHeight <= 0
            ) {

                sendStatus(
                    "DISPLAY_ERROR"
                )

                releaseCapture()
                stopForegroundSafe()
                stopSelf()

                return
            }

            /*
             * Full width up to 1080.
             */
            val captureWidth =
                minOf(
                    screenWidth,
                    1080
                )

            val captureHeight =
                (
                    screenHeight.toFloat() *
                        captureWidth.toFloat() /
                        screenWidth.toFloat()
                )
                    .roundToInt()
                    .coerceAtLeast(1)

            imageReader =
                ImageReader.newInstance(
                    captureWidth,
                    captureHeight,
                    PixelFormat.RGBA_8888,
                    3
                )

            sendStatus(
                "IMAGE_READER_CREATED"
            )

            val readerHandler =
                captureHandler
                    ?: mainHandler

            imageReader?.setOnImageAvailableListener(
                { reader ->
                    processLatestImage(reader)
                },
                readerHandler
            )

            virtualDisplay =
                projection?.createVirtualDisplay(
                    "BinomoScreenCapture",
                    captureWidth,
                    captureHeight,
                    densityDpi,
                    DisplayManager
                        .VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    imageReader?.surface,
                    null,
                    readerHandler
                )

            if (virtualDisplay == null) {

                sendStatus(
                    "VIRTUAL_DISPLAY_ERROR"
                )

                releaseCapture()
                stopForegroundSafe()
                stopSelf()

                return
            }

            sendStatus(
                "VIRTUAL_DISPLAY_CREATED"
            )

            running = true

            sendStatus(
                "CAPTURE_STARTED"
            )

        } catch (e: Exception) {

            Log.e(
                TAG,
                "Start capture error",
                e
            )

            sendStatus(
                "CAPTURE_ERROR"
            )

            releaseCapture()
            stopForegroundSafe()
            stopSelf()
        }
    }

    // ============================================================
    // IMAGE
    // ============================================================

    private fun processLatestImage(
        reader: ImageReader
    ) {

        if (!running) {
            return
        }

        val image =
            try {

                reader.acquireLatestImage()

            } catch (_: Exception) {

                null
            }

        if (image == null) {
            return
        }

        try {

            frameCount++

            val callbackFrame =
                frameCount

            val now =
                SystemClock.elapsedRealtime()

            if (
                now - lastCaptureTime <
                FRAME_INTERVAL
            ) {
                return
            }

            lastCaptureTime = now

            sendFrameStatus(
                callbackFrame
            )

            val plane =
                image.planes.firstOrNull()
                    ?: return

            val buffer =
                plane.buffer

            val pixelStride =
                plane.pixelStride

            val rowStride =
                plane.rowStride

            if (
                pixelStride <= 0 ||
                rowStride <= 0
            ) {
                return
            }

            val rowPadding =
                rowStride -
                    pixelStride *
                    image.width

            val bitmapWidth =
                image.width +
                    rowPadding /
                    pixelStride

            if (
                bitmapWidth <= 0 ||
                image.height <= 0
            ) {
                return
            }

            val bitmap =
                try {

                    Bitmap.createBitmap(
                        bitmapWidth,
                        image.height,
                        Bitmap.Config.ARGB_8888
                    )

                } catch (
                    _: OutOfMemoryError
                ) {

                    sendStatus(
                        "FRAME_ERROR"
                    )

                    return
                }

            try {

                buffer.rewind()

                bitmap.copyPixelsFromBuffer(
                    buffer
                )

                // ImageReader rows may contain right-side padding. Feed the
                // detector an exact image-width bitmap so screen-relative
                // chart coordinates stay aligned with the captured chart.
                if (bitmap.width != image.width) {
                    val exactBitmap =
                        Bitmap.createBitmap(
                            bitmap,
                            0,
                            0,
                            image.width,
                            image.height
                        )
                    try {
                        processBitmap(exactBitmap)
                    } finally {
                        exactBitmap.recycle()
                    }
                } else {
                    processBitmap(bitmap)
                }

            } finally {

                try {
                    bitmap.recycle()
                } catch (_: Exception) {
                }
            }

        } catch (e: Exception) {

            Log.e(
                TAG,
                "Frame processing error",
                e
            )

            sendStatus(
                "FRAME_ERROR"
            )

        } finally {

            try {
                image.close()
            } catch (_: Exception) {
            }
        }
    }

    // ============================================================
    // BITMAP PROCESSING
    // ============================================================

    private fun processBitmap(
        bitmap: Bitmap
    ) {

        if (!running) {
            return
        }

        // 5S QUICK target is a blue LINE chart, not OHLC candles.
        if (quickMode) {
            try {
                val lineY = LineChartAnalyzer.extractPriceY(bitmap)
                if (lineY != null) {
                    updateQuickLine5s(lineY)
                    sendCandleCount(0)
                    return
                } else {
                    // In 5S QUICK, a missing line is a hard gate.
                    // NEVER fall through to the normal candle engine.
                    sendQuickStatus("NO TRADE", 0, 0, "NO LINE CHART • WAITING")
                    sendCandleCount(0)
                    return
                }
            } catch (e: Exception) {
                Log.e(TAG, "Line chart detection failed", e)
                sendQuickStatus("NO TRADE", 0, 0, "LINE DETECTION WAITING")
                sendCandleCount(0)
                return
            }
        }

        val detected =
            try {

                CandleAnalyzer
                    .detectVisibleCandles(
                        bitmap
                    )

            } catch (e: Exception) {

                Log.e(
                    TAG,
                    "Detection failed",
                    e
                )

                emptyList()
            }

        // Always expose the detector's raw count. Do not turn a partial but
        // genuine detection into a misleading zero; the engine itself still
        // requires enough history before it can produce a signal.
        sendCandleCount(detected.size)

        if (detected.size < MIN_HISTORY + 1) {
            resetWhenChartIsMissing()
            sendStatus("CANDLE_DETECTION_WAITING")
            return
        }

        val visibleSignature =
            createVisibleSignature(
                detected
            )

        if (
            visibleSignature.isEmpty()
        ) {
            return
        }

        val currentRunningCandle =
            detected.last()

        // V23: feed the 5S activity analyzer on every detected frame,
        // before any normal 1M lifecycle/return guard.
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V23 quick activity feed", e)
            }
        }

        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V13 quick activity update failed", e)
            }
        }

        val nowMillis =
            System.currentTimeMillis()

        val periodId =
            currentPeriod(
                nowMillis
            )

        // ========================================================
        // FIRST FRAME
        // ========================================================

        if (
            currentPeriodId == -1L
        ) {

            currentPeriodId =
                periodId

            lastVisibleSignature =
                visibleSignature

            previousRunningCandle =
                currentRunningCandle

            previousRunningCandleSignature =
                createCandleSignature(
                    currentRunningCandle
                )

            rebuildHistory(
                detected
            )

            if (!quickMode) {
                sendLiveAnalysis()
                sendCandleWaitingStatus()
            }

            return
        }

        // ========================================================
        // WALL-CLOCK PERIOD CHANGED
        // ========================================================

        if (
            periodId != currentPeriodId
        ) {

            /*
             * DO NOT immediately start a trade.
             *
             * First remember that the wall clock changed.
             * The chart itself must also show a genuinely
             * different rightmost candle.
             */
            if (!waitingForNewCandle) {

                waitingForNewCandle = true

                pendingPeriodId =
                    periodId

                pendingOldPeriodId =
                    currentPeriodId

                Log.d(
                    TAG,
                    "Period changed: " +
                        "old=$currentPeriodId " +
                        "new=$periodId " +
                        "waiting for actual new candle"
                )

                sendStatus(
                    "WAITING_NEW_CANDLE"
                )
            }

            /*
             * IMPORTANT:
             *
             * Do NOT change currentPeriodId yet.
             *
             * We only change it after the new candle
             * is visually confirmed.
             */
            if (
                isNewCandleConfirmed(
                    currentRunningCandle
                )
            ) {

                confirmNewCandlePeriod(
                    pendingPeriodId,
                    pendingOldPeriodId,
                    detected,
                    visibleSignature
                )
            }

            return
        }

        // ========================================================
        // WAITING FOR NEW CANDLE
        // ========================================================

        if (waitingForNewCandle) {

            if (
                isNewCandleConfirmed(
                    currentRunningCandle
                )
            ) {

                confirmNewCandlePeriod(
                    pendingPeriodId,
                    pendingOldPeriodId,
                    detected,
                    visibleSignature
                )

            } else {

                /*
                 * Still showing old candle.
                 *
                 * Do not enter.
                 * Do not create result.
                 */
                sendStatus(
                    "WAITING_NEW_CANDLE"
                )
            }

            return
        }

        // ========================================================
        // SAME CURRENT CANDLE
        // ========================================================

        if (
            visibleSignature !=
            lastVisibleSignature
        ) {

            lastVisibleSignature =
                visibleSignature

            rebuildHistory(
                detected
            )
        }

        /*
         * Update running candle continuously.
         */
        previousRunningCandle =
            currentRunningCandle

        previousRunningCandleSignature =
            createCandleSignature(
                currentRunningCandle
            )
        if (quickMode) {
            try {
                updateQuick5s(currentRunningCandle)
            } catch (e: Exception) {
                Log.e(TAG, "V18 quick activity frame error", e)
            }
        }

        /*
         * Safety:
         * never evaluate the current running candle.
         */
        evaluateActiveTrade(
            periodId - 1L,
            detected
        )

        val remaining =
            secondsToNextBoundary()

        // ========================================================
        // FINAL 3 SECONDS
        // ========================================================

        if (
            !quickMode &&
            remaining <=
            SIGNAL_WINDOW_SECONDS &&
            lastSignalPeriodId != periodId
        ) {

            generateNextCandleSignal(
                periodId
            )

        } else {

            /*
             * Show live analysis during the candle.
             */
            if (!quickMode) {
                sendLiveAnalysis()
                sendCandleWaitingStatus()
            }
        }
    }

    // ============================================================
    // CHART MISSING
    // ============================================================

    private fun resetWhenChartIsMissing() {

        candleHistory.clear()

        currentPeriodId = -1L
        lastSignalPeriodId = -1L
        lastConfirmedSignalPeriodId = -1L
        lastConfirmedSignal = "NO TRADE"
        lastVisibleSignature = ""

        previousRunningCandle = null
        previousRunningCandleSignature = ""

        waitingForNewCandle = false
        pendingPeriodId = -1L
        pendingOldPeriodId = -1L

        queuedSignal = "NO TRADE"
        queuedConfidence = 0
        queuedTrend = "WAITING"
        queuedSignalPeriodId = -1L

        signalResetForMissingChart()
    }

    private fun signalResetForMissingChart() {
        // Keep demo result counters intact, but remove any pending signal.
        // A new chart frame must initialise the scanner from scratch.
        activeSignal = "NO TRADE"
        activeConfidence = 0
        activeTradePeriodId = -1L
        activeEntryPrice = Double.NaN
        activeEntryHigh = Double.NaN
        activeEntryLow = Double.NaN
        activeTradeCandleSignature = ""
        activeTradeStarted = false
    }

    // ============================================================
    // NEW CANDLE CONFIRMATION
    // ============================================================

    private fun isNewCandleConfirmed(
        current:
            CandleAnalyzer.DetectedCandle
    ): Boolean {

        val old =
            previousRunningCandle

        if (old == null) {
            return true
        }

        /*
         * If rightmost candle is clearly different,
         * it is safe to treat it as the new candle.
         */
        return !candlesLookSame(
            old,
            current
        )
    }

    // ============================================================
    // CONFIRM NEW PERIOD
    // ============================================================

    private fun confirmNewCandlePeriod(
        newPeriodId: Long,
        oldPeriodId: Long,
        detected:
            List<CandleAnalyzer.DetectedCandle>,
        visibleSignature: String
    ) {

        /*
         * Safety against stale/duplicate state.
         */
        if (
            !waitingForNewCandle
        ) {
            return
        }

        if (
            newPeriodId !=
            oldPeriodId + 1L
        ) {

            /*
             * If app was paused for multiple periods,
             * do not guess a trade/result.
             */
            Log.w(
                TAG,
                "Unexpected period jump: " +
                    "old=$oldPeriodId " +
                    "new=$newPeriodId"
            )

            waitingForNewCandle = false
            pendingPeriodId = -1L
            pendingOldPeriodId = -1L

            currentPeriodId =
                newPeriodId

            lastVisibleSignature =
                visibleSignature

            previousRunningCandle =
                detected.last()

            previousRunningCandleSignature =
                createCandleSignature(
                    detected.last()
                )

            rebuildHistory(
                detected
            )

            sendStatus(
                "PERIOD_RESYNC"
            )

            return
        }

        /*
         * ========================================================
         * FIRST:
         * CLOSE THE PREVIOUS ACTIVE TRADE.
         *
         * The newly detected rightmost candle is the new
         * running candle.
         *
         * detected[-2] = exact candle that just closed.
         * ========================================================
         */
        evaluateActiveTrade(
            oldPeriodId,
            detected
        )

        /*
         * ========================================================
         * NOW COMMIT THE NEW PERIOD.
         * ========================================================
         */
        currentPeriodId =
            newPeriodId

        waitingForNewCandle =
            false

        pendingPeriodId =
            -1L

        pendingOldPeriodId =
            -1L

        lastVisibleSignature =
            visibleSignature

        /*
         * ========================================================
         * START QUEUED TRADE.
         *
         * This is ONLY the new candle.
         *
         * ENTRY = its OPEN.
         * ========================================================
         */
        startQueuedTradeIfNeeded(
            newPeriodId,
            detected
        )

        // Consume one cooldown candle after the entry decision.
        if (cooldownPeriodsRemaining > 0) {
            cooldownPeriodsRemaining--
        }

        /*
         * ========================================================
         * Store new running candle.
         * ========================================================
         */
        val newRunningCandle =
            detected.last()

        previousRunningCandle =
            newRunningCandle

        previousRunningCandleSignature =
            createCandleSignature(
                newRunningCandle
            )

        /*
         * History contains only CLOSED candles.
         */
        rebuildHistory(
            detected
        )

        sendCandleRunningStatus()
    }

    // ============================================================
    // HISTORY
    // ============================================================

    private fun rebuildHistory(
        detected:
            List<CandleAnalyzer.DetectedCandle>
    ) {

        if (
            detected.size <= 1
        ) {
            return
        }

        /*
         * Rightmost candle = running.
         * Everything before it = closed history.
         */
        val completed =
            detected
                .dropLast(1)
                .takeLast(MAX_HISTORY)

        if (
            completed.isEmpty()
        ) {
            return
        }

        /*
         * Keep a rolling history across frames instead of rebuilding it
         * from the visible window every time. The visible chart usually
         * contains only ~50-60 candles; rebuilding capped the calibration
         * forever. A new closed candle is appended only when its OHLC/signature
         * differs from the last stored closed candle.
         */
        if (candleHistory.isEmpty()) {
            candleHistory.addAll(completed)
        } else {
            val newestClosed = completed.last()
            val lastStored = candleHistory.lastOrNull()
            if (lastStored == null || !candlesLookSame(lastStored, newestClosed)) {
                candleHistory.add(newestClosed)
            }
        }

        trimHistory()

        // QUICK mode uses the running 1M candle plus successive screen
        // frames to derive genuine 5-second observations.

    }

    // ============================================================
    // LIVE ANALYSIS
    // ============================================================

    private fun sendLiveAnalysis() {

        if (
            candleHistory.size <
            MIN_HISTORY
        ) {

            sendAnalysisWaiting()

            return
        }

        try {

            val result =
                CandleAnalyzer
                    .analyzeHistory(
                        candleHistory
                            .takeLast(
                                MAX_HISTORY
                            ),
                        selectedTimeframe
                    )

            val intent =
                Intent(
                    ACTION_STATUS
                )

            intent.setPackage(
                packageName
            )

            intent.putExtra(
                "status",
                "LIVE_ANALYSIS"
            )

            intent.putExtra(
                "timeframe",
                selectedTimeframe
            )

            intent.putExtra(
                "trend",
                result.trend
            )

            intent.putExtra(
                "signal",
                "NO TRADE"
            )

            // Show the real analysis confidence even while the live
            // state is NO TRADE. A NO TRADE result can still have a
            // meaningful setup strength (for example 45%, 72%, 88%).
            // CALL/PUT is still locked only by generateNextCandleSignal
            // at the final confirmation stage.
            val liveProbability =
                if (result.signal == "CALL" || result.signal == "PUT") {
                    calculateEmpiricalProbability(
                        candleHistory.takeLast(MAX_HISTORY),
                        result.signal
                    )
                } else {
                    null
                }

            intent.putExtra(
                "confidence",
                liveProbability ?: 0
            )
            intent.putExtra(
                "probability",
                liveProbability ?: 0
            )
            intent.putExtra(
                "probabilitySamples",
                empiricalProbabilitySamples(
                    candleHistory.takeLast(MAX_HISTORY),
                    result.signal
                )
            )

            intent.putExtra(
                "bullishScore",
                result.bullishScore
            )

            intent.putExtra(
                "bearishScore",
                result.bearishScore
            )

            intent.putExtra(
                "remaining",
                secondsToNextBoundary()
            )

            intent.putExtra(
                "count",
                candleHistory.size
            )

            sendBroadcast(
                intent
            )

        } catch (e: Exception) {

            Log.e(
                TAG,
                "Live analysis failed",
                e
            )
        }
    }

    // ============================================================
    // FINAL SIGNAL
    // ============================================================

    private fun generateNextCandleSignal(
        signalPeriodId: Long
    ) {

        /*
         * One final signal maximum per candle.
         */
        if (
            lastSignalPeriodId ==
            signalPeriodId
        ) {
            return
        }

        if (
            candleHistory.size <
            MIN_HISTORY
        ) {

            lastSignalPeriodId =
                signalPeriodId

            clearQueuedSignal()

            sendAnalysisWaiting()

            return
        }

        try {

            val result =
                CandleAnalyzer
                    .analyzeHistory(
                        candleHistory
                            .takeLast(
                                MAX_HISTORY
                            ),
                        selectedTimeframe
                    )

            val rawSignal =
                result.signal
                    .uppercase()

            // Same-direction setups are allowed again only after
            // the hard candle-gap protection below. This avoids the old
            // behaviour where one CALL permanently blocked all future CALLs.

            /*
             * HARD ANTI-REPEAT RULE:
             * A valid signal must have a fresh setup. Never allow
             * signals on consecutive candles. We require three
             * candle periods between confirmed signal candles.
             */
            val gapSinceConfirmed =
                if (lastConfirmedSignalPeriodId < 0L) {
                    Long.MAX_VALUE
                } else {
                    signalPeriodId - lastConfirmedSignalPeriodId
                }

            val cooldownActive =
                gapSinceConfirmed < MIN_SIGNAL_GAP_CANDLES

            if (cooldownActive) {

                clearQueuedSignal()

                queuedSignalPeriodId =
                    signalPeriodId

                lastSignalPeriodId =
                    signalPeriodId

                val cooldownIntent =
                    Intent(
                        ACTION_STATUS
                    )

                cooldownIntent.setPackage(
                    packageName
                )

                cooldownIntent.putExtra(
                    "status",
                    "ANALYSIS_READY"
                )
                cooldownIntent.putExtra(
                    "timeframe",
                    selectedTimeframe
                )
                cooldownIntent.putExtra(
                    "trend",
                    result.trend
                )
                cooldownIntent.putExtra(
                    "signal",
                    "NO TRADE"
                )
                cooldownIntent.putExtra(
                    "rawSignal",
                    rawSignal
                )
                cooldownIntent.putExtra(
                    "confidence",
                    0
                )
                cooldownIntent.putExtra(
                    "candleId",
                    signalPeriodId
                )
                cooldownIntent.putExtra(
                    "remaining",
                    secondsToNextBoundary()
                )
                cooldownIntent.putExtra(
                    "entry",
                    "WAIT - FRESH SETUP"
                )

                sendBroadcast(
                    cooldownIntent
                )

                return
            }

            /*
             * HARD RULE:
             *
             * CALL/PUT only at >= 90%.
             */
            val empiricalProbability =
                if (rawSignal == "CALL" || rawSignal == "PUT") {
                    calculateEmpiricalProbability(
                        candleHistory.takeLast(MAX_HISTORY),
                        rawSignal
                    )
                } else {
                    null
                }

            val confirmed =
                (
                    (rawSignal == "CALL" || rawSignal == "PUT") &&
                    result.confidence >= MIN_CONFIDENCE_TO_QUEUE &&
                    empiricalProbability != null &&
                    empiricalProbability >= MIN_EMPIRICAL_PROBABILITY
                )

            val finalSignal =
                if (confirmed) rawSignal else "NO TRADE"

            if (confirmed) {
                lastConfirmedSignalPeriodId =
                    signalPeriodId
                lastConfirmedSignal =
                    finalSignal
            }

            queuedSignal =
                finalSignal

            queuedConfidence =
                if (confirmed) {
                    empiricalProbability ?: 0
                } else {
                    0
                }

            queuedTrend =
                result.trend

            queuedSignalPeriodId =
                signalPeriodId

            /*
             * Lock this source candle.
             *
             * Even if the next few frames change the
             * analysis, we do not generate another signal
             * for this same candle.
             */
            lastSignalPeriodId =
                signalPeriodId

            val intent =
                Intent(
                    ACTION_STATUS
                )

            intent.setPackage(
                packageName
            )

            intent.putExtra(
                "status",
                "ANALYSIS_READY"
            )

            intent.putExtra(
                "timeframe",
                selectedTimeframe
            )

            intent.putExtra(
                "trend",
                result.trend
            )

            intent.putExtra(
                "signal",
                finalSignal
            )

            intent.putExtra(
                "rawSignal",
                rawSignal
            )

            intent.putExtra(
                "confidence",
                if (confirmed) {
                    empiricalProbability ?: 0
                } else {
                    0
                }
            )
            intent.putExtra(
                "probability",
                empiricalProbability ?: 0
            )
            intent.putExtra(
                "probabilitySamples",
                empiricalProbabilitySamples(candleHistory.takeLast(MAX_HISTORY), rawSignal)
            )

            intent.putExtra(
                "candleId",
                signalPeriodId
            )

            intent.putExtra(
                "remaining",
                secondsToNextBoundary()
            )

            intent.putExtra(
                "entry",
                if (confirmed) {
                    "NEXT $selectedTimeframe CANDLE OPEN"
                } else {
                    "WAIT"
                }
            )

            intent.putExtra(
                "exit",
                if (confirmed) {
                    "SAME NEXT CANDLE CLOSE"
                } else {
                    "WAIT"
                }
            )

            intent.putExtra(
                "finalStatus",
                if (confirmed) {
                    "SIGNAL LOCKED"
                } else {
                    "NO TRADE"
                }
            )

            intent.putExtra(
                "signalForNextCandle",
                confirmed
            )

            sendBroadcast(
                intent
            )

        } catch (e: Exception) {

            Log.e(
                TAG,
                "Final analysis failed",
                e
            )

            lastSignalPeriodId =
                signalPeriodId

            clearQueuedSignal()

            sendStatus(
                "ANALYSIS_ERROR"
            )
        }
    }

    // ============================================================
    // NEXT CANDLE ENTRY
    // ============================================================

    private fun startQueuedTradeIfNeeded(
        newPeriodId: Long,
        detected:
            List<CandleAnalyzer.DetectedCandle>
    ) {

        /*
         * Absolutely no trade without CALL/PUT.
         */
        if (
            queuedSignal != "CALL" &&
            queuedSignal != "PUT"
        ) {
            return
        }

        /*
         * CONSERVATIVE COOLDOWN:
         * Never enter while the loss-protection cooldown is active.
         * This is deliberately applied before entry validation so a
         * weak signal cannot bypass the protection.
         */
        if (cooldownPeriodsRemaining > 0) {
            Log.d(
                TAG,
                "Trade blocked by cooldown: " +
                    "remaining=$cooldownPeriodsRemaining " +
                    "signal=$queuedSignal"
            )
            clearQueuedSignal()
            return
        }

        /*
         * Signal MUST be for immediately previous candle.
         */
        if (
            queuedSignalPeriodId !=
            newPeriodId - 1L
        ) {

            Log.d(
                TAG,
                "Queued signal expired: " +
                    "signalPeriod=$queuedSignalPeriodId " +
                    "newPeriod=$newPeriodId"
            )

            clearQueuedSignal()

            return
        }

        if (
            detected.isEmpty()
        ) {
            return
        }

        /*
         * The rightmost detected candle is the NEW
         * running candle.
         */
        val tradeCandle =
            detected.last()

        /*
         * Entry must be the OPEN of this exact candle.
         */
        val entry =
            tradeCandle.open

        if (
            !entry.isFinite()
        ) {
            Log.w(
                TAG,
                "Invalid new candle OPEN. Trade blocked."
            )

            return
        }

        /*
         * ========================================================
         * LOCK EXACT TRADE CANDLE
         * ========================================================
         */
        activeSignal =
            queuedSignal

        activeConfidence =
            queuedConfidence

        activeTradePeriodId =
            newPeriodId

        activeEntryPrice =
            entry

        activeEntryHigh =
            tradeCandle.high

        activeEntryLow =
            tradeCandle.low

        activeTradeCandleSignature =
            createCandleSignature(
                tradeCandle
            )

        activeTradeStarted =
            true

        Log.d(
            TAG,
            "TRADE ENTRY: " +
                "period=$newPeriodId " +
                "signal=$activeSignal " +
                "OPEN=$entry"
        )

        sendTradeEntry(
            newPeriodId,
            entry
        )

        /*
         * Consume the queued signal.
         */
        clearQueuedSignal()
    }

    // ============================================================
    // EXACT RESULT
    // ============================================================

    private fun evaluateActiveTrade(
        completedPeriodId: Long,
        detected:
            List<CandleAnalyzer.DetectedCandle>
    ) {

        /*
         * No active trade.
         */
        if (!activeTradeStarted) {
            return
        }

        /*
         * Only the exact active trade period can produce
         * its result.
         */
        if (
            activeTradePeriodId !=
            completedPeriodId
        ) {
            return
        }

        /*
         * Never process same period twice.
         */
        if (
            resultProcessedPeriodId ==
            completedPeriodId
        ) {
            return
        }

        /*
         * Need:
         *
         * detected[-2] = CLOSED TRADE CANDLE
         * detected[-1] = NEW RUNNING CANDLE
         */
        if (
            detected.size < 2
        ) {
            return
        }

        val tradeCandle =
            detected[
                detected.lastIndex - 1
            ]

        /*
         * ========================================================
         * EXACT TRADE CANDLE VALIDATION
         * ========================================================
         */
        if (
            !isSameTradeCandle(
                tradeCandle
            )
        ) {

            Log.w(
                TAG,
                "Trade candle mismatch. " +
                    "RESULT BLOCKED."
            )

            sendStatus(
                "RESULT_WAITING_CANDLE_CONFIRMATION"
            )

            return
        }

        /*
         * ========================================================
         * CRITICAL RESULT VALUES
         *
         * ENTRY = OPEN OF SAME TRADE CANDLE
         * EXIT  = CLOSE OF SAME TRADE CANDLE
         *
         * NEVER use detected[-1].
         * NEVER use the new candle colour.
         * ========================================================
         */
        val entry =
            tradeCandle.open

        val exit =
            tradeCandle.close

        if (
            !entry.isFinite() ||
            !exit.isFinite()
        ) {
            return
        }

        /*
         * ========================================================
         * EXACT RESULT LOGIC
         * ========================================================
         */
        val result =
            when {

                activeSignal == "CALL" &&
                    exit > entry ->
                    "WIN"

                activeSignal == "CALL" &&
                    exit < entry ->
                    "LOSS"

                activeSignal == "PUT" &&
                    exit < entry ->
                    "WIN"

                activeSignal == "PUT" &&
                    exit > entry ->
                    "LOSS"

                else ->
                    "DRAW"
            }

        /*
         * Mark BEFORE broadcast.
         */
        resultProcessedPeriodId =
            completedPeriodId

        lastResult =
            result

        lastResultSignal =
            activeSignal

        lastResultEntry =
            entry

        lastResultExit =
            exit

        when (result) {

            "WIN" -> {
                wins++
                consecutiveLosses = 0
                cooldownPeriodsRemaining = 0
            }

            "LOSS" -> {
                losses++
                consecutiveLosses++
                cooldownPeriodsRemaining =
                    if (consecutiveLosses >= 2) 3 else 1
            }

            "DRAW" -> {
                draws++
            }
        }

        Log.d(
            TAG,
            "CLOSED RESULT: " +
                "period=$completedPeriodId " +
                "signal=$activeSignal " +
                "OPEN=$entry " +
                "CLOSE=$exit " +
                "result=$result"
        )

        sendTradeResult(
            completedPeriodId,
            activeSignal,
            entry,
            exit,
            result
        )

        /*
         * Trade completely finished.
         */
        clearActiveTrade()
    }

    // ============================================================
    // TRADE CANDLE VALIDATION
    // ============================================================

    private fun isSameTradeCandle(
        candle:
            CandleAnalyzer.DetectedCandle
    ): Boolean {

        if (
            !activeEntryPrice.isFinite()
        ) {
            return false
        }

        /*
         * OPEN is the strongest identity check.
         */
        val openDifference =
            abs(
                candle.open -
                    activeEntryPrice
            )

        if (
            openDifference >
            CANDLE_MATCH_TOLERANCE
        ) {
            return false
        }

        /*
         * High/low can change while the candle is running.
         *
         * Therefore they are only secondary protection.
         */
        if (
            activeEntryHigh.isFinite() &&
            activeEntryLow.isFinite()
        ) {

            val highDifference =
                abs(
                    candle.high -
                        activeEntryHigh
                )

            val lowDifference =
                abs(
                    candle.low -
                        activeEntryLow
                )

            if (
                highDifference >
                    CANDLE_MATCH_TOLERANCE * 4.0 &&
                lowDifference >
                    CANDLE_MATCH_TOLERANCE * 4.0
            ) {

                return false
            }
        }

        return true
    }

    // ============================================================
    // SAME / DIFFERENT CANDLE
    // ============================================================

    private fun candlePriceTolerance(
        first: CandleAnalyzer.DetectedCandle,
        second: CandleAnalyzer.DetectedCandle
    ): Double {

        val scale = maxOf(
            abs(first.open),
            abs(first.high),
            abs(first.low),
            abs(first.close),
            abs(second.open),
            abs(second.high),
            abs(second.low),
            abs(second.close)
        )

        // Pixel-to-price conversion is instrument dependent. A small
        // relative tolerance works for both 0.x OTC pairs and 1000+
        // instruments without using the old fixed 1.0 threshold, which
        // could treat genuinely different 5-second candles as identical.
        return maxOf(1.0e-8, scale * 1.0e-5)
    }

    private fun candlesLookSame(
        first:
            CandleAnalyzer.DetectedCandle,
        second:
            CandleAnalyzer.DetectedCandle
    ): Boolean {

        val tolerance = candlePriceTolerance(first, second)

        return (
            first.bullish ==
                second.bullish
        ) &&

        abs(
            first.open -
                second.open
        ) <=
            tolerance &&

        abs(
            first.high -
                second.high
        ) <=
            tolerance &&

        abs(
            first.low -
                second.low
        ) <=
            tolerance &&

        abs(
            first.close -
                second.close
        ) <=
            tolerance
    }

    // ============================================================
    // QUEUED CLEAR
    // ============================================================


    // ============================================================
    // EMPIRICAL WIN PROBABILITY
    // ============================================================
    // Walk-forward calibration: each historical signal is generated
    // using candles available before the outcome candle, then the next
    // completed candle decides WIN/LOSS. This is deliberately separate
    // from the analyzer's quality score.
    private fun empiricalProbabilitySamples(
        history: List<CandleAnalyzer.DetectedCandle>,
        direction: String
    ): Int {

        if (history.size < 31) {
            return 0
        }

        val wanted =
            direction.uppercase(Locale.US)

        if (wanted != "CALL" && wanted != "PUT") {
            return 0
        }

        var samples = 0

        for (endExclusive in 25 until history.size - 1) {

            val prefix =
                history.take(endExclusive)

            val result =
                try {
                    CandleAnalyzer.analyzeHistory(
                        prefix,
                        selectedTimeframe
                    )
                } catch (_: Exception) {
                    continue
                }

            val signal =
                result.signal.uppercase(Locale.US)

            /*
             * Historical calibration does NOT require the old
             * analyzer confidence to already be 90%. Otherwise
             * calibration can remain stuck at N=0.
             *
             * The 90% requirement is applied separately to the
             * CURRENT setup in generateNextCandleSignal().
             */
            if (signal != wanted) {
                continue
            }

            samples++
        }

        return samples
    }

    private fun calculateEmpiricalProbability(
        history: List<CandleAnalyzer.DetectedCandle>,
        direction: String
    ): Int? {

        if (history.size < 31) {
            return null
        }

        val wanted =
            direction.uppercase(Locale.US)

        if (wanted != "CALL" && wanted != "PUT") {
            return null
        }

        var winsLocal = 0
        var samples = 0

        for (endExclusive in 25 until history.size - 1) {

            val prefix =
                history.take(endExclusive)

            val result =
                try {
                    CandleAnalyzer.analyzeHistory(
                        prefix,
                        selectedTimeframe
                    )
                } catch (_: Exception) {
                    continue
                }

            val signal =
                result.signal.uppercase(Locale.US)

            /*
             * Count every genuine historical CALL/PUT generated by
             * the strategy. Do NOT require historical confidence >= 90
             * here, because that makes the empirical calibration
             * self-starving and keeps N at zero.
             */
            if (signal != wanted) {
                continue
            }

            val signalCandle =
                prefix.last()

            val outcomeCandle =
                history[endExclusive]

            val win =
                if (wanted == "CALL") {
                    outcomeCandle.close > signalCandle.close
                } else {
                    outcomeCandle.close < signalCandle.close
                }

            samples++

            if (win) {
                winsLocal++
            }
        }

        /*
         * Never manufacture a probability.
         * At least 30 genuine historical observations are required.
         */
        if (samples < MIN_EMPIRICAL_SAMPLES) {
            return null
        }

        return (
            winsLocal.toDouble() /
                samples.toDouble() *
                100.0
        )
            .roundToInt()
            .coerceIn(0, 100)
    }

    private fun quickHistoricalSampleCount(direction: String): Int {
        val winsKey =
            if (direction == "CALL") "shadow_call_wins"
            else "shadow_put_wins"
        val lossesKey =
            if (direction == "CALL") "shadow_call_losses"
            else "shadow_put_losses"
        return probabilityPrefs.getInt(winsKey, 0) +
            probabilityPrefs.getInt(lossesKey, 0)
    }

    // ============================================================
    // 5-SECOND QUICK ENGINE
    // ============================================================
    // The screen remains on 1M. We use the rightmost running 1M candle
    // and successive captured frames to observe a 5-second intrabar move.
    // There is no honest way to invent historical 5-second candles from
    // a 1M candle, so the quick probability starts only after enough
    // real 5-second observations have been recorded.
    private fun updateQuickLine5s(priceY: Double) {
        val now = System.currentTimeMillis()
        lineSamples.addLast(now to priceY)
        while (lineSamples.isNotEmpty() && now - lineSamples.first().first > 2200L) {
            lineSamples.removeFirst()
        }

        if (lineSignalDirection == "CALL" || lineSignalDirection == "PUT") {
            if (now >= lineSignalUntilMs) {
                val win = if (lineSignalDirection == "CALL") {
                    priceY < lineSignalEntryY
                } else {
                    priceY > lineSignalEntryY
                }
                sendQuickStatus(
                    "NO TRADE", 0, lineSamples.size,
                    if (win) "5S DEMO RESULT: WIN" else "5S DEMO RESULT: LOSS"
                )
                lineSignalDirection = "NONE"
                lineSignalEntryY = Double.NaN
                lineSignalUntilMs = 0L
                lineLastSignalMs = now
            } else {
                sendQuickStatus(lineSignalDirection, 0, lineSamples.size, "5S SIGNAL LOCKED")
                return
            }
        }

        if (lineSamples.size < 5) {
            sendQuickStatus("NO TRADE", 0, lineSamples.size, "LINE DETECTED • WARMING")
            return
        }

        val values = lineSamples.map { it.second }
        val first = values.first()
        val last = values.last()
        val delta = first - last

        // Ignore sub-pixel jitter. Direction must agree across most observed
        // moves before a 90% signal is allowed.
        var up = 0
        var down = 0
        var previous = first
        for (y in values.drop(1)) {
            val d = previous - y
            if (d > 2.0) up++
            else if (d < -2.0) down++
            previous = y
        }

        val directionalMoves = up + down
        if (directionalMoves < 5) {
            val scanScore = (55 + kotlin.math.abs(delta).coerceAtMost(15.0)).roundToInt()
            sendQuickStatus("NO TRADE", scanScore.coerceIn(0, 89), lineSamples.size,
                "LINE DETECTED • SCANNING")
            return
        }

        val agreement = maxOf(up, down).toDouble() / directionalMoves.toDouble()
        val movement = kotlin.math.abs(delta)

        val movementScore = when {
            movement >= 20.0 -> 45
            movement >= 16.0 -> 40
            movement >= 12.0 -> 34
            movement >= 8.0 -> 28
            movement >= 6.0 -> 20
            movement >= 4.0 -> 12
            else -> 6
        }
        val agreementScore = when {
            agreement >= 0.66 -> 45
            agreement >= 0.60 -> 40
            agreement >= 0.55 -> 32
            agreement >= 0.50 -> 24
            else -> 12
        }

        val momentum = (movementScore + agreementScore).coerceIn(0, 99)
        val strongDirection = if (up > down) "CALL" else "PUT"

        // Meaningful movement and strong directional agreement are
        // mandatory. The gate is practical enough to trigger on real line
        // moves while still rejecting weak/noisy motion.
        val strong = movement >= 20.0 && agreement >= 0.66 && momentum >= 90

        if (strong) {
            lineSignalDirection = strongDirection
            lineSignalEntryY = priceY
            lineSignalUntilMs = now + 5000L
            lineLastSignalMs = now

            sendQuickStatus(
                strongDirection, momentum, lineSamples.size,
                "5S DEMO SIGNAL • LOCK 5 SEC"
            )
        } else {
            sendQuickStatus(
                "NO TRADE", momentum.coerceAtMost(89), lineSamples.size,
                "LINE DETECTED • SCANNING"
            )
        }
    }

    private fun updateQuick5s(runningCandle: CandleAnalyzer.DetectedCandle) {
        val nowBucket = System.currentTimeMillis() / QUICK_BUCKET_MS
        val price = runningCandle.close
        if (!price.isFinite()) {
            sendQuickStatus("NO TRADE", 0, 0, "WAIT - INVALID PRICE")
            return
        }

        if (quickBucketId < 0L || quickPressureCandle == null) {
            quickBucketId = nowBucket
            quickLastClose = price
            quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)
            return
        }

        val building = quickPressureCandle
        if (nowBucket == quickBucketId && building != null) {
            building.high = max(building.high, price)
            building.low = min(building.low, price)
            building.close = price
            return
        }

        // Missing capture buckets invalidate the setup; never synthesize missing data.
        if (nowBucket != quickBucketId + 1L || building == null) {
            quickBucketId = nowBucket
            quickLastClose = price
            quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)
            quickShadowDirection = "NONE"
            quickShadowEntry = Double.NaN
            quickShadowUntilBucket = -1L
            quickSignalDirection = "NONE"
            quickSignal = "NO TRADE"
            quickSignalEntry = Double.NaN
            quickActiveUntilBucket = -1L
            sendQuickStatus("NO TRADE", 0, 0, "WAIT - MISSED 5S DATA")
            return
        }

        val closed = building
        quickPressureHistory.add(closed)
        while (quickPressureHistory.size > 120) quickPressureHistory.removeAt(0)

        // Score a shadow setup only when the next bucket's first real price arrives.
        if ((quickShadowDirection == "CALL" || quickShadowDirection == "PUT") &&
            quickShadowUntilBucket >= 0L && nowBucket >= quickShadowUntilBucket) {
            val won = if (quickShadowDirection == "CALL") price > quickShadowEntry else price < quickShadowEntry
            val wk = if (quickShadowDirection == "CALL") "shadow_call_wins" else "shadow_put_wins"
            val lk = if (quickShadowDirection == "CALL") "shadow_call_losses" else "shadow_put_losses"
            val wins = probabilityPrefs.getInt(wk, 0) + if (won) 1 else 0
            val losses = probabilityPrefs.getInt(lk, 0) + if (won) 0 else 1
            probabilityPrefs.edit().putInt(wk, wins).putInt(lk, losses).apply()
            quickShadowDirection = "NONE"
            quickShadowEntry = Double.NaN
            quickShadowUntilBucket = -1L
        }

        if ((quickSignalDirection == "CALL" || quickSignalDirection == "PUT") &&
            quickActiveUntilBucket >= 0L && nowBucket >= quickActiveUntilBucket) {
            val won = if (quickSignalDirection == "CALL") price > quickSignalEntry else price < quickSignalEntry
            if (won) quickWins++ else quickLosses++
            probabilityPrefs.edit().putInt("quick_wins", quickWins).putInt("quick_losses", quickLosses).apply()
            quickSignalDirection = "NONE"
            quickSignal = "NO TRADE"
            quickSignalEntry = Double.NaN
            quickActiveUntilBucket = -1L
        }

        // Start the next bucket before evaluating the completed one.
        quickBucketId = nowBucket
        quickLastClose = price
        quickPressureCandle = QuickPressureCandle(nowBucket, price, price, price, price)

        val oneMinute = candleHistory.takeLast(MAX_HISTORY)
        if (oneMinute.size < 30 || quickPressureHistory.size < 3) {
            sendQuickStatus("NO TRADE", 0, quickPressureHistory.size, "WAIT - BUILDING 1M/5S HISTORY")
            return
        }

        val trend1m = quickTrend(oneMinute.map { it.close }, 5, 13)
        // Approximate 5M structure from five-candle groups on the 1M chart.
        // This is not an independent broker-provided 5M candle feed.
        val fiveMinuteCloses = oneMinute.takeLast(60).chunked(5)
            .filter { it.size == 5 }.map { it.last().close }
        val trend5m = quickTrend(fiveMinuteCloses, 3, 6)

        val range = (closed.high - closed.low).coerceAtLeast(1.0e-12)
        val bodyRatio = (abs(closed.close - closed.open) / range).coerceIn(0.0, 1.0)
        val upper = (closed.high - max(closed.open, closed.close)).coerceAtLeast(0.0) / range
        val lower = (min(closed.open, closed.close) - closed.low).coerceAtLeast(0.0) / range
        val closeLocation = ((closed.close - closed.low) / range).coerceIn(0.0, 1.0)
        val micro = quickPressureHistory.takeLast(3)
        val momentum = micro.last().close - micro.first().open
        val momentumUp = momentum > 0.0
        val momentumDown = momentum < 0.0

        // Body + close location + both wick tips + three-candle momentum.
        // This is price-action pressure, not order-book buying/selling volume.
        val bullPressure = (bodyRatio * 0.40 + closeLocation * 0.30 + lower * 0.20 +
            (if (momentumUp) 0.10 else 0.0) - upper * 0.20).coerceIn(0.0, 1.0)
        val bearPressure = (bodyRatio * 0.40 + (1.0 - closeLocation) * 0.30 + upper * 0.20 +
            (if (momentumDown) 0.10 else 0.0) - lower * 0.20).coerceIn(0.0, 1.0)

        val bull = closed.close > closed.open && bodyRatio >= 0.35 &&
            closeLocation >= 0.62 && upper <= 0.35 && momentumUp && bullPressure >= 0.58
        val bear = closed.close < closed.open && bodyRatio >= 0.35 &&
            closeLocation <= 0.38 && lower <= 0.35 && momentumDown && bearPressure >= 0.58

        val direction = when {
            trend5m == "BULLISH" && trend1m == "BULLISH" && bull -> "CALL"
            trend5m == "BEARISH" && trend1m == "BEARISH" && bear -> "PUT"
            else -> "NO TRADE"
        }

        val setupKey = "$trend5m:$trend1m:$direction:" + closed.bucket
        val cooldown = quickLastSignalBucket >= 0L &&
            nowBucket - quickLastSignalBucket < QUICK_COOLDOWN_BUCKETS
        val fresh = setupKey != quickLastSetupKey ||
            nowBucket - quickLastSetupBucket >= QUICK_COOLDOWN_BUCKETS

        if ((direction == "CALL" || direction == "PUT") && fresh && quickShadowDirection == "NONE") {
            quickShadowDirection = direction
            quickShadowEntry = price
            quickShadowUntilBucket = nowBucket + 1L
            quickLastSetupKey = setupKey
            quickLastSetupBucket = nowBucket
        }

        val probability = if (direction == "CALL" || direction == "PUT") quickHistoricalProbability(direction) else null
        val samples = if (direction == "CALL" || direction == "PUT") quickHistoricalSampleCount(direction) else 0
        val canSignal = (direction == "CALL" || direction == "PUT") &&
            probability != null && probability >= MIN_EMPIRICAL_PROBABILITY &&
            samples >= MIN_EMPIRICAL_SAMPLES && !cooldown && fresh &&
            quickSignalDirection == "NONE"

        if (canSignal) {
            quickSignal = direction
            quickSignalDirection = direction
            quickSignalEntry = price
            quickActiveUntilBucket = nowBucket + 1L
            quickLastSignalBucket = nowBucket
            quickLastSetupKey = setupKey
            quickLastSetupBucket = nowBucket
            sendQuickStatus(direction, probability ?: 0, samples, "5S SIGNAL - DEMO TEST ONLY")
        } else {
            val why = when {
                trend5m == "WAITING" || trend1m == "WAITING" -> "WAIT - TREND HISTORY"
                trend5m != trend1m -> "NO TRADE - TREND CONFLICT"
                direction == "NO TRADE" -> "NO TRADE - WEAK 5S PRESSURE"
                probability == null || samples < MIN_EMPIRICAL_SAMPLES -> "WAIT - EMPIRICAL SAMPLES ($samples/$MIN_EMPIRICAL_SAMPLES)"
                cooldown || !fresh -> "WAIT - FRESH SETUP"
                else -> "NO TRADE - 90% GATE"
            }
            sendQuickStatus("NO TRADE", probability ?: 0, samples, why)
        }
    }

    private fun quickTrend(values: List<Double>, fastPeriod: Int, slowPeriod: Int): String {
        if (values.size < maxOf(slowPeriod + 2, 6)) return "WAITING"
        val fast = quickEma(values, fastPeriod)
        val slow = quickEma(values, slowPeriod)
        val recent = values.takeLast(3)
        return when {
            fast > slow && recent.last() > recent.first() -> "BULLISH"
            fast < slow && recent.last() < recent.first() -> "BEARISH"
            else -> "SIDEWAYS"
        }
    }

    private fun quickEma(values: List<Double>, period: Int): Double {
        if (values.isEmpty()) return Double.NaN
        val alpha = 2.0 / (period + 1.0)
        var value = values.first()
        for (i in 1 until values.size) value = alpha * values[i] + (1.0 - alpha) * value
        return value
    }

    private fun quickHistoricalProbability(
        direction: String
    ): Int? {
        // Direction-specific calibration is preferable. For the first
        // implementation we keep separate CALL/PUT buckets so one side
        // cannot hide a weak result on the other side.
        val winsKey =
            if (direction == "CALL") "shadow_call_wins"
            else "shadow_put_wins"
        val lossesKey =
            if (direction == "CALL") "shadow_call_losses"
            else "shadow_put_losses"

        val winsLocal = probabilityPrefs.getInt(winsKey, 0)
        val lossesLocal = probabilityPrefs.getInt(lossesKey, 0)
        val samples = winsLocal + lossesLocal

        if (samples < MIN_EMPIRICAL_SAMPLES) return null

        return (
            winsLocal.toDouble() / samples.toDouble() * 100.0
        ).roundToInt().coerceIn(0, 100)
    }

    private fun sendQuickStatus(
        signal: String,
        probability: Int,
        samples: Int,
        statusText: String
    ) {
        val intent = Intent(ACTION_STATUS).apply {
            setPackage(packageName)
            putExtra("status", "QUICK_5S")
            putExtra("timeframe", "5S")
            putExtra("quickSignal", signal)
            putExtra("quickProbability", probability)
            putExtra("confidence", probability)
            putExtra("quickSamples", samples)
            putExtra("quickStatus", statusText)
        }
        sendBroadcast(intent)
    }

    private fun clearQueuedSignal() {

        queuedSignal =
            "NO TRADE"

        queuedConfidence =
            0

        queuedTrend =
            "WAITING"

        queuedSignalPeriodId =
            -1L
    }

    // ============================================================
    // ACTIVE CLEAR
    // ============================================================

    private fun clearActiveTrade() {

        activeSignal =
            "NO TRADE"

        activeConfidence =
            0

        activeTradePeriodId =
            -1L

        activeEntryPrice =
            Double.NaN

        activeEntryHigh =
            Double.NaN

        activeEntryLow =
            Double.NaN

        activeTradeCandleSignature =
            ""

        activeTradeStarted =
            false
    }

    // ============================================================
    // ENTRY BROADCAST
    // ============================================================

    private fun sendTradeEntry(
        periodId: Long,
        entryPrice: Double
    ) {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "TRADE_ENTRY"
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        intent.putExtra(
            "signal",
            activeSignal
        )

        intent.putExtra(
            "confidence",
            activeConfidence
        )

        intent.putExtra(
            "entryPrice",
            entryPrice
        )

        intent.putExtra(
            "entryType",
            "OPEN"
        )

        intent.putExtra(
            "exitType",
            "CLOSE"
        )

        intent.putExtra(
            "tradePeriodId",
            periodId
        )

        intent.putExtra(
            "wins",
            wins
        )

        intent.putExtra(
            "losses",
            losses
        )

        intent.putExtra(
            "draws",
            draws
        )

        intent.putExtra(
            "tradeRunning",
            true
        )

        intent.putExtra(
            "entryConfirmed",
            true
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // RESULT BROADCAST
    // ============================================================

    private fun sendTradeResult(
        periodId: Long,
        signal: String,
        entry: Double,
        exit: Double,
        result: String
    ) {

        val total =
            wins + losses

        val accuracy =
            if (
                total > 0
            ) {

                (
                    wins.toDouble() /
                        total.toDouble() *
                        100.0
                ).toInt()

            } else {
                0
            }

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "RESULT_READY"
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        intent.putExtra(
            "result",
            result
        )

        intent.putExtra(
            "resultSignal",
            signal
        )

        intent.putExtra(
            "entryPrice",
            entry
        )

        intent.putExtra(
            "exitPrice",
            exit
        )

        intent.putExtra(
            "entryType",
            "OPEN"
        )

        intent.putExtra(
            "exitType",
            "CLOSE"
        )

        intent.putExtra(
            "resultPeriodId",
            periodId
        )

        intent.putExtra(
            "wins",
            wins
        )

        intent.putExtra(
            "losses",
            losses
        )

        intent.putExtra(
            "draws",
            draws
        )

        intent.putExtra(
            "accuracy",
            accuracy
        )

        /*
         * Result is officially closed.
         */
        intent.putExtra(
            "tradeClosed",
            true
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // CANDLE RUNNING
    // ============================================================

    private fun sendCandleRunningStatus() {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "CANDLE_RUNNING"
        )

        intent.putExtra(
            "remaining",
            secondsToNextBoundary()
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        intent.putExtra(
            "count",
            candleHistory.size
        )

        intent.putExtra(
            "tradeActive",
            activeTradeStarted
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // CANDLE WAITING
    // ============================================================

    private fun sendCandleWaitingStatus() {

        val remaining =
            secondsToNextBoundary()

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            if (
                remaining <=
                SIGNAL_WINDOW_SECONDS
            ) {
                "CANDLE_RUNNING"
            } else {
                "CANDLE_WAITING"
            }
        )

        intent.putExtra(
            "remaining",
            remaining
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        intent.putExtra(
            "count",
            candleHistory.size
        )

        intent.putExtra(
            "tradeActive",
            activeTradeStarted
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // ANALYSIS WAITING
    // ============================================================

    private fun sendAnalysisWaiting() {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "HISTORY_WAITING"
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // FRAME STATUS
    // ============================================================

    private fun sendFrameStatus(
        frame: Int
    ) {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "FRAME_READY"
        )

        intent.putExtra(
            "frame",
            frame
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // CANDLE COUNT
    // ============================================================

    private fun sendCandleCount(
        count: Int
    ) {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            "CANDLES_DETECTED"
        )

        intent.putExtra(
            "count",
            count
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // GENERIC STATUS
    // ============================================================

    private fun sendStatus(
        value: String
    ) {

        val intent =
            Intent(
                ACTION_STATUS
            )

        intent.setPackage(
            packageName
        )

        intent.putExtra(
            "status",
            value
        )

        intent.putExtra(
            "timeframe",
            selectedTimeframe
        )

        intent.putExtra(
            "quickMode",
            quickMode
        )

        sendBroadcast(
            intent
        )
    }

    // ============================================================
    // VISIBLE SIGNATURE
    // ============================================================

    private fun createVisibleSignature(
        candles:
            List<CandleAnalyzer.DetectedCandle>
    ): String {

        if (
            candles.isEmpty()
        ) {
            return ""
        }

        val start =
            maxOf(
                0,
                candles.size - 5
            )

        return buildString {

            for (
                i in
                start until candles.size
            ) {

                val c =
                    candles[i]

                append(
                    "%.4f".format(
                        Locale.US,
                        c.open
                    )
                )

                append("|")

                append(
                    "%.4f".format(
                        Locale.US,
                        c.high
                    )
                )

                append("|")

                append(
                    "%.4f".format(
                        Locale.US,
                        c.low
                    )
                )

                append("|")

                append(
                    "%.4f".format(
                        Locale.US,
                        c.close
                    )
                )

                append("|")

                append(
                    if (
                        c.bullish
                    ) {
                        "B"
                    } else {
                        "R"
                    }
                )

                append(";")
            }
        }
    }

    // ============================================================
    // SINGLE CANDLE SIGNATURE
    // ============================================================

    private fun createCandleSignature(
        candle:
            CandleAnalyzer.DetectedCandle
    ): String {

        return buildString {

            append(
                "%.4f".format(
                    Locale.US,
                    candle.open
                )
            )

            append("|")

            append(
                "%.4f".format(
                    Locale.US,
                    candle.high
                )
            )

            append("|")

            append(
                "%.4f".format(
                    Locale.US,
                    candle.low
                )
            )

            append("|")

            append(
                "%.4f".format(
                    Locale.US,
                    candle.close
                )
            )

            append("|")

            append(
                if (
                    candle.bullish
                ) {
                    "B"
                } else {
                    "R"
                }
            )
        }
    }

    // ============================================================
    // HISTORY LIMIT
    // ============================================================

    private fun trimHistory() {

        while (
            candleHistory.size >
            MAX_HISTORY
        ) {

            candleHistory.removeAt(0)
        }
    }

    // ============================================================
    // RELEASE
    // ============================================================

    private fun releaseCapture() {

        running = false

        try {

            imageReader
                ?.setOnImageAvailableListener(
                    null,
                    null
                )

        } catch (_: Exception) {
        }

        try {
            imageReader?.close()
        } catch (_: Exception) {
        }

        imageReader = null

        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }

        virtualDisplay = null

        try {

            projection
                ?.unregisterCallback(
                    projectionCallback
                )

        } catch (_: Exception) {
        }

        try {
            projection?.stop()
        } catch (_: Exception) {
        }

        projection = null
    }

    // ============================================================
    // STOP FOREGROUND
    // ============================================================

    private fun stopForegroundSafe() {

        try {

            if (
                Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.N
            ) {

                stopForeground(
                    STOP_FOREGROUND_REMOVE
                )

            } else {

                @Suppress("DEPRECATION")
                stopForeground(true)
            }

        } catch (_: Exception) {
        }
    }

    // ============================================================
    // DESTROY
    // ============================================================

    override fun onDestroy() {

        running = false

        releaseCapture()

        stopCaptureThread()

        mainHandler
            .removeCallbacksAndMessages(null)

        stopForegroundSafe()

        super.onDestroy()
    }

    override fun onBind(
        intent: Intent?
    ): IBinder? {
        return null
    }
}
