import os
import asyncio
import json
import glob
from aiohttp import web
from dotenv import load_dotenv

# Import the generalized bot class
from exhaustion_bot import ExhaustionBot

# --- DASHBOARD HTML ---
def get_dashboard_html():
    states = {}
    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    
    # Load all states
    for state_file in glob.glob(f"{data_dir}/state_*.json"):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                states[data["symbol"]] = data
        except Exception:
            pass

    if not states:
        return "<h1>No bot data available yet. Please wait for the first cycle...</h1>"

    html_content = """
    <html>
    <head>
        <title>Exhaustion Fleet Dashboard</title>
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
            h1 { text-align: center; color: #38bdf8; margin-bottom: 30px; font-weight: 800; letter-spacing: 1px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 25px; max-width: 1400px; margin: 0 auto; }
            .card { background: #1e293b; padding: 25px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }
            h2 { margin-top: 0; color: #fbbf24; border-bottom: 1px solid #334155; padding-bottom: 10px; }
            .stat { margin: 10px 0; font-size: 16px; display: flex; justify-content: space-between; }
            .stat span { font-weight: 600; color: #cbd5e1; }
            .win { color: #10b981 !important; }
            .loss { color: #ef4444 !important; }
            .log-box { background: #000; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 13px; height: 250px; overflow-y: auto; color: #a3e635; margin-top: 15px; border: 1px solid #334155;}
            .total-profit { text-align: center; font-size: 24px; padding: 20px; background: #1e293b; border-radius: 12px; margin: 0 auto 30px auto; max-width: 400px; color: #10b981; font-weight: bold; border: 1px solid #10b981; box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
        </style>
        <meta http-equiv="refresh" content="30">
    </head>
    <body>
        <h1>🚀 Elite Exhaustion Fleet (BB 2.5 + RSI 80)</h1>
    """
    
    total_fleet_profit = sum(bot["bot_state"].get("total_profit", 0) for bot in states.values())
    html_content += f'<div class="total-profit">Total Fleet Profit: ${total_fleet_profit:.2f}</div>'
    html_content += '<div class="grid">'

    for symbol, data in states.items():
        state = data.get("bot_state", {})
        logs = data.get("app_logs", [])
        
        profit = state.get('total_profit', 0)
        profit_class = "win" if profit >= 0 else "loss"
        
        html_content += f"""
        <div class="card">
            <h2>{symbol}</h2>
            <div class="stat">Total Trades: <span>{state.get('total_trades', 0)}</span></div>
            <div class="stat">Wins / Losses: <span><span class="win">{state.get('trades_won', 0)}</span> / <span class="loss">{state.get('trades_lost', 0)}</span></span></div>
            <div class="stat">Current Balance: <span>${state.get('current_balance', 0):.2f}</span></div>
            <div class="stat">Net Profit: <span class="{profit_class}">${profit:.2f}</span></div>
            <div class="stat">Last Signal: <span>{state.get('last_signal', 'None')} ({state.get('last_signal_time', 'Never')})</span></div>
            <div class="stat">Last Update: <span>{state.get('last_update', 'Never')}</span></div>
            <div class="log-box">
                {"<br>".join(logs[:15])}
            </div>
        </div>
        """
        
    html_content += "</div></body></html>"
    return html_content

async def handle_home(request):
    return web.Response(text=get_dashboard_html(), content_type='text/html')

async def init_web():
    app = web.Application()
    app.router.add_get('/', handle_home)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🚀 Web Dashboard running on port {port}")

async def main():
    load_dotenv()
    
    # 1. Start Web Dashboard
    await init_web()
    
    # 2. Initialize Elite Bots
    eurusd_bot = ExhaustionBot("frxEURUSD")
    usdchf_bot = ExhaustionBot("frxUSDCHF")
    
    # 3. Run all bots concurrently in the background
    print("Launching Exhaustion Fleet...")
    await asyncio.gather(
        eurusd_bot.run(),
        usdchf_bot.run()
    )

if __name__ == '__main__':
    asyncio.run(main())
