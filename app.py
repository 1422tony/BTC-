import os
import time
import ccxt
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- 設定區 ---
# 強制緩存時間 (秒)：在這段時間內，絕對不會重複呼叫幣安 API
CACHE_DURATION = 20 

# 全局變數用來存儲緩存
global_cache = {
    "data": None,
    "last_update_time": 0
}

# 初始化：只需要讀取權限
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_READ_KEY'),
    'secret': os.getenv('BINANCE_READ_SECRET'),
    'options': {'defaultType': 'future'},
    'enableRateLimit': True  # 啟用 CCXT 內建的頻率限制保護
})

# --- 核心演算法 ---
def calculate_rebalance_plan(target_leverage=1.5):
    try:
        # 1. 獲取數據
        balance = exchange.fetch_balance()
        margin_balance = float(balance['info']['totalWalletBalance']) 
        
        positions = balance['info']['positions']
        btc_pos = next((p for p in positions if p['symbol'] == 'BTCUSDT'), None)
        
        if not btc_pos:
            return {"error": "No BTC Position found"}
            
        amt = abs(float(btc_pos['positionAmt']))
        
        ticker = exchange.fetch_ticker('BTC/USDT')
        current_price = ticker['last']
        
        position_value = amt * current_price
        current_leverage = position_value / margin_balance if margin_balance > 0 else 0
        
        # --- 計算再平衡 ---
        required_margin = position_value / target_leverage
        diff_usdt = required_margin - margin_balance
        
        btc_to_sell = 0
        if diff_usdt > 0:
            btc_to_sell = diff_usdt / current_price * 1.01

        return {
            "success": True,
            "timestamp": time.strftime("%H:%M:%S"), # 紀錄資料時間
            "price": current_price,
            "amt": amt,
            "position_value": round(position_value, 2),
            "margin_balance": round(margin_balance, 2),
            "current_leverage": round(current_leverage, 2),
            "target_leverage": target_leverage,
            "action_needed": diff_usdt > 10,
            "instruction": {
                "transfer_usdt": round(diff_usdt, 2),
                "sell_spot_btc": round(btc_to_sell, 5) if diff_usdt > 0 else 0
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

# --- API 接口 (包含緩存邏輯) ---
@app.route('/api/status')
def api_status():
    current_time = time.time()
    
    # 檢查緩存：如果距離上次更新還不到 CACHE_DURATION 秒，直接回傳舊資料
    # 這樣可以 100% 確保不會因為前端刷新而爆 API
    if global_cache["data"] and (current_time - global_cache["last_update_time"] < CACHE_DURATION):
        print("Using Cache Data (No API Call)") # Log 方便觀察
        return jsonify(global_cache["data"])

    # 如果緩存過期，才真的去呼叫幣安
    print("Fetching New Data from Binance...")
    data = calculate_rebalance_plan()
    
    # 只有當成功獲取數據時才更新緩存
    if data.get("success"):
        global_cache["data"] = data
        global_cache["last_update_time"] = current_time
    
    return jsonify(data)

# --- 前端頁面 ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BTC 套利指揮官 (安全版)</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
        <div class="max-w-md w-full bg-gray-800 p-8 rounded-xl shadow-2xl" id="app">
            <h1 class="text-2xl font-bold mb-2 text-center text-yellow-400">⚡ 套利監控面板</h1>
            <p class="text-center text-gray-500 text-xs mb-6">資料更新時間: <span id="data-time">--</span></p>
            
            <div id="loading" class="text-center">載入中...</div>
            
            <div id="content" class="hidden space-y-4">
                <div class="grid grid-cols-2 gap-4 text-center">
                    <div class="bg-gray-700 p-3 rounded">
                        <p class="text-gray-400 text-xs">當前價格</p>
                        <p class="text-xl font-mono" id="price">--</p>
                    </div>
                    <div class="bg-gray-700 p-3 rounded">
                        <p class="text-gray-400 text-xs">真實槓桿</p>
                        <p class="text-2xl font-bold" id="lev">--</p>
                    </div>
                </div>

                <div id="action-box" class="bg-green-900/50 border border-green-500 p-4 rounded-lg hidden">
                    <h2 class="text-green-400 font-bold mb-2">✅ 目前狀態安全</h2>
                    <p class="text-sm text-gray-300">槓桿比例健康，無需操作。</p>
                </div>
                
                <div id="warning-box" class="bg-red-900/50 border border-red-500 p-4 rounded-lg hidden animate-pulse">
                    <h2 class="text-red-400 font-bold mb-2">⚠️ 需要再平衡！</h2>
                    <ul class="text-sm space-y-2 list-disc list-inside">
                        <li>現貨賣出: <span class="font-bold text-white" id="sell-amt"></span> BTC</li>
                        <li>資金劃轉: 現貨 -> 合約 <span class="font-bold text-white" id="transfer-amt"></span> U</li>
                    </ul>
                </div>
                
                <div class="text-xs text-center text-gray-500 mt-4">
                    目標槓桿: 1.5x | 自動刷新: 30秒<br>
                    <span class="text-red-400">注意：請勿頻繁手動刷新網頁</span>
                </div>
            </div>
        </div>

        <script>
            async function fetchStatus() {
                try {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    
                    if(data.error) {
                        console.error(data.error);
                        // 如果出錯，不要 alert 騷擾，顯示在 console 就好
                        return;
                    }

                    document.getElementById('loading').classList.add('hidden');
                    document.getElementById('content').classList.remove('hidden');
                    
                    document.getElementById('data-time').innerText = data.timestamp;
                    document.getElementById('price').innerText = `$${data.price.toLocaleString()}`;
                    
                    const levEl = document.getElementById('lev');
                    levEl.innerText = `${data.current_leverage}x`;
                    levEl.className = `text-2xl font-bold ${data.current_leverage > 2.0 ? 'text-red-500' : 'text-green-400'}`;

                    const diff = data.instruction.transfer_usdt;
                    
                    if (data.current_leverage > 1.8 && diff > 0) {
                        document.getElementById('action-box').classList.add('hidden');
                        document.getElementById('warning-box').classList.remove('hidden');
                        document.getElementById('sell-amt').innerText = data.instruction.sell_spot_btc;
                        document.getElementById('transfer-amt').innerText = diff;
                    } else {
                        document.getElementById('warning-box').classList.add('hidden');
                        document.getElementById('action-box').classList.remove('hidden');
                    }
                } catch (e) {
                    console.error(e);
                }
            }

            fetchStatus();
            // 改成 30 秒刷新一次，更加安全
            setInterval(fetchStatus, 30000); 
        </script>
    </body>
    </html>
    """)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))