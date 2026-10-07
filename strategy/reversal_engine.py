import pandas as pd
import ta

class ReversalEngine:
    def __init__(self, bb_window=20, bb_dev=2.5, rsi_window=14, rsi_ob=80, rsi_os=20):
        self.bb_window = bb_window
        self.bb_dev = bb_dev
        self.rsi_window = rsi_window
        self.rsi_ob = rsi_ob
        self.rsi_os = rsi_os

    def generate(self, df: pd.DataFrame) -> dict:
        """
        Expects a pandas DataFrame with at least 'open', 'high', 'low', 'close'.
        Returns a dict: {"signal": "CALL" | "PUT" | None, "confidence": float, "reason": str}
        """
        if len(df) < self.bb_window + 2:
            return {"signal": None, "confidence": 0, "reason": "Not enough data"}

        # Calculate indicators
        rsi_series = ta.momentum.RSIIndicator(df['close'], window=self.rsi_window).rsi()
        bb = ta.volatility.BollingerBands(df['close'], window=self.bb_window, window_dev=self.bb_dev)
        bb_high = bb.bollinger_hband()
        bb_low = bb.bollinger_lband()
        
        # Get last two candles (current fully closed, and previous)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        curr_rsi = rsi_series.iloc[-1]
        prev_rsi = rsi_series.iloc[-2]
        
        curr_bb_high = bb_high.iloc[-1]
        curr_bb_low = bb_low.iloc[-1]
        prev_bb_high = bb_high.iloc[-2]
        prev_bb_low = bb_low.iloc[-2]
        
        # Check PUT condition (Bearish Exhaustion Reversal)
        # 1. Previous candle pierced Upper BB and RSI was overbought
        if prev['high'] > prev_bb_high and prev_rsi > self.rsi_ob:
            # 2. Current candle is bearish (close < open) and closes back inside the BB
            if curr['close'] < curr['open'] and curr['close'] < curr_bb_high:
                return {
                    "signal": "PUT",
                    "confidence": 85.0,
                    "reason": f"Bearish Reversal after BB Exhaustion (Prev RSI: {prev_rsi:.1f}, Pierced {prev_bb_high:.5f})"
                }
                
        # Check CALL condition (Bullish Exhaustion Reversal)
        # 1. Previous candle pierced Lower BB and RSI was oversold
        if prev['low'] < prev_bb_low and prev_rsi < self.rsi_os:
            # 2. Current candle is bullish (close > open) and closes back inside the BB
            if curr['close'] > curr['open'] and curr['close'] > curr_bb_low:
                return {
                    "signal": "CALL",
                    "confidence": 85.0,
                    "reason": f"Bullish Reversal after BB Exhaustion (Prev RSI: {prev_rsi:.1f}, Pierced {prev_bb_low:.5f})"
                }

        return {"signal": None, "confidence": 0, "reason": "No exhaustion reversal detected"}
