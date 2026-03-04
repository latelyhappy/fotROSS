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
# 五大區塊數據容器
MASTER_BRAIN = {"sniper": [], "drop": [], "stocks": [], "live": [], "details": {}}
stock_info_cache = {}
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極戰情室 UI：五大區塊獨立排版 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V164.7 - 五大戰略區塊</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 8px 12px; font-size: 12px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .resize-handle { width: 10px; height: 10px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-sniper { background: rgba(63, 185, 80, 0.18) !important; border-left: 3px solid #3fb950; }
        .row-drop { background: rgba(255, 51, 102, 0.22) !important; border-left: 3px solid #ff3366; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        #sys-status { position: fixed; bottom: 10px; right: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 狙擊手 (進場訊號)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    
    <div class="window" id="win-live" style="top:10px; left:500px; width:480px; height:320px;"><div class="title-bar">📡 即時報警 (Live)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    
    <div class="window" id="win-drop" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 下跌警報 (Ross/拋售)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    
    <div class="window" id="win-ranking" style="top:340px; left:500px; width:480px; height:620px;"><div class="title-bar">🏆 排行 (1-30 USD 全掃描)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    
    <div class="window" id="win-details" style="top:670px; left:10px; width:480px; height:290px;"><div class="title-bar">📊 數據與戰情</div><div class="content" id="detail-list">點擊代碼查看詳情...</div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 掃描引擎同步中...</div>

    <script>
        async function refresh() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ V164.7 | ' + new Date().toLocaleTimeString();
                
                // 渲染狙擊手區塊
                let sniperH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    sniperH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = sniperH;

                // 渲染即時報警區塊
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>動態</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;" onclick="loadDetail('${l.Code}')">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div>${l.Type}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 渲染下跌警報區塊
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>回落%</div><div>警報</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row row-drop" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${d.Code}')">
                        <div class="text-blue">${d.Code}</div><div>${d.Price}</div><div class="text-red">${d.Drop}</div><div>${d.Type}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 渲染排行區塊 (所有欄位)
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1fr;"><div>代碼</div><div>價格</div><div>漲幅%</div><div>漲幅$</div><div>浮動股</div></div>';
                data.stocks.forEach(s => {
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue" style="font-weight:bold;">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div>
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
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
                    <div style="background:#161b22; padding:10px; border-radius:4px;">今日最高: <b>${d.HOD}</b></div>
                    <div style="background:#161b22; padding:10px; border-radius:4px;">換手率: <b style="color:#f2cc60;">${d.Turnover}</b></div>
                    <div style="background:#161b22; padding:10px; border-radius:4px;">跳空幅度: <b style="color:#3fb950;">${d.Gap}</b></div>
                    <div style="background:#161b22; padding:10px; border-radius:4px;">量比 (RVOL): <b>${d.RVOL}</b></div>
                </div>`;
        }

        // 視窗交互邏輯
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

# --- [ 2. 核心運算引擎 ] ---
def format_vol(v):
    if v <= 0: return "N/A"
    if v >= 1e6: return f"{v/1e6:.1f}M"
    return f"{v/1e3:.0f}K" if v >= 1e3 else str(int(v))

def fetch_data(ticker):
    try:
        t = yf.Ticker(ticker); info = t.info
        return info.get('floatShares', 0) or info.get('sharesOutstanding', 1), info.get('averageVolume', 1), info.get('previousClose', 0)
    except: return 0, 1, 0

# --- [ 3. 狙擊掃描：10秒隨機頻率 ] ---
def scanner_job():
    global MASTER_BRAIN
    while True:
        try:
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            if table:
                temp_stocks, sniper, drop, live = [], [], [], []
                for tr in table.find_all('tr')[1:35]:
                    tds = tr.find_all('td')
                    if len(tds) < 5: continue
                    sym = tds[1].text.strip()
                    p_num = float(tds[4].text.replace('$','').replace(',',''))
                    
                    if 1.0 <= p_num <= 30.0:
                        f, a, prev = stock_info_cache.get(sym, fetch_data(sym))
                        stock_info_cache[sym] = (f, a, prev)
                        cell = MASTER_BRAIN["details"].get(sym, {"HOD": 0})
                        vol_n = float(tds[5].text.replace('K','000').replace('M','000000').replace(',','').replace('.','')) # 簡化
                        
                        if p_num > cell["HOD"]: cell["HOD"] = p_num
                        gap = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol = vol_n / a if a > 0 else 1.0
                        drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0

                        item = {
                            "Time": datetime.now().strftime('%H:%M:%S'), "Code": sym, "Price": f"${p_num:.2f}",
                            "Change": tds[3].text, "ChangeAmt": f"${(p_num-prev):.2f}", "RVOL": f"{rvol:.1f}x",
                            "Gap": f"{gap:.1f}%", "Turnover": f"{(vol_n/f*100):.1f}%" if f > 0 else "0%",
                            "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}", "FloatStr": format_vol(f), "Type": "🆕NEW"
                        }

                        # 區塊 2: 狙擊手判定
                        if gap > 3.0 and rvol > 5.0:
                            item["Type"] = "🚀 第一根狙擊"
                            sniper.append(item)
                        
                        # 區塊 5: 下跌警報
                        if drop_p < -2.0:
                            item["Type"] = "🔴 Ross 下跌"
                            drop.append(item)
                        
                        # 區塊 4: 即時報警
                        if p_num >= cell["HOD"]:
                            item["Type"] = "🔥 HOD 突破"
                            live.append(item)
                        else: live.append(item)

                        temp_stocks.append(item)
                        MASTER_BRAIN["details"][sym] = item
                
                MASTER_BRAIN["stocks"] = temp_stocks
                MASTER_BRAIN["sniper"] = sniper[:10]
                MASTER_BRAIN["drop"] = drop[:10]
                MASTER_BRAIN["live"] = live[:15]
            
            # ★ 頻率控制：10秒 ±3秒
            time.sleep(random.uniform(7.0, 13.0))
        except: time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
