import os
import time
import threading
import ccxt
from flask import Flask
from datetime import datetime

# --- 配置區 ---
# 為了避免 Render 找不到變數報錯，這裡加個預設值或安全檢查
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_SECRET')
# Render 會自動提供 PORT 變數，預設 10000
PORT = int(os.environ.get("PORT", 10000))

# 初始化 Flask
app = Flask(__name__)

# 全局變數用來存儲機器人狀態 (讓網頁能顯示)
bot_status = {
    "last_check": "Not started",
    "leverage": 0,
    "msg": "Initializing..."
}

# --- 交易邏輯區 (與之前相同，但封裝得更健壯) ---
def run_bot_logic():
    print("🚀 機器人背景執行緒啟動...")
    
    # 初始化交易所 (建議在這裡初始化，避免全域變數問題)
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

    while True:
        try:
            # 1. 獲取數據
            balance = exchange.fetch_balance()
            margin_balance = float(balance['info']['totalWalletBalance']) # 使用 totalWalletBalance 更準確
            
            # 獲取倉位
            positions = balance['info']['positions']
            btc_pos = next((p for p in positions if p['symbol'] == 'BTCUSDT'), None)
            
            if btc_pos:
                # 計算槓桿
                amt = abs(float(btc_pos['positionAmt']))
                ticker = exchange.fetch_ticker('BTC/USDT')
                price = ticker['last']
                position_value = amt * price
                
                if margin_balance > 0:
                    leverage = position_value / margin_balance
                else:
                    leverage = 0

                # 更新狀態給 Flask 顯示
                bot_status["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                bot_status["leverage"] = round(leverage, 2)
                bot_status["msg"] = "Monitoring..."
                
                print(f"[{bot_status['last_check']}] 槓桿: {leverage:.2f}x | 價格: {price}")

                # --- 觸發條件 (範例) ---
                if leverage > 2.2:
                    bot_status["msg"] = "⚠️ TRIGGERED REBALANCE!"
                    # TODO: 在這裡呼叫您的 rebalance() 函數
                    # rebalance(exchange, ...)
            
            else:
                bot_status["msg"] = "No BTC Position found"

        except Exception as e:
            print(f"Error: {e}")
            bot_status["msg"] = f"Error: {str(e)}"

        # 休眠 60 秒 (Render 免費版建議不要太頻繁，避免被判定濫用)
        time.sleep(60)

# --- Flask 路由區 ---
@app.route('/')
def index():
    # 這是給外部喚醒服務打的接口，也是給您自己看狀態的儀表板
    return f"""
    <h1>🤖 Crypto Arb Bot is Running</h1>
    <p>Last Check: {bot_status['last_check']}</p>
    <p>Current Leverage: <strong>{bot_status['leverage']}x</strong></p>
    <p>Status: {bot_status['msg']}</p>
    """

@app.route('/health')
def health():
    # 專門給 Uptime Robot 的輕量接口
    return "OK", 200

# --- 啟動區 ---
# 使用 threading 在背景運行交易邏輯
if __name__ != '__main__':
    # 這段是為了配合 Gunicorn，當 Gunicorn 載入 app 時啟動執行緒
    t = threading.Thread(target=run_bot_logic)
    t.daemon = True # 設為守護執行緒，主程式結束它也會結束
    t.start()

if __name__ == '__main__':
    # 本地開發測試用
    t = threading.Thread(target=run_bot_logic)
    t.daemon = True
    t.start()
    app.run(debug=True, port=PORT)