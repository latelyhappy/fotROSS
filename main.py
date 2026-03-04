import os, json, time, threading, requests, yfinance as yf, logging, re, warnings
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

# ★ 初始預熱數據：確保啟動時畫面不空白
MASTER_BRAIN = {
    "alerts": [
        {"Time": "00:00:00", "Code": "SYSTEM", "Price": "$0.00", "RVOL": "1.0x", "Turnover": "0%", "Gap": "0%", "Type": "🔄 系統初始化中..."}
    ],
    "stocks": [],
    "raw_top20": [],
    "details": {}
}
stock_info_cache = {}
translator = GoogleTranslator(source='auto', target='zh-TW')

STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 豪華版 UI 介面 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V8.5 - 終極雲端系統</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow-x: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: grab; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 12px; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 8px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-ross { background: rgba(255, 51, 102, 0.25) !important; border-left: 3px solid #ff3366; }
        .row-hod { background: rgba(63, 185, 80, 0.12) !important; border-left: 3px solid #3fb950; }
        .row-support { background: rgba(88, 166, 255, 0.15) !important; border-left: 3px solid #58a6ff; }
        .text-green { color: #3fb950; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 10px; border-radius: 6px; text-align: center; flex: 1; margin: 4px; }
        .p-val { font-size: 22px; font-weight: bold; color: #fff; font-family: 'Consolas'; }
        #sys-status { position: fixed; bottom: 12px; left: 12px; color: #8b949e; font-size: 11px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 5px 10px; border-radius: 4px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <div class="window" id="win-alerts" style="top:10px; left:10px; width:750px; height:450px;"><div class="title-bar"><span>🚨 即時動能警報 (V164.5 終極版)</span></div><div class="content" id="alert-list"></div></div>
    <div class="window" id="win-gainers" style="top:470px; left:10px; width:750px; height:480px;"><div class="title-bar"><span>🏆 強勢榜 (1-30 USD)</span></div><div class="content" id="gainer-list"></div></div>
    <div class="window" id="win-quote" style="top:10px; left:770px; width:450px; height:450px;"><div class="title-bar"><span>📰 24H 即時情報翻譯</span></div><div class="content" id="news-list">點擊個股開始狙擊...</div></div>
    <div class="window" id="win-pillars" style="top:470px; left:770px; width:450px; height:480px;"><div class="title-bar"><span>📊 核心五檔數據</span></div><div class="content" id="pillar-list"></div></div>

    <div id="sys-status">🔄 數據同步中...</div>

    <script>
        async function update() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 系統運行中 | ' + new Date().toLocaleTimeString();
                
                let alertH = '<div class="grid-row grid-th" style="grid-template-columns: 0.7fr 0.8fr 0.8fr 0.8fr 0.8fr 0.8fr 1.3fr;"><div>時間</div><div>代碼</div><div>價格</div><div>量比</div><div>換手</div><div>跳空</div><div>訊號</div></div>';
                data.alerts.forEach(a => {
                    let cls = a.Type.includes('Ross') ? 'row-ross' : (a.Type.includes('HOD') ? 'row-hod' : (a.Type.includes('支撐') ? 'row-support' : ''));
                    alertH += `<div class="grid-row ${cls}" style="grid-template-columns: 0.7fr 0.8fr 0.8fr 0.8fr 0.8fr 0.8fr 1.3fr;" onclick="loadDetail('${a.Code}')">
                        <div>${a.Time}</div><div class="text-blue">${a.Code}</div><div>${a.Price}</div><div>${a.RVOL}</div><div>${a.Turnover}</div><div class="text-green">${a.Gap}</div><div style="font-weight:bold;">${a.Type}</div>
                    </div>`;
                });
                document.getElementById('alert-list').innerHTML = alertH;

                let gainerH = '<div class="grid-row grid-th" style="grid-template-columns: 1fr 1fr 1fr 1.2fr 1fr;"><div>代碼</div><div>價格</div><div>漲幅</div><div>交易量</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    gainerH += `<div class="grid-row" style="grid-template-columns: 1fr 1fr 1fr 1.2fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue" style="font-weight:bold;">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div>${s.Volume}</div><div>${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('gainer-list').innerHTML = gainerH;
            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data');
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;
            document.getElementById('pillar-list').innerHTML = `
                <div style="display:flex; flex-wrap:wrap; gap:5px;">
                    <div class="p-box">最高價 (HP/HOD)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">回落幅度<div class="p-val" style="color:#f85149;">${d.Drop}</div></div>
                    <div class="p-box">跳空幅度 (%)<div class="p-val" style="color:#3fb950;">${d.Gap}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                    <div class="p-box">成交量<div class="p-val" style="font-size:18px;">${d.Volume}</div></div>
                </div>`;
        }
        setInterval(update, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心邏輯函數 ] ---
def format_volume_km(vol):
    if vol <= 0: return "N/A"
    if vol >= 1e6: return f"{vol/1e6:.1f}M"
    if vol >= 1e3: return f"{vol/1e3:.0f}K"
    return str(int(vol))

def parse_vol_str(v):
    v = str(v).upper().replace(',','').replace(' ','')
    if 'M' in v: return float(v.replace('M',''))*1e6
    if 'K' in v: return float(v.replace('K',''))*1e3
    try: return float(v)
    except: return 0

def fetch_advanced_data(ticker):
    f_shares, a_vol, prev_close = 0, 1, 0
    try:
        t = yf.Ticker(ticker); info = t.info
        f_shares = info.get('floatShares', 0) or info.get('sharesOutstanding', 1)
        a_vol = info.get('averageVolume', 1)
        prev_close = info.get('previousClose', 0)
    except: pass
    return f_shares, a_vol, prev_close

# --- [ 3. 掃描引擎 ] ---
def scanner_job():
    global MASTER_BRAIN
    print("🚀 掃描器引擎已啟動，正在抓取數據...")
    while True:
        try:
            url = "https://stockanalysis.com/markets/premarket/gainers/"
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            
            if table:
                temp_stocks, alerts = [], []
                for tr in table.find_all('tr')[1:35]:
                    tds = tr.find_all('td')
                    if len(tds) < 5: continue
                    sym = tds[1].text.strip()
                    p_num = float(tds[4].text.replace('$','').replace(',',''))
                    
                    if 1.0 <= p_num <= 30.0:
                        if sym not in stock_info_cache:
                            f, a, prev = fetch_advanced_data(sym)
                            stock_info_cache[sym] = (f, a, prev)
                        else:
                            f, a, prev = stock_info_cache[sym]

                        cell = MASTER_BRAIN["details"].get(sym, {"HOD_num": 0})
                        vol_n = parse_vol_str(tds[5].text)
                        if p_num > cell["HOD_num"]: cell["HOD_num"] = p_num
                        
                        gap_pct = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol_val = vol_n / a if a > 0 else 1.0
                        
                        item = {
                            "Time": datetime.now().strftime('%H:%M:%S'), "Code": sym, "Price": f"${p_num:.2f}",
                            "Change": tds[3].text, "Volume": format_volume_km(vol_n), "RVOL": f"{rvol_val:.1f}x",
                            "Gap": f"{gap_pct:.1f}%", "Turnover": f"{(vol_n/f*100):.1f}%" if f > 0 else "0%",
                            "Drop": f"{((p_num - cell['HOD_num']) / cell['HOD_num'] * 100):.1f}%" if cell['HOD_num'] > 0 else "0%",
                            "HOD": f"${cell['HOD_num']:.2f}", "Type": "🆕NEW", "NewsList": []
                        }
                        temp_stocks.append(item)
                        MASTER_BRAIN["details"][sym] = item
                
                MASTER_BRAIN["stocks"] = temp_stocks
                MASTER_BRAIN["alerts"] = temp_stocks[:15]
                print(f"✅ 數據更新完成，目前抓到 {len(temp_stocks)} 檔標的")
            time.sleep(10)
        except Exception as e: 
            print(f"❌ 掃描出錯: {e}")
            time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
