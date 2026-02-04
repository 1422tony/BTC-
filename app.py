import os
import ccxt
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# 初始化：只需要讀取權限
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_READ_KEY'),
    'secret': os.getenv('BINANCE_READ_SECRET'),
    'options': {'defaultType': 'future'}
})

# --- 核心演算法 ---
def calculate_rebalance_plan(target_leverage=1.5):
    try:
        # 1. 獲取數據
        balance = exchange.fetch_balance()
        # 合約帳戶保證金餘額 (Total Margin Balance)
        margin_balance = float(balance['info']['totalWalletBalance']) 
        
        # 獲取 BTC 持倉
        positions = balance['info']['positions']
        btc_pos = next((p for p in positions if p['symbol'] == 'BTCUSDT'), None)
        
        if not btc_pos:
            return {"error": "No BTC Position found"}
            
        # 計算當前狀態
        amt = abs(float(btc_pos['positionAmt'])) # 持倉數量 (顆)
        entry_price = float(btc_pos['entryPrice'])
        
        # 獲取即時價格
        ticker = exchange.fetch_ticker('BTC/USDT')
        current_price = ticker['last']
        
        position_value = amt * current_price
        current_leverage = position_value / margin_balance if margin_balance > 0 else 0
        
        # --- 計算再平衡建議 ---
        # 目標公式： PositionValue / (CurrentMargin + ToAdd) = TargetLeverage
        # 變換公式： ToAdd = (PositionValue / TargetLeverage) - CurrentMargin
        
        required_margin = position_value / target_leverage
        diff_usdt = required_margin - margin_balance
        
        # 為了要補這筆 USDT，我需要賣多少現貨 BTC？
        btc_to_sell = 0
        if diff_usdt > 0:
            btc_to_sell = diff_usdt / current_price * 1.01 # 多賣 1% 當手續費緩衝

        return {
            "price": current_price,
            "amt": amt,
            "position_value": round(position_value, 2),
            "margin_balance": round(margin_balance, 2),
            "current_leverage": round(current_leverage, 2),
            "target_leverage": target_leverage,
            "action_needed": diff_usdt > 10, # 只有差額大於 10U 才建議操作
            "instruction": {
                "transfer_usdt": round(diff_usdt, 2), # 正數代表要補錢，負數代表可以領錢
                "sell_spot_btc": round(btc_to_sell, 5) if diff_usdt > 0 else 0
            }
        }

    except Exception as e:
        return {"error": str(e)}

# --- API 接口 ---
@app.route('/api/status')
def api_status():
    data = calculate_rebalance_plan()
    return jsonify(data)

# --- 前端頁面 (您可以在這裡發揮前端實力，這裡先給個簡單版) ---
@app.route('/')
def index():
    # 使用 render_template_string 方便演示，實際專案建議分開寫 .html
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BTC 套利指揮官</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
        <div class="max-w-md w-full bg-gray-800 p-8 rounded-xl shadow-2xl" id="app">
            <h1 class="text-2xl font-bold mb-6 text-center text-yellow-400">⚡ 套利監控面板</h1>
            
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
                
                <p class="text-xs text-center text-gray-500 mt-4">目標槓桿: 1.5x | 每 10 秒自動刷新</p>
            </div>
        </div>

        <script>
            async function fetchStatus() {
                try {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    
                    if(data.error) {
                        alert(data.error);
                        return;
                    }

                    document.getElementById('loading').classList.add('hidden');
                    document.getElementById('content').classList.remove('hidden');
                    
                    document.getElementById('price').innerText = `$${data.price.toLocaleString()}`;
                    
                    // 槓桿顏色邏輯
                    const levEl = document.getElementById('lev');
                    levEl.innerText = `${data.current_leverage}x`;
                    levEl.className = `text-2xl font-bold ${data.current_leverage > 2.0 ? 'text-red-500' : 'text-green-400'}`;

                    // 判斷是否顯示操作建議
                    const diff = data.instruction.transfer_usdt;
                    
                    if (data.current_leverage > 1.8 && diff > 0) { // 設定觸發顯示的門檻 (例如槓桿 > 1.8 才叫你動)
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
            setInterval(fetchStatus, 10000); // 每10秒刷新
        </script>
    </body>
    </html>
    """)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))