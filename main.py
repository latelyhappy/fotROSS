import os, json, time, threading, requests, yfinance as yf, logging, re, warnings, random
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# --- [ 系統核心配置 ] ---
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

app = Flask(__name__); CORS(app)

# ★ 數據中樞
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], "live": [], 
    "details": {}, "last_update": "初始化中..."
}
# 靜態數據快取 (避免卡死迴圈)
stock_cache = {} 
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 介面：確保視窗可動、數據會跳 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V165.2 - 終極穩定版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; position: relative; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-sniper { background: rgba(63, 185, 80, 0.2) !important; border-left: 3px solid #3fb950; }
        .row-drop { background: rgba(255, 51, 102, 0.25) !important; border-left: 3px solid #ff3366; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 狙擊手 (Gap > 3% + RVOL > 5x)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-live" style="top:10px; left:500px; width:480px; height:320px;"><div class="title-bar">📡 即時報警 (滾動歷史)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-drop" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-rank" style="top:340px; left:500px; width:480px; height:600px;"><div class="title-bar">🏆 排行掃描 (全欄位)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    <div id="sys-status">🔄 掃描引擎監測中...</div>

    <script>
        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 後端最後更新: ' + data.last_update + ' | 本地: ' + new Date().toLocaleTimeString();

                // 2. 狙擊手
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    snipH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;

                // 4. 即時報警 (保留最後 20 筆歷史)
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>動向</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div>${l.Type}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 5. 下跌警報
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;"><div>代碼</div><div>價格</div><div>回落%</div><div>訊號</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row row-drop" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;">
                        <div class="text-blue">${d.Code}</div><div>${d.Price}</div><div class="text-red">${d.Drop}</div><div>${d.Type}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 3. 排行榜
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;"><div>代碼</div><div>漲幅%</div><div>漲幅$</div><div>浮動股</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;">
                        <div class="text-blue">${s.Code}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div><div>${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('rank-list').innerHTML = rankH;
            } catch(e) {}
        }

        // 視窗拖拽縮放
        document.querySelectorAll('.window').forEach(win => {
            const title = win.querySelector('.title-bar');
            const handle = win.querySelector('.resize-handle');
            title.onmousedown = (e) => {
                let p1 = 0, p2 = 0, p3 = e.clientX, p4 = e.clientY;
                document.onmousemove = (e) => {
                    p1 = p3 - e.clientX; p2 = p4 - e.clientY; p3 = e.clientX; p4 = e.clientY;
                    win.style.top = (win.offsetTop - p2) + "px"; win.style.left = (win.offsetLeft - p1) + "px";
                };
                document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; };
            };
            handle.onmousedown = (e) => {
                let startW = win.offsetWidth, startH = win.offsetHeight, startX = e.clientX, startY = e.clientY;
                document.onmousemove = (e) => {
                    win.style.width = (startW + e.clientX - startX) + 'px';
                    win.style.height = (startH + e.clientY - startY) + 'px';
                };
                document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; };
            };
        });
        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心數據函數：強化穩定性 ] ---
def get_static(ticker):
    # 檢查快取，如果沒有就返回預設值，避免卡死掃描
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        # 非同步抓取靜態數據的邏輯需在背景執行，這裡先給個大概值
        t = yf.Ticker(ticker)
        f = t.info.get('floatShares', 1000000)
        a = t.info.get('averageVolume', 500000)
        p = t.info.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

# --- [ 3. 掃描引擎：絕對不卡死邏輯 ] ---
def scanner_loop():
    global MASTER_BRAIN
    print("🔥 引擎啟動：進入 3-5 秒高頻掃描循環...")
    live_history = [] # 儲存即時報警的歷史

    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            # 1. 抓取強勢榜
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=5)
            if r.status_code != 200: 
                print(f"❌ 網路請求失敗: {r.status_code}")
                time.sleep(5); continue

            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            if not table: 
                print("❌ 找不到數據表格"); time.sleep(5); continue

            temp_stocks, temp_snip, temp_drop = [], [], []
            for tr in table.find_all('tr')[1:25]:
                tds = tr.find_all('td')
                if len(tds) < 5: continue
                sym = tds[1].text.strip()
                p_num = float(tds[4].text.replace('$','').replace(',',''))
                
                if 1.0 <= p_num <= 30.0:
                    # 使用快取數據，不在此處執行耗時的 yf.info
                    f, a, prev = stock_cache.get(sym, (1000000, 500000, p_num))
                    vol_raw = float(tds[5].text.replace('K','000').replace('M','000000').replace(',',''))
                    
                    cell = MASTER_BRAIN["details"].get(sym, {"HOD": p_num})
                    if p_num > cell["HOD"]: cell["HOD"] = p_num
                    
                    gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                    rvol = vol_raw / a if a > 0 else 1.0
                    drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0

                    item = {
                        "Time": current_time, "Code": sym, "Price": f"${p_num:.2f}",
                        "Change": tds[3].text, "ChangeAmt": f"${(p_num-prev):.2f}", "RVOL": f"{rvol:.1f}x",
                        "Gap": f"{gap_p:.1f}%", "Turnover": f"{(vol_raw/f*100):.1f}%",
                        "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}", 
                        "FloatStr": f"{f/1e6:.1f}M", "Type": "🆕 掃描"
                    }

                    # 分選邏輯
                    if gap_p > 3.0 and rvol > 5.0: 
                        item["Type"] = "🚀 第一根狙擊"; temp_snip.append(item)
                    if drop_p < -2.0: 
                        item["Type"] = "🔴 Ross 下跌"; temp_drop.append(item)
                    if p_num >= cell["HOD"]: 
                        item["Type"] = "🔥 HOD 突破"
                    
                    # 更新即時報警歷史 (只存有動作的)
                    if "掃描" not in item["Type"]:
                        live_history.insert(0, item)
                    
                    temp_stocks.append(item)
                    MASTER_BRAIN["details"][sym] = cell

            # 保持歷史紀錄在 20 筆
            live_history = live_history[:20]

            # 4. 更新大腦
            MASTER_BRAIN.update({
                "stocks": temp_stocks, "sniper": temp_snip, 
                "drop": temp_drop, "live": live_history,
                "last_update": current_time
            })
            print(f"✅ 掃描完成: {current_time} | 狙擊: {len(temp_snip)} | 下跌: {len(temp_drop)}")
            
            time.sleep(random.uniform(3.0, 5.0))

        except Exception as e:
            print(f"⚠️ 核心發生錯誤: {e}")
            time.sleep(5)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    # 啟動一個獨立線程去預抓靜態數據，不影響掃描
    def pre_fetch():
        tickers = ["GME", "AMC", "SOFI", "PLTR", "MARA", "RIOT"] # 預設幾檔
        for t in tickers: get_static(t)
    threading.Thread(target=pre_fetch, daemon=True).start()
    
    threading.Thread(target=scanner_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
