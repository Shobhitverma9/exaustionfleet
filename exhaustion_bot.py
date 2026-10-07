import os
import time
import json
import asyncio
import websockets
import requests
import pandas as pd
import numpy as np
from collections import deque
from datetime import datetime
import sys

# Ensure local strategy folder is accessible
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from strategy.reversal_engine import ReversalEngine

class ExhaustionBot:
    def __init__(self, symbol):
        self.symbol = symbol
        self.min_stake = 5.0
        self.base_risk_pct = 0.01
        self.min_payout_pct = 68.0
        self.candles_to_fetch = 200
        self.duration = 15
        self.duration_unit = "m"
        
        self.use_time_filter = True
        self.blackout_start = 6
        self.blackout_end = 8
        self.block_thursdays = True
        
        self.bot_state = {
            "total_trades": 0,
            "trades_won": 0,
            "trades_lost": 0,
            "starting_balance": 0.0,
            "current_balance": 0.0,
            "total_profit": 0.0,
            "last_signal": "None",
            "last_signal_time": "Never",
            "last_candle_rsi": 0.0,
            "last_candle_body": 0.0,
            "last_candle_avg_body": 0.0,
            "last_update": "Never",
            "last_trade_epoch": 0,
            "pending_trade_details": {}
        }
        
        self.app_logs = deque(maxlen=100)
        self.trade_history = deque(maxlen=50)
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.engine = ReversalEngine()

    def log(self, msg):
        now = datetime.now()
        time_str = now.strftime('%Y-%m-%d %H:%M:%S')
        formatted = f"[{time_str}] [{self.symbol}] {msg}"
        print(formatted)
        self.app_logs.appendleft(formatted)
        
        # Persist logs to data directory
        with open(f"{self.data_dir}/{self.symbol}_log.txt", "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
        self.save_state()

    def save_state(self):
        state_file = f"{self.data_dir}/state_{self.symbol}.json"
        full_state = {
            "symbol": self.symbol,
            "bot_state": self.bot_state,
            "app_logs": list(self.app_logs),
            "trade_history": list(self.trade_history)
        }
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(full_state, f, indent=4)
        except Exception as e:
            print(f"[{self.symbol}] Failed to save state: {e}")

    async def get_otp_ws_url(self):
        token = os.environ.get("DERIV_API_TOKEN")
        account = os.environ.get("DERIV_ACCOUNT_ID")
        app_id = os.environ.get("DERIV_APP_ID")
        if not token or not account or not app_id:
            self.log("ERROR: Missing API credentials.")
            return None
            
        url = f"https://api.derivws.com/trading/v1/options/accounts/{account}/otp"
        headers = {
            "Authorization": f"Bearer {token}",
            "Deriv-App-ID": app_id,
            "Content-Type": "application/json"
        }
        try:
            res = requests.post(url, headers=headers)
            if res.status_code == 200:
                return res.json().get("data", {}).get("url")
        except Exception as e:
            self.log(f"OTP URL fetch failed: {e}")
        return None

    async def fetch_balance(self, retries=3, delay=5):
        for attempt in range(1, retries + 1):
            ws_url = await self.get_otp_ws_url()
            if not ws_url:
                await asyncio.sleep(delay)
                continue
            try:
                async with websockets.connect(ws_url, open_timeout=10) as ws:
                    await ws.send(json.dumps({"balance": 1}))
                    res = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if "balance" in res:
                        return float(res["balance"]["balance"])
            except Exception:
                if attempt < retries:
                    await asyncio.sleep(delay)
        return None

    async def monitor_contract(self, contract_id, trade_info=None):
        ws_url = await self.get_otp_ws_url()
        if not ws_url:
            return
        self.log(f"Monitoring contract {contract_id}...")
        try:
            async with websockets.connect(ws_url) as ws:
                req = {"proposal_open_contract": 1, "contract_id": contract_id, "subscribe": 1}
                await ws.send(json.dumps(req))
                while True:
                    res = json.loads(await ws.recv())
                    if "error" in res:
                        break
                    contract = res.get("proposal_open_contract", {})
                    if contract.get("is_sold"):
                        profit = float(contract.get("profit", 0.0))
                        status = contract.get("status")
                        self.log(f"Contract {contract_id} closed! Status: {status}, Profit: ${profit:.2f}")
                        
                        self.bot_state["total_profit"] += profit
                        if profit > 0:
                            self.bot_state["trades_won"] += 1
                        else:
                            self.bot_state["trades_lost"] += 1
                            
                        bal = await self.fetch_balance()
                        if bal is not None:
                            self.bot_state["current_balance"] = bal
                            
                        if trade_info:
                            trade_info["profit"] = profit
                            trade_info["status"] = status
                            trade_info["balance_after"] = self.bot_state["current_balance"]
                        self.save_state()
                        break
        except Exception as e:
            self.log(f"Error monitoring contract {contract_id}: {e}")

    async def execute_trade(self, contract_type):
        bal = await self.fetch_balance()
        if bal is not None:
            self.bot_state["current_balance"] = bal
        else:
            bal = self.bot_state["current_balance"]

        if bal < self.min_stake:
            self.log(f"⚠️ Insufficient balance (${bal:.2f}).")
            return

        dynamic_stake = 10.00
        
        ws_url = await self.get_otp_ws_url()
        if not ws_url:
            return

        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                proposal_req = {
                    "proposal": 1,
                    "amount": dynamic_stake,
                    "basis": "stake",
                    "contract_type": contract_type,
                    "currency": "USD",
                    "underlying_symbol": self.symbol,
                    "duration": self.duration,
                    "duration_unit": self.duration_unit
                }
                await ws.send(json.dumps(proposal_req))
                res = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))

                if "error" in res:
                    return

                proposal = res.get("proposal", {})
                proposal_id = proposal.get("id")
                ask_price = proposal.get("ask_price")
                payout = proposal.get("payout")

                if ask_price and payout:
                    payout_pct = ((payout - ask_price) / ask_price) * 100
                    if payout_pct < self.min_payout_pct:
                        self.log(f"⚠️ Rejected — payout only {payout_pct:.1f}% (Required: {self.min_payout_pct}%)")
                        return

                buy_req = {"buy": proposal_id, "price": ask_price}
                await ws.send(json.dumps(buy_req))
                buy_res = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))

                if "error" not in buy_res:
                    contract_id = buy_res['buy']['contract_id']
                    self.log(f"✅ Trade Executed! {contract_type} | Stake: ${dynamic_stake:.2f}")
                    self.bot_state["total_trades"] += 1

                    trade_info = {
                        "contract_id": contract_id,
                        "type": contract_type,
                        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "details": self.bot_state.get("pending_trade_details", {}).copy(),
                        "balance_before": self.bot_state["current_balance"],
                        "profit": 0.0,
                        "balance_after": 0.0,
                        "status": "OPEN"
                    }
                    self.trade_history.appendleft(trade_info)
                    self.save_state()
                    asyncio.create_task(self.monitor_contract(contract_id, trade_info))
        except Exception as e:
            self.log(f"❌ execute_trade error: {e}")

    async def fetch_recent_candles(self):
        uri = "wss://api.derivws.com/trading/v1/options/ws/public"
        try:
            async with websockets.connect(uri) as ws:
                req = {
                    "ticks_history": self.symbol,
                    "adjust_start_time": 1,
                    "count": self.candles_to_fetch,
                    "end": "latest",
                    "style": "candles",
                    "granularity": 300 
                }
                await ws.send(json.dumps(req))
                response = json.loads(await ws.recv())
                return response.get("candles", [])
        except Exception as e:
            self.log(f"API Fetch Error: {e}")
            return []

    def check_for_signal(self, candles):
        if len(candles) < 100:
            self.log("Not enough candles fetched to stabilize RSI.")
            return None
            
        df = pd.DataFrame(candles)
        
        current_epoch = int(time.time())
        current_boundary_epoch = current_epoch - (current_epoch % 300)
        
        if df.iloc[-1]['epoch'] >= current_boundary_epoch:
            df = df.iloc[:-1].copy()
        else:
            df = df.copy()
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
        
        result = self.engine.generate(df)
        
        last_closed = df.iloc[-1]
        candle_time = pd.to_datetime(last_closed['epoch'], unit='s')
        current_hour = candle_time.hour
        
        self.bot_state["last_update"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if self.use_time_filter and (self.blackout_start <= current_hour < self.blackout_end):
            self.bot_state["last_update"] = f"{candle_time} (Blackout Period)"
            self.log(f"⏸️ Signal ignored. {current_hour}:00 is within blackout.")
            return None
            
        if self.block_thursdays and candle_time.dayofweek == 3:
            self.bot_state["last_update"] = f"{candle_time} (Thursday Block)"
            self.log("⏸️ Signal ignored. Trading disabled on Thursdays.")
            return None
        
        self.log(f"Analyzed 5m candle (Epoch: {candle_time}) -> Engine: {result.get('signal')}")

        signal = result.get('signal')
        if signal:
            if last_closed['epoch'] <= self.bot_state.get("last_trade_epoch", 0):
                return None
            
            self.log(f"🔥 {signal} SIGNAL GENERATED! {result.get('reason')}")
            self.bot_state["last_signal"] = signal
            self.bot_state["last_signal_time"] = self.bot_state["last_update"]
            self.bot_state["last_trade_epoch"] = last_closed['epoch']
            self.bot_state["pending_trade_details"] = {"reason": result.get("reason")}
            return signal
                
        return None

    async def run_bot_cycle(self):
        try:
            self.log("Running Exhaustion strategy cycle...")
            candles = await self.fetch_recent_candles()
            if not candles:
                return
                
            signal = self.check_for_signal(candles)
            if signal:
                await self.execute_trade(signal)
        except Exception as e:
            self.log(f"⚠️ Network Error during cycle: {e}")

    async def run(self):
        for attempt in range(1, 6):
            bal = await self.fetch_balance()
            if bal is not None:
                self.bot_state["starting_balance"] = bal
                self.bot_state["current_balance"] = bal
                self.log(f"✅ Starting balance: ${bal:.2f}")
                break
            await asyncio.sleep(10)

        self.log(f"Bot Started for {self.symbol}! Waiting for boundary...")
        await self.run_bot_cycle()
        
        while True:
            now = datetime.now()
            minutes = now.minute
            next_min = ((minutes // 5) + 1) * 5
            seconds_to_sleep = ((next_min * 60) - (minutes * 60 + now.second)) + 4
            
            if next_min >= 60:
                self.log(f"Sleeping for {seconds_to_sleep}s until next hour...")
            else:
                self.log(f"Sleeping for {seconds_to_sleep}s until XX:{next_min:02d}:04...")
                
            await asyncio.sleep(seconds_to_sleep)
            await self.run_bot_cycle()
