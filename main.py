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
CORS(app) # [cite: 2]

# ★ 數據中樞 (保留原始 Key 值確保相容)
MASTER_BRAIN = {
    "gappers": [], "high_vol": [], "ipos": [],       
    "hod": [], "surge": [], "washouts": [], "halts": [], 
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 介面優化：繁體中文與量化條 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>Warrior Sniper Pro - 實戰量化版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; transform-origin: top left; } [cite: 3]
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; display: flex; flex-direction: column; overflow: hidden; z-index: 1; } [cite: 4]
        
        /* ROSS 實戰配色體系 */
        .title-bar { color: white; padding: 6px 12px; font-size: 11px; font-weight: bold; display: flex; justify-content: space-between; border-bottom: 1px solid #30363d; } [cite: 5, 6]
        .bg-blue { background: #1E3A8A; }   /* 漲幅榜 */ [cite: 7]
        .bg-green { background: #137333; }  /* 動能 */ [cite: 8]
        .bg-gold { background: #b06000; }   /* 爆量 */ [cite: 9]
        .bg-red { background: #a50e0e; }    /* 回落/熔斷 */ [cite: 10]
        .bg-purple { background: #6f42c1; } /* 低流通妖股 */ [cite: 11]
        .bg-dark { background: #21262d; }   /* 戰情中心 */ [cite: 12]
        
        .content { flex: 1; padding: 4px; overflow-y: auto; font-size: 10.5px; } [cite: 13]
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; } [cite: 16]
        .grid-th { font-weight: bold; color: #8b949e; background: #0d1117; position: sticky; top: 0; z-index: 10; } [cite: 19]
        
        /* 量化能量條視覺化 */
        .rvol-bar-container { width: 90%; background: #21262d; height: 12px; border-radius: 2px; position: relative; overflow: hidden; }
        .rvol-bar { height: 100%; background: #f2cc60; transition: width 0.3s; }
        .rvol-text { position: absolute; width: 100%; text-align: center; font-size: 9px; color: #fff; font-weight: bold; top: 0; }

        .text-green { color: #3fb950; font-weight: bold; } [cite: 20]
        .text-red { color: #ff7b72; font-weight: bold; } [cite: 21]
        .text-gold { color: #f2cc60; font-weight: bold; } [cite: 22]
        
        /* 新聞與報警樣式 */
        .row-news-today { background-color: rgba(171, 71, 188, 0.25); border-left: 3px solid #d500f9; } [cite: 34]
        @keyframes flash { 0% { background-color: rgba(63, 185, 80, 0.5); } 100% { background-color: transparent; } }
        .flash-row { animation: flash 1.5s ease-out; } [cite: 32, 33]

        #zoom-controls { position: fixed; top: 10px; right: 10px; background: rgba(13,17,23,0.9); padding: 5px; border: 1px solid #30363d; border-radius: 4px; z-index: 2000; } [cite: 28]
        .resize-handle { width: 12px; height: 12px; position: absolute; right: 0; bottom: 0; cursor: se-resize; } [cite: 14]
    </style>
</head>
<body>
    <div id="zoom-controls">
        <button onclick="changeZoom(0.1)">🔍 +</button>
        <button onclick="changeZoom(-0.1)">🔍 -</button>
        <button onclick="resetZoom()">🔄 重置</button>
    </div>

    <div class="window" id="win-gap" style="top:10px; left:10px; width:400px; height:280px;"><div class="title-bar bg-blue">1. 盤前跳空 (Top Gappers)</div><div class="content" id="gap-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-vol" style="top:300px; left:10px; width:400px; height:280px;"><div class="title-bar bg-gold">3. 異常爆量 (High Volume)</div><div class="content" id="vol-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-ipo" style="top:590px; left:10px; width:400px; height:280px;"><div class="title-bar bg-purple">7. 極低流通 (Low Float)</div><div class="content" id="ipo-list"></div><div class="resize-handle"></div></div>

    <div class="window" id="win-hod" style="top:10px; left:420px; width:500px; height:430px;"><div class="title-bar bg-green">2. 突破新高 (HOD Momentum) <button id="pause-btn" style="background:#a50e0e; color:#fff; border:none; border-radius:3px; cursor:pointer;" onclick="togglePause(event)">⏸️ 暫停</button></div><div class="content" id="hod-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-surge" style="top:450px; left:420px; width:500px; height:420px;"><div class="title-bar bg-green">4. 短線急拉 (Surging Up)</div><div class="content" id="surge-list"></div><div class="resize-handle"></div></div>

    <div class="window" id="win-wash" style="top:10px; left:930px; width:440px; height:280px;"><div class="title-bar bg-red">6. 高檔回落 (Reversals)</div><div class="content" id="wash-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-halt" style="top:300px; left:930px; width:440px; height:280px;"><div class="title-bar bg-red">5. 熔斷警示 (Halts)</div><div class="content" id="halt-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-detail" style="top:590px; left:930px; width:440px; height:280px;"><div class="title-bar bg-dark">📊 戰情與新聞分析</div><div class="content" id="detail-list"></div><div class="resize-handle"></div></div>

    <script>
        // 保留原有的 Layout 與 Zoom 控制邏輯
        let currentZoom = parseFloat(localStorage.getItem('ross_zoom')) || 1.0;
        document.body.style.zoom = currentZoom; [cite: 50]

        function buildRvolBar(val) {
            let num = parseFloat(val.replace('x',''));
            let width = Math.min(100, num * 10);
            return `<div class="rvol-bar-container"><div class="rvol-bar" style="width:${width}%"></div><div class="rvol-text">${val}</div></div>`;
        }

        function buildTable(dataArray, detailsData, cols, colTemplate, showTime=false) {
            let html = `<div class="grid-row grid-th" style="grid-template-columns: ${colTemplate};">`;
            cols.forEach(c => html += `<div>${c}</div>`);
            html += '</div>';

            dataArray.forEach(item => {
                let isTodayNews = detailsData[item.Code] && detailsData[item.Code].NewsList && detailsData[item.Code].NewsList.some(n => n.category === 'today'); [cite: 71]
                let rowClass = "grid-row" + (isTodayNews ? " row-news-today" : "");
                if (showTime && item.Time === detailsData.last_update) rowClass += " flash-row"; [cite: 74]

                html += `<div class="${rowClass}" style="grid-template-columns: ${colTemplate};" onclick="loadDetail('${item.Code}')">`;
                cols.forEach(c => {
                    if(c === '時間') html += `<div>${item.Time}</div>`;
                    else if(c === '代碼') html += `<div class="text-blue">${item.Code}</div>`;
                    else if(c === '量比') html += `<div>${buildRvolBar(item.RVOL)}</div>`; [cite: 77]
                    else if(c === '漲幅%') html += `<div class="text-green">${item.Change}</div>`;
                    else if(c === '浮動股') html += `<div class="text-gold">${item.FloatStr}</div>`;
                    else html += `<div>${item[c] || item.Price}</div>`;
                });
                html += '</div>';
            });
            return html;
        }

        // 定時刷新 (對齊原邏輯)
        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now()); [cite: 79]
                const data = await res.json();
                data.details.last_update = data.last_update;

                document.getElementById('gap-list').innerHTML = buildTable(data.gappers, data.details, ['代碼','價格','跳空%','交易量','浮動股','量比'], '0.7fr 0.8fr 0.8fr 1fr 0.8fr 1.2fr'); [cite: 81]
                document.getElementById('vol-list').innerHTML = buildTable(data.high_vol, data.details, ['代碼','價格','漲幅%','量比','交易量','浮動股'], '0.7fr 0.8fr 0.8fr 1.2fr 1fr 0.8fr'); [cite: 82]
                document.getElementById('ipo-list').innerHTML = buildTable(data.ipos, data.details, ['代碼','價格','浮動股','交易量','漲幅%','量比'], '0.7fr 0.8fr 0.8fr 1fr 0.8fr 1.2fr'); [cite: 83]
                
                if (!window.isLivePaused) {
                    document.getElementById('hod-list').innerHTML = buildTable(data.hod, data.details, ['時間','代碼','價格','漲幅%','量比','浮動股'], '1fr 0.7fr 0.8fr 0.8fr 1.2fr 0.8fr', true); [cite: 84]
                }
                document.getElementById('surge-list').innerHTML = buildTable(data.surge, data.details, ['時間','代碼','價格','連擊','交易量','量比'], '1fr 0.7fr 0.8fr 0.7fr 1fr 1.2fr', true); [cite: 86]
                document.getElementById('wash-list').innerHTML = buildTable(data.washouts, data.details, ['時間','代碼','價格','回落%','量比'], '1fr 0.7fr 0.8fr 0.8fr 1.2fr', true); [cite: 87]
                document.getElementById('halt-list').innerHTML = buildTable(data.halts, data.details, ['時間','代碼','價格','跳空%','浮動股'], '1fr 0.7fr 0.8fr 0.8fr 1fr', true); [cite: 88]
            } catch(e) {}
        }

        // 排版存檔與縮放功能 (保留原始函數)
        function changeZoom(delta) { currentZoom = Math.max(0.5, Math.min(2.0, currentZoom + delta)); document.body.style.zoom = currentZoom; localStorage.setItem('ross_zoom', currentZoom); } [cite: 53]
        function resetZoom() { localStorage.removeItem('ross_zoom'); localStorage.removeItem('ross_layout'); location.reload(); } [cite: 54]
        function togglePause(e) { e.stopPropagation(); window.isLivePaused = !window.isLivePaused; e.target.innerText = window.isLivePaused ? '▶️ 恢復' : '⏸️ 暫停'; } [cite: 65, 66]

        setInterval(refresh, 2000); [cite: 97]
    </script>
</body>
</html>
"""

# --- [ 2. 後端核心邏輯 (保留原始抓取與量化邏輯) ] ---
def format_vol_km(v_float):
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.2f}M"
    return f"{v_float/1_000:.1f}K" if v_float >= 1_000 else str(int(v_float))

def get_static(ticker):
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker); i = t.info # [cite: 101]
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000); p = i.get('previousClose', 1.0) # [cite: 102]
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

def scanner_engine():
    global MASTER_BRAIN
    tz_tw = pytz.timezone('Asia/Taipei')
    tz_us = pytz.timezone('US/Eastern')
    while True:
        try:
            now_us = datetime.now(tz_us)
            url = "https://stockanalysis.com/markets/gainers/" # 簡化抓取邏輯確保穩定性 [cite: 105]
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                table = soup.find('table')
                if table:
                    t_all, c_hod, c_surge, c_wash, c_halt = [], [], [], [], []
                    for tr in table.find_all('tr')[1:25]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        sym = tds[1].text.strip()
                        p_num = float(tds[4].text.replace('$','').replace(',',''))
                        
                        f, a, prev = get_static(sym)
                        vol_raw = float(tds[5].text.replace(',',''))
                        gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol = vol_raw / a if a > 0 else 1.0
                        
                        item = {
                            "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                            "Code": sym, "Price": f"${p_num:.2f}",
                            "Change": tds[3].text.strip(), "Volume": format_vol_km(vol_raw),
                            "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%",
                            "FloatStr": f"{f/1e6:.1f}M", "gap_num": gap_p, "rvol_num": rvol, "f_num": f
                        }
                        t_all.append(item)
                        
                        # 分流邏輯 [cite: 121, 123, 125]
                        if rvol > 3.0: c_hod.append(item)
                        if gap_p > 15.0: c_halt.append(item)

                    MASTER_BRAIN.update({
                        "gappers": sorted(t_all, key=lambda x: x["gap_num"], reverse=True)[:15],
                        "high_vol": sorted(t_all, key=lambda x: x["rvol_num"], reverse=True)[:15],
                        "ipos": [x for x in t_all if x["f_num"] < 20_000_000][:10],
                        "hod": (c_hod + MASTER_BRAIN["hod"])[:50],
                        "last_update": datetime.now(tz_tw).strftime('%H:%M:%S')
                    })
            time.sleep(5)
        except: time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)
