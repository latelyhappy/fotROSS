import os, time, threading, requests, random, warnings, yfinance as yf
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__); CORS(app)

# ★ 強化版數據中樞
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], "live": [],
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ UI 介面：維持您的五大區塊排版 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V167.0 - 穩定進化版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 狙擊手 (Gap > 3% + RVOL > 5x)</div><div class="content" id="sniper-list"></div></div>
    <div class="window" style="top:10px; left:500px; width:480px; height:320px;"><div class="title-bar">📡 即時報警 (Live)</div><div class="content" id="live-list"></div></div>
    <div class="window" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div></div>
    <div class="window" style="top:340px; left:500px; width:480px; height:640px;"><div class="title-bar">🏆 排行掃描 (1-30 USD)</div><div class="content" id="rank-list"></div></div>
    <div id="sys-status">🔄 等待數據中...</div>

    <script>
        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 更新: ' + data.last_update + ' | 次數: ' + data.scan_count;

                document.getElementById('sniper-list').innerHTML = data.sniper.map(s => `<div class="grid-row"><div>${s.Code}</div><div class="text-green">${s.Change}</div><div>🚀 狙擊</div></div>`).join('');
                document.getElementById('live-list').innerHTML = data.live.map(l => `<div class="grid-row"><div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div></div>`).join('');
                document.getElementById('drop-list').innerHTML = data.drop.map(d => `<div class="grid-row"><div>${d.Code}</div><div class="text-red">${d.Drop}</div></div>`).join('');
                document.getElementById('rank-list').innerHTML = data.stocks.map(s => `<div class="grid-row"><div>${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div></div>`).join('');
            } catch(e) {}
        }
        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 改良後的掃描循環 ] ---
def stable_scanner():
    global MASTER_BRAIN
    count = 0
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            # PHASE 1: 抓取基礎數據 (速度極快)
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
                if table:
                    temp_stocks, temp_snip, temp_drop, temp_live = [], [], [], []
                    for tr in table.find_all('tr')[1:25]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        
                        sym = tds[1].text.strip()
                        p_str = tds[4].text.replace('$','').replace(',','')
                        p_num = float(p_str)
                        chg_str = tds[3].text.strip()
                        
                        # 基礎過濾
                        if 1.0 <= p_num <= 30.0:
                            item = {"Code": sym, "Price": f"${p_num:.2f}", "Change": chg_str, "Time": current_time, "Drop": "0%"}
                            
                            # 判定狙擊與下跌
                            if "+" in chg_str and float(chg_str.replace('%','').replace('+','')) > 5.0:
                                temp_snip.append(item)
                            
                            temp_live.append(item)
                            temp_stocks.append(item)
                    
                    count += 1
                    MASTER_BRAIN.update({
                        "stocks": temp_stocks, "sniper": temp_snip, "drop": temp_drop,
                        "live": temp_live[:20], "last_update": current_time, "scan_count": count
                    })
                    print(f"✅ 第 {count} 次掃描完成 - {current_time}")
            
            time.sleep(random.uniform(7.0, 13.0)) # 遵循 10s 節奏
        except Exception as e:
            print(f"❌ 錯誤: {e}"); time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=stable_scanner, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
