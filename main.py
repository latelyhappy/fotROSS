import os, time, threading, requests, random, warnings
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

# 基礎配置
warnings.filterwarnings('ignore')
app = Flask(__name__); CORS(app)

# [cite_start]★ 極簡數據大腦 [cite: 1]
MASTER_BRAIN = {
    "stocks": [],
    "last_update": "等待中...",
    "scan_count": 0
}

STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 極簡 UI：只有一個表格，方便觀察 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V166.0 - 極簡診斷版</title>
    <style>
        body { background: #050811; color: #fff; font-family: sans-serif; padding: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #30363d; padding: 10px; text-align: left; }
        th { background: #1E3A8A; }
        .status-bar { background: #0d1117; padding: 10px; border: 1px solid #30363d; border-radius: 5px; }
        .highlight { color: #3fb950; font-weight: bold; }
    </style>
</head>
<body>
    <div class="status-bar">
        <div>📡 系統狀態: <span class="highlight" id="stat-text">連線中...</span></div>
        <div>🕒 最後掃描時間: <span id="last-update">N/A</span></div>
        <div>🔢 累計掃描次數: <span id="scan-count">0</span></div>
    </div>

    <table id="data-table">
        <thead>
            <tr>
                <th>代碼</th>
                <th>價格</th>
                <th>漲幅%</th>
                <th>成交量</th>
            </tr>
        </thead>
        <tbody id="data-body"></tbody>
    </table>

    <script>
        async function refresh() {
            try {
                [cite_start]// 加入時間戳記避免緩存 [cite: 1]
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                
                document.getElementById('stat-text').innerText = '✅ 正常運作';
                document.getElementById('last-update').innerText = data.last_update;
                document.getElementById('scan-count').innerText = data.scan_count;

                let html = '';
                data.stocks.forEach(s => {
                    html += `<tr>
                        <td>${s.Code}</td>
                        <td>${s.Price}</td>
                        <td class="highlight">${s.Change}</td>
                        <td>${s.Volume}</td>
                    </tr>`;
                });
                document.getElementById('data-body').innerHTML = html;
            } catch(e) {
                document.getElementById('stat-text').innerText = '❌ 連線中斷';
            }
        }
        setInterval(refresh, 2000); // 前端每 2 秒刷新畫面
    </script>
</body>
</html>
"""

# --- [ 2. 極簡掃描引擎 ] ---
def simple_scanner():
    global MASTER_BRAIN
    count = 0
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            # [cite_start]只讀取這一個數據源 [cite: 1]
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=8)
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                table = soup.find('table')
                if table:
                    temp_stocks = []
                    # [cite_start]只取前 10 名最簡單的 [cite: 1]
                    for tr in table.find_all('tr')[1:11]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        temp_stocks.append({
                            "Code": tds[1].text.strip(),
                            "Price": tds[4].text.strip(),
                            "Change": tds[3].text.strip(),
                            "Volume": tds[5].text.strip()
                        })
                    
                    count += 1
                    # 直接覆蓋大腦數據
                    MASTER_BRAIN = {
                        "stocks": temp_stocks,
                        "last_update": current_time,
                        "scan_count": count
                    }
                    print(f"✅ 第 {count} 次掃描完成 - {current_time}")
            
            # 設定 5 秒循環測試
            time.sleep(5)
            
        except Exception as e:
            print(f"❌ 錯誤: {e}")
            time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    # [cite_start]啟動線程 [cite: 1]
    threading.Thread(target=simple_scanner, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
