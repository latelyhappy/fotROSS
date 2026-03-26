from flask import Flask, render_template, jsonify, request
import threading

# 載入我們的自訂模組
import config
import scanner

app = Flask(__name__)

# ==========================================
# 網頁路由 1：顯示首頁戰情室介面
# ==========================================
@app.route('/')
def index():
    # 這裡會去讀取 templates 資料夾底下的 index.html
    return render_template('index.html')

# ==========================================
# 網頁路由 2：傳送最新 AI 運算數據給前端
# ==========================================
@app.route('/data')
def get_data():
    # 將 config.py 裡面的 MASTER_BRAIN 字典，轉成 JSON 傳給網頁
    return jsonify(config.MASTER_BRAIN)

# ==========================================
# 網頁路由 3：接收前端手動輸入的狙擊代碼 (V4.0 新增)
# ==========================================
@app.route('/add_target', methods=['POST'])
def add_target():
    # 接收前端網頁傳來的股票代碼，並轉成大寫去空白
    ticker = request.form.get('ticker', '').strip().upper()
    if ticker:
        # 寫入 watchlist.txt 讓 scanner.py 讀取並啟動追蹤
        try:
            with open("watchlist.txt", "a") as f:
                f.write(ticker + "\n")
            print(f"🎯 成功接收並寫入目標: {ticker}")
            return jsonify({"status": "success", "ticker": ticker})
        except Exception as e:
            print(f"寫入 watchlist.txt 失敗: {e}")
            return jsonify({"status": "error"}), 500
            
    return jsonify({"status": "error"}), 400

# ==========================================
# 主程式啟動區
# ==========================================
if __name__ == '__main__':
    print("🚀 系統啟動中...")
    
    # 1. 在背景獨立啟動 V4.0 終極掃描引擎 (Webull VIP 雷達 + Yahoo 狙擊鏡)
    engine_thread = threading.Thread(target=scanner.scanner_engine, daemon=True)
    engine_thread.start()
    
    # 2. 啟動 Flask 網頁伺服器 (供您用瀏覽器連線觀看)
    # 注意：use_reloader=False 確保背景的 scanner 引擎不會被重複啟動兩次
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
