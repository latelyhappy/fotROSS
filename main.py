import os, json, time, threading, requests, yfinance as yf, logging, re, warnings, random
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# --- [ 系統核心配置 ] ---
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

app = Flask(__name__); CORS(app)

# ★ 中央數據大腦
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], "live": [], "details": {},
    "last_update": "N/A"
}
stock_info_cache = {}
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極戰情室 UI：五大區塊邏輯分佈 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V164.7 - 終極戰情系統</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; align-items: center; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .resize-handle { width: 10px; height: 10px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; }
        
        /* 表格樣式 */
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        
        /* 訊號顏色 */
        .row-sniper { background: rgba(63, 185, 80, 0.18) !important; border-left: 3px solid #3fb950; }
        .row-drop { background: rgba(255, 51, 102, 0.22) !important; border-left: 3px solid #ff3366; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 8px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 18px; font-weight: bold; color: #fff; margin-top: 4px; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:450px; height:320px;"><div class="title-bar">🚀 2. 狙擊手 (Gap > 3% + RVOL > 5x)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-live" style="top:10px; left:470px; width:450px; height:320px;"><div class="title-bar">📡 4. 即時報警 (10s 循環)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-drop" style="top:340px; left:10px; width:450px; height:320px;"><div class="title-bar">📉 5. 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-rank" style="top:340px; left:470px; width:450px; height:640px;"><div class="title-bar">🏆 3. 排行 (1-30 USD 全掃描)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-details" style="top:670px; left:10px; width:450px; height:310px;"><div class="title-bar">📊 1. 戰情室詳情</div><div class="content" id="detail-list">點擊個股代碼...</div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 初始化掃描引擎...</div>

    <script>
        async function refreshUI() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 更新時間: ' + data.last_update;

                // 2. 狙擊手區塊
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    snipH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;

                // 4. 即時報警區塊
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>動態</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;" onclick="loadDetail('${l.Code}')">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div>${l.Type}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 5. 下跌警報區塊
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;"><div>代碼</div><div>價格</div><div>回落%</div><div>訊號</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row row-drop" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;" onclick="loadDetail('${d.Code}')">
                        <div class="text-blue">${d.Code}</div><div>${d.Price}</div><div class="text-red">${d.Drop}</div><div>${d.Type}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 3. 排行榜 (全欄位)
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;"><div>代碼</div><div>漲幅%</div><div>漲幅$</div><div>浮動股</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div><div>${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('rank-list').innerHTML = rankH;
            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data');
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;
            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap}</div></div>
                    <div class="p-box">平均量比<div class="p-val">${d.RVOL}</div></div>
                </div>`;
        }

        // 視窗交互與拖拽
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
        setInterval(refreshUI, 2000); // 2秒前端更新
    </script>
</body>
</html>
"""

# --- [ 2. 核心數據處理函數 ] ---
def get_advanced_info(ticker): #
    try:
        t = yf.Ticker(ticker); i = t.info
        return i.get('floatShares', 0) or i.get('sharesOutstanding', 1), i.get('averageVolume', 1), i.get('previousClose', 0)
    except: return 0, 1, 0

def format_km(val): #
    if val >= 1e6: return f"{val/1e6:.1f}M"
    return f"{val/1e3:.0f}K" if val >= 1e3 else str(int(val))

# --- [ 3. 中央掃描引擎：10秒 隨機循環 ] ---
def central_scanner():
    global MASTER_BRAIN
    while True:
        try:
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            if table:
                temp_rank, temp_snip, temp_drop, temp_live = [], [], [], []
                for tr in table.find_all('tr')[1:35]:
                    tds = tr.find_all('td')
                    if len(tds) < 5: continue
                    sym = tds[1].text.strip()
                    p_num = float(tds[4].text.replace('$','').replace(',',''))
                    
                    if 1.0 <= p_num <= 30.0:
                        f, a, prev = stock_info_cache.get(sym, get_advanced_info(sym))
                        stock_info_cache[sym] = (f, a, prev)
                        cell = MASTER_BRAIN["details"].get(sym, {"HOD": 0})
                        vol_raw = float(tds[5].text.replace('K','000').replace('M','000000').replace(',','')) # 
                        
                        if p_num > cell["HOD"]: cell["HOD"] = p_num
                        gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol_v = vol_raw / a if a > 0 else 1.0
                        drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0

                        item = {
                            "Time": datetime.now().strftime('%H:%M:%S'), "Code": sym, "Price": f"${p_num:.2f}",
                            "Change": tds[3].text, "ChangeAmt": f"${(p_num-prev):.2f}", "RVOL": f"{rvol_v:.1f}x",
                            "Gap": f"{gap_p:.1f}%", "Turnover": f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%",
                            "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}", "FloatStr": format_km(f), "Type": "🆕NEW"
                        }

                        # 分流：區塊 2 (狙擊)
                        if gap_p > 3.0 and rvol_v > 5.0:
                            item["Type"] = "🚀 第一根狙擊"
                            temp_snip.append(item)
                        
                        # 分流：區塊 5 (下跌)
                        if drop_p < -2.0:
                            item["Type"] = "🔴 Ross 下跌"
                            temp_drop.append(item)
                        
                        # 分流：區塊 4 (即時)
                        if p_num >= cell["HOD"]: item["Type"] = "🔥 HOD 突破"
                        temp_live.append(item)

                        temp_rank.append(item)
                        MASTER_BRAIN["details"][sym] = item
                
                MASTER_BRAIN["stocks"] = temp_rank
                MASTER_BRAIN["sniper"] = temp_snip
                MASTER_BRAIN["drop"] = temp_drop
                MASTER_BRAIN["live"] = temp_live
                MASTER_BRAIN["last_update"] = datetime.now().strftime('%H:%M:%S')

            time.sleep(random.uniform(7.0, 13.0)) # ★ 10s ±3s 循環
        except: time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=central_scanner, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
