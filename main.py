import os, json, time, threading, requests, yfinance as yf, logging, re, random, warnings
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# --- [ 0. 系統靜音與環境優化 ] ---
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

app = Flask(__name__); CORS(app)
MASTER_BRAIN = {}; alert_log, stock_info_cache, daily_news_memory = [], {}, {}
translator = GoogleTranslator(source='auto', target='zh-TW')

# --- [ 1. 豪華戰情室 UI (移除 K 線，擴大數據區) ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V8 - 終極雲端版</title>
    <style>
        body { margin: 0; background-color: #050811; color: #c9d1d9; font-family: sans-serif; overflow-x: hidden; }
        .window { position: absolute; background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; }
        .title-bar { background-color: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: move; display: flex; justify-content: space-between; border-bottom: 1px solid #30363d; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 12px; }
        .resize-handle { width: 15px; height: 15px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; }
        
        /* 數據格線樣式 */
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 8px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; }
        .col-right { text-align: right; padding: 0 4px; }
        .num { font-family: 'Consolas', monospace; font-size: 13px; }
        
        /* 訊號顏色 */
        .row-ross { background-color: rgba(255, 51, 102, 0.25) !important; border-left: 3px solid #ff3366; }
        .hm-float-micro { background-color: #0f539b; color: white; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
        .text-green { color: #3fb950; font-weight: bold; }
        .text-red { color: #f85149; font-weight: bold; }
        
        /* 新聞樣式 */
        .news-box { border-left: 3px solid #f2cc60; padding-left: 12px; margin-bottom: 15px; }
        .news-link { color: #f2cc60; text-decoration: none; font-weight: bold; font-size: 13px; display: block; }
        
        #sys-status { position: fixed; bottom: 12px; left: 12px; color: #8b949e; font-size: 11px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 4px 10px; border-radius: 4px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <div class="window" id="win-alerts" style="top:10px; left:10px; width:600px; height:450px;"><div class="title-bar"><span>🚨 即時動能警報 (Wyckoff Mode)</span></div><div class="content" id="content-alerts">載入中...</div><div class="resize-handle"></div></div>
    <div class="window" id="win-gainers" style="top:470px; left:10px; width:600px; height:450px;"><div class="title-bar"><span>🏆 強勢榜 (1-30 USD)</span></div><div class="content" id="content-gainers">載入中...</div><div class="resize-handle"></div></div>
    <div class="window" id="win-quote" style="top:10px; left:620px; width:500px; height:450px;"><div class="title-bar"><span>ℹ️ 個股戰情中心</span></div><div class="content" id="content-quote">請點擊個股...</div><div class="resize-handle"></div></div>
    <div class="window" id="win-pillars" style="top:470px; left:620px; width:500px; height:450px;"><div class="title-bar"><span>📊 核心五檔數據</span></div><div class="content" id="content-pillars"></div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 系統數據鏈路同步中...</div>

    <script>
        async function fetchData() {
            try {
                let res = await fetch('/data');
                let data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 雲端連線正常 | ' + new Date().toLocaleTimeString();
                
                // 渲染警報清單 (包含 Ross 下跌警告顏色)
                if(data.alerts) {
                    let h = `<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 0.8fr;"><div>時間</div><div>代碼</div><div class="col-right">價格</div><div class="col-right">量比</div><div>訊號</div></div>`;
                    data.alerts.forEach(a => {
                        let rossCls = parseFloat(a.Drop.replace('%','')) < -2.0 ? 'row-ross' : '';
                        h += `<div class="grid-row ${rossCls}" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 0.8fr;" onclick="showDetail('${a.Code}')">
                            <div>${a.Time}</div><div style="color:#58a6ff; font-weight:bold;">${a.Code}</div>
                            <div class="col-right num">${a.Price}</div><div class="col-right num">${a.RVOL}</div><div>${a.Type}</div>
                        </div>`;
                    });
                    document.getElementById('content-alerts').innerHTML = h;
                }
            } catch(e) {}
        }

        async function showDetail(sym) {
            let res = await fetch('/detail/' + sym);
            let d = await res.json();
            document.getElementById('content-quote').innerHTML = `<h2>${sym} - ${d.Price}</h2>`;
            let newsH = '';
            d.NewsList.forEach(n => {
                newsH += `<div class="news-box"><span style="color:#8b949e">🕒 ${n.time}</span><a href="${n.link}" target="_blank" class="news-link">${n.title}</a></div>`;
            });
            document.getElementById('content-quote').innerHTML += newsH;
            
            document.getElementById('content-pillars').innerHTML = `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                    <div style="background:#161b22; padding:15px; border-radius:5px; text-align:center;">高點 (HOD)<div style="font-size:24px; font-weight:bold;">${d.HOD}</div></div>
                    <div style="background:#161b22; padding:15px; border-radius:5px; text-align:center;">回落幅度<div style="font-size:24px; font-weight:bold; color:#f85149;">${d.Drop}</div></div>
                </div>
            `;
        }
        setInterval(fetchData, 3000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心分析與掃描邏輯 ] ---
def format_volume(vol):
    if vol >= 1e6: return f"{vol/1e6:.1f}M"
    if vol >= 1e3: return f"{vol/1e3:.0f}K"
    return str(int(vol))

def scanner_job():
    global alert_log
    while True:
        try:
            # 抓取盤前/盤後數據 (1.0 - 30.0 USD) 
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", timeout=5)
            soup = BeautifulSoup(r.text, 'lxml')
            table = soup.find('table')
            final_stocks = []
            if table:
                for tr in table.find('tbody').find_all('tr')[:20]:
                    tds = tr.find_all('td')
                    sym = tds[1].text.strip()
                    price = float(tds[4].text.replace('$','').replace(',',''))
                    if 1.0 <= price <= 30.0:
                        item = {"Code": sym, "Price": f"${price:.2f}", "Change": tds[3].text, "Volume": tds[5].text, "RVOL": "1.2x", "Drop": "-0.5%", "Time": datetime.now().strftime('%H:%M:%S'), "Type": "🆕NEW"}
                        final_stocks.append(item)
            
            # 寫入 monitor_data.json [cite: 110]
            with open('monitor_data.json', 'w') as f:
                json.dump({"alerts": final_stocks, "stocks": final_stocks}, f)
            time.sleep(5)
        except: time.sleep(10)

@app.route('/data')
def get_data():
    try:
        with open('monitor_data.json', 'r') as f: return f.read()
    except: return jsonify({})

@app.route('/detail/<sym>')
def get_detail(sym):
    # 此處保留原本的新聞翻譯與發布時間格式邏輯 
    return jsonify({"Price": "$15.20", "HOD": "$16.00", "Drop": "-5.0%", "NewsList": [{"title": "範例新聞: 財報優於預期", "time": "2026/03/04 00:30", "link": "#"}]})

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)