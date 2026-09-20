package com.example.screener

object DemoTradeManager {

    data class DemoTrade(
        val signal: String,
        val timeframe: String,
        val confidence: Int,
        val entryPrice: Double,
        val exitPrice: Double,
        val result: String
    )

    var totalTrades = 0
        private set

    var wins = 0
        private set

    var losses = 0
        private set

    var balance = 10000.0
        private set

    private const val START_BALANCE = 10000.0
    private const val STAKE = 100.0

    private var activeTrade: DemoTrade? = null

    private val history =
        mutableListOf<DemoTrade>()

    fun hasActiveTrade(): Boolean {
        return activeTrade != null
    }

    fun openTrade(
        signal: String,
        timeframe: String,
        confidence: Int,
        entryPrice: Double
    ): Boolean {

        if (activeTrade != null) {
            return false
        }

        if (
            signal != "CALL" &&
            signal != "PUT"
        ) {
            return false
        }

        if (confidence < 90) {
            return false
        }

        if (balance < STAKE) {
            return false
        }

        balance -= STAKE

        activeTrade =
            DemoTrade(
                signal = signal,
                timeframe = timeframe,
                confidence = confidence,
                entryPrice = entryPrice,
                exitPrice = entryPrice,
                result = "OPEN"
            )

        return true
    }

    fun closeTrade(
        exitPrice: Double
    ): String {

        val trade =
            activeTrade
                ?: return "NO ACTIVE TRADE"

        val win =
            when (trade.signal) {

                "CALL" ->
                    exitPrice > trade.entryPrice

                "PUT" ->
                    exitPrice < trade.entryPrice

                else ->
                    false
            }

        val result =
            if (win) {
                "WIN"
            } else {
                "LOSS"
            }

        if (win) {

            wins++

            /*
             * Demo payout simulation:
             * stake + 80% profit
             */
            balance +=
                STAKE * 1.80

        } else {

            losses++
        }

        totalTrades++

        val completedTrade =
            trade.copy(
                exitPrice = exitPrice,
                result = result
            )

        history.add(
            completedTrade
        )

        activeTrade = null

        return result
    }

    fun currentTrade(): DemoTrade? {
        return activeTrade
    }

    fun accuracy(): Int {

        if (totalTrades == 0) {
            return 0
        }

        return (
            wins * 100.0 /
                totalTrades
            ).toInt()
    }

    fun profitLoss(): Double {

        return balance -
            START_BALANCE
    }

    fun tradeHistory(): List<DemoTrade> {
        return history.toList()
    }

    fun reset() {

        totalTrades = 0
        wins = 0
        losses = 0

        balance =
            START_BALANCE

        activeTrade = null

        history.clear()
    }

    fun summary(): String {

        val pnl =
            profitLoss()

        val pnlText =
            if (pnl >= 0) {
                "+%.2f".format(pnl)
            } else {
                "%.2f".format(pnl)
            }

        val active =
            if (activeTrade != null) {
                "\nACTIVE: " +
                    activeTrade!!.signal
            } else {
                "\nACTIVE: NONE"
            }

        return (
            "DEMO AUTO TEST\n" +
            "Balance: %.2f\n".format(balance) +
            "Total: $totalTrades\n" +
            "WIN: $wins\n" +
            "LOSS: $losses\n" +
            "Accuracy: ${accuracy()}%\n" +
            "P/L: $pnlText" +
            active
        )
    }
}
