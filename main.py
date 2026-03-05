import os, time, threading, requests, random, warnings, yfinance as yf
from datetime import datetime, timedelta
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__)
CORS(app) [cite: 1, 2]

# ★ 核心數據中樞：對齊 Ross 7 區塊邏輯
MASTER_BRAIN = {
    "top_gainers": [],    # 1. 漲幅排行 (Blue)
    "running_up": [],     # 2. 即時拉升 (Green)
    "small_cap_hod": [],  # 3. 小盤股新高 (Gold)
    "low_float": [],      # 5. 低流通漲幅榜 (Purple)
    "pillars_scan": [],   # 6. 策略掃描 (Dark/Gold)
    "pillars_alert": [],  # 7. 核心警示 (Red/Purple)
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極 UI 介面 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>Warrior Sniper Pro - 繁體實戰版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: 'Segoe UI', sans-serif; overflow: hidden; } [cite: 3]
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 4px; display: flex; flex-direction: column; overflow: hidden; z-index: 1; } [cite: 4]
        
        /* 配色系統 */
        .title-bar { color: white; padding: 6px 12px; font-size: 12px; font-weight: bold; display: flex; justify-content: space-between; border-bottom: 1px solid #30363d; } [cite: 5, 6]
        .bg-blue { background: #0052cc; }    /* 漲幅榜 */ [cite: 7]
        .bg-green { background: #0e632b; }   /* 動能 */ [cite: 8]
        .bg-gold { background: #966900; }    /* 掃描器 */ [cite: 9]
        .bg-purple { background: #6f42c1; }  /* 妖股 */ [cite: 11]
        .bg-red { background: #a50e0e; }     /* 警示 */ [cite: 10]
        .bg-dark { background: #161b22; }    /* 報價 */ [cite: 12]
        
        .content { flex: 1; padding: 2px; overflow-y: auto; font-size: 11px; } [cite: 13]
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 4px 0; cursor: pointer; } [cite: 16]
        .grid-th { font-weight: bold; color: #8b949e; background: #0d1117; position: sticky; top: 0; } [cite: 19]
        
        /* RVOL 量階條 */
        .rvol-bar-container { width: 100%; background: #21262d; height: 14px; border-radius: 2px; position: relative; overflow: hidden; }
        .rvol-bar { height: 100%; background: #f2cc60; transition: width 0.3s; }
        .rvol-text { position: absolute; width: 100%; text-align: center; font-size: 9px; color: #fff; font-weight: bold; top: 0; }

        .text-green { color: #3fb950; font-weight: bold; } [cite: 20]
        .text-red { color: #ff7b72; font-weight: bold; }
        .text-gold { color: #f2cc60; font-weight: bold; } [cite: 22]
        .row-news-today { background-color: rgba(111, 66, 193, 0.15); border-left: 3px solid #6f42c1; } [cite: 34]
        
        @keyframes flash { 0% { background: rgba(255, 255, 255, 0.3); } 100% { background: transparent; } }
        .flash { animation: flash 1s ease-out; } 
    </style>
</head>
<body>
    <div class="window" id="win-1" style="top:10px; left:10px; width:380px; height:280px;"><div class="title-bar bg-blue">1. 漲幅排行 (Top Gainers)</div><div class="content" id="list-1"></div></div>
    <div class="window" id="win-2" style="top:300px; left:10px; width:380px; height:280px;"><div class="title-bar bg-green">2. 即時拉升 (Running Up)</div><div class="content" id="list-2"></div></div>
    <div class="window" id="win-5" style="top:590px; left:10px; width:380px; height:280px;"><div class="title-bar bg-purple">5. 低流通漲幅榜 (Low Float)</div><div class="content" id="list-5"></div></div>

    <div class="window" id="win-3" style="top:10px; left:400px; width:450px; height:430px;"><div class="title-bar bg-gold">3. 小盤股新高 (Small Cap HOD)</div><div class="content" id="list-3"></div></div>
    <div class="window" id="win-6" style="top:450px; left:400px; width:450px; height:420px;"><div class="title-bar bg-gold">6. 策略掃描 (5 Pillars Scan)</div><div class="content" id="list-6"></div></div>

    <div class="window" id="win-7" style="top:10px; left:860px; width:400px; height:280px;"><div class="title-bar bg-red">7. 核心警示 (Pillars Alert)</div><div class="content" id="list-7"></div></div>
    <div class="window" id="win-4" style="top:300px; left:860px; width:400px; height:570px;"><div class="title-bar bg-dark">4. 個股報價與新聞 (Stock Quote)</div><div class="content" id="list-4"></div></div>

    <script>
        function buildRvolBar(val) {
            let num = parseFloat(val.replace('x',''));
            let width = Math.min(100, num * 10);
            return `<div class="rvol-bar-container"><div class="rvol-bar" style="width:${width}%"></div><div class="rvol-text">${val}</div></div>`;
        } [cite: 16, 76]

        function buildTable(data, cols, colTemplate, isAlert=false) {
            let html = `<div class="grid-row grid-th" style="grid-template-columns: ${colTemplate};">`; [cite: 73]
            cols.forEach(c => html += `<div>${c}</div>`);
            html += '</div>';

            data.forEach(item => {
                let rowClass = "grid-row" + (isAlert ? " flash" : "");
                html += `<div class="${rowClass}" style="grid-template-columns: ${colTemplate};" onclick="loadDetail('${item.Code}')">`; [cite: 74]
                cols.forEach(c => {
                    if(c === '代碼') html += `<div class="text-green">${item.Code}</div>`; [cite: 75]
                    else if(c === '漲幅%') html += `<div class="text-green">${item.Change}</div>`;
                    else if(c === '量比') html += `<div>${buildRvolBar(item.RVOL)}</div>`;
                    else if(c === '浮動股') html += `<div class="text-gold">${item.FloatStr}</div>`; [cite: 76, 77]
                    else html += `<div>${item[c] || item.Price}</div>`;
                });
                html += '</div>';
            });
            return html;
        }

        async function refresh() {
            const res = await fetch('/data');
            const data = await res.json(); [cite: 79, 80]
            
            document.getElementById('list-1').innerHTML = buildTable(data.top_gainers, ['代碼','價格','漲幅%','成交量','浮動股'], '0.6fr 0.8fr 0.8fr 1fr 0.8fr'); [cite: 81]
            document.getElementById('list-2').innerHTML = buildTable(data.running_up, ['代碼','價格','漲幅%','量比'], '0.6fr 0.8fr 0.8fr 1.2fr'); [cite: 84]
            document.getElementById('list-3').innerHTML = buildTable(data.small_cap_hod, ['代碼','價格','量比','成交量','浮動股'], '0.6fr 0.8fr 1.2fr 1fr 0.8fr'); [cite: 82]
            document.getElementById('list-5').innerHTML = buildTable(data.low_float, ['代碼','價格','浮動股','漲幅%'], '0.6fr 0.8fr 0.8fr 0.8fr'); [cite: 83]
            document.getElementById('list-7').innerHTML = buildTable(data.halts, ['時間','代碼','價格','漲幅%'], '0.8fr 0.6fr 0.8fr 0.8fr', true); [cite: 88]
        }
        setInterval(refresh, 2000); [cite: 97]
    </script>
</body>
</html>
"""

# --- [ 2. 量化與掃描邏輯 ] ---
def format_vol_km(v_float):
    """將成交量格式化為 K/M/B，符合專業交易顯示 [cite: 103]"""
    if v_float >= 1_000_000_000: return f"{v_float/1_000_000_000:.2f}B"
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.2f}M"
    return f"{v_float/1_000:.1f}K" if v_float >= 1_000 else str(int(v_float))

def scanner_engine():
    global MASTER_BRAIN
    tz_tw = pytz.timezone('Asia/Taipei')
    while True:
        try:
            # 模擬從 StockAnalysis 或真實 API 獲取數據 [cite: 104, 105]
            url = "https://stockanalysis.com/markets/gainers/"
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                rows = soup.find('table').find_all('tr')[1:30]
                
                t_all = []
                for tr in rows:
                    tds = tr.find_all('td')
                    sym = tds[1].text.strip()
                    price = float(tds[4].text.replace('$','').replace(',',''))
                    
                    f, a, prev = get_static(sym) [cite: 101, 102]
                    vol_raw = float(tds[5].text.replace(',',''))
                    rvol = vol_raw / a if a > 0 else 1.0
                    
                    item = {
                        "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                        "Code": sym, "Price": f"${price:.2f}",
                        "Change": tds[3].text.strip(),
                        "成交量": format_vol_km(vol_raw),
                        "RVOL": f"{rvol:.1f}x",
                        "FloatStr": f"{f/1e6:.1f}M",
                        "f_num": f, "r_num": rvol, "c_num": float(tds[3].text.replace('%',''))
                    }
                    t_all.append(item)

                # 分流至 7 大區塊 [cite: 128, 129, 130]
                MASTER_BRAIN["top_gainers"] = sorted(t_all, key=lambda x: x["c_num"], reverse=True)[:15]
                MASTER_BRAIN["low_float"] = [x for x in t_all if x["f_num"] < 20_000_000][:10]
                MASTER_BRAIN["small_cap_hod"] = [x for x in t_all if 1.0 < float(x["Price"][1:]) < 20.0 and x["r_num"] > 2.0]
                MASTER_BRAIN["halts"] = [x for x in t_all if x["c_num"] > 20.0 and x["r_num"] > 5.0]

            time.sleep(5) [cite: 131]
        except: time.sleep(10)

def get_static(ticker):
    """獲取流通股本與平均成交量 [cite: 101]"""
    try:
        if ticker in stock_cache: return stock_cache[ticker]
        info = yf.Ticker(ticker).info
        f = info.get('floatShares', 50_000_000)
        a = info.get('averageVolume', 1_000_000)
        p = info.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 20_000_000, 1_000_000, 1.0

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN) [cite: 80]
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)
