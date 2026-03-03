import os, json, time, threading, requests, yfinance as yf, logging, re, random, warnings
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# --- [ 0. 系統環境設定 ] ---
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

app = Flask(__name__); CORS(app)
MASTER_BRAIN = {"alerts": [], "stocks": [], "raw_top20": [], "details": {}}
alert_log, stock_info_cache, daily_news_memory = [], {}, {}
translator = GoogleTranslator(source='auto', target='zh-TW')

STEALTH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

# --- [ 1. 豪華版 UI 介面 (復原 260225 樣式，移除 K 線) ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>Sniper V8 終極雲端系統</title>
    <style>
        body { margin: 0; background-color: #050811; color: #c9d1d9; font-family: sans-serif; overflow-x: hidden; }
        .window { position: absolute; background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background-color: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: grab; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 12px; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 8px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-ross { background-color: rgba(255, 51, 102, 0.25) !important; border-left: 3px solid #ff3366; }
        .row-hod { background-color: rgba(63, 185, 80, 0.12); border-left: 3px solid #3fb950; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 12px; border-radius: 6px; text-align: center; flex: 1; margin: 5px; }
        .p-val { font-size: 26px; font-weight: bold; color: #fff; font-family: 'Consolas'; }
        .news-box { border-left: 3px solid #f2cc60; padding-left: 12px; margin-bottom: 15px; }
        .news-link { color: #f2cc60; text-decoration: none; font-weight: bold; font-size: 13px; display: block; margin-top: 4px; }
        #sys-status { position: fixed; bottom: 12px; left: 12px; color: #8b949e; font-size: 12px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 6px 12px; border-radius: 4px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <div class="window" id="win-alerts" style="top:10px; left:10px; width:650px; height:450px;"><div class="title-bar"><span>🚨 即時動能警報 (Ross Signal)</span></div><div class="content" id="alert-list"></div></div>
    <div class="window" id="win-gainers" style="top:470px; left:10px; width:650px; height:450px;"><div class="title-bar"><span>🏆 強勢榜 (1-30 USD)</span></div><div class="content" id="gainer-list"></div></div>
    <div class="window" id="win-quote" style="top:10px; left:670px; width:500px; height:450px;"><div class="title-bar"><span>📰 24H 即時情報翻譯</span></div><div class="content" id="news-list">請點擊個股...</div></div>
    <div class="window" id="win-pillars" style="top:470px; left:670px; width:500px; height:450px;"><div class="title-bar"><span>📊 核心五檔數據</span></div><div class="content" id="pillar-list"></div></div>

    <div id="sys-status">🔄 數據鏈路同步中...</div>

    <script>
        async function update() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 雲端連線正常 | ' + new Date().toLocaleTimeString();
                
                // 警報清單渲染 [cite: 67, 73]
                let alertH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 0.8fr;"><div>時間</div><div>代碼</div><div>價格</div><div>量比</div><div>回落</div><div>訊號</div></div>';
                data.alerts.forEach(a => {
                    let isRoss = parseFloat(a.Drop) < -2.0;
                    alertH += `<div class="grid-row ${isRoss ? 'row-ross' : ''} ${a.Type.includes('HOD')?'row-hod':''}" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 0.8fr;" onclick="loadDetail('${a.Code}')">
                        <div>${a.Time}</div><div style="color:#58a6ff; font-weight:bold;">${a.Code}</div><div>${a.Price}</div><div>${a.RVOL}</div><div class="${isRoss ? 'text-red' : ''}">${a.Drop}</div><div>${a.Type}</div>
                    </div>`;
                });
                document.getElementById('alert-list').innerHTML = alertH;

                // 強勢榜渲染 [cite: 74, 80]
                let gainerH = '<div class="grid-row grid-th" style="grid-template-columns: 1fr 1fr 1fr 1.2fr 1fr;"><div>代碼</div><div>價格</div><div>漲幅</div><div>交易量</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    gainerH += `<div class="grid-row" style="grid-template-columns: 1fr 1fr 1fr 1.2fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div style="color:#58a6ff; font-weight:bold;">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div>${s.Volume}</div><div>${s.RVOL}</div>
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

            // 新聞渲染 [cite: 62, 63]
            let newsH = `<h3>${sym} 戰情情報</h3>`;
            d.NewsList.forEach(n => {
                newsH += `<div class="news-box"><span style="color:#8b949e">🕒 ${n.time}</span><a href="${n.link}" target="_blank" class="news-link">${n.title}</a></div>`;
            });
            document.getElementById('news-list').innerHTML = newsH;

            // 五檔渲染 [cite: 64]
            document.getElementById('pillar-list').innerHTML = `
                <div style="display:flex; flex-wrap:wrap; gap:10px;">
                    <div class="p-box">最高價 (HOD)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">回落幅度<div class="p-val" style="color:#f85149;">${d.Drop}</div></div>
                    <div class="p-box">交易量<div class="p-val" style="font-size:20px;">${d.Volume}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                    <div class="p-box">浮動股數<div class="p-val">${d.FloatStr}</div></div>
                </div>`;
        }

        setInterval(update, 3000);
        
        // 視窗拖動邏輯 [cite: 45, 49]
        document.querySelectorAll('.window').forEach(win => {
            const title = win.querySelector('.title-bar');
            title.onmousedown = (e) => {
                let p1 = 0, p2 = 0, p3 = e.clientX, p4 = e.clientY;
                document.onmousemove = (e) => {
                    p1 = p3 - e.clientX; p2 = p4 - e.clientY; p3 = e.clientX; p4 = e.clientY;
                    win.style.top = (win.offsetTop - p2) + "px"; win.style.left = (win.offsetLeft - p1) + "px";
                };
                document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; };
            };
        });
    </script>
</body>
</html>
"""

# --- [ 2. 數據抓取邏輯 (復原 260225 核心函數) ] ---
def parse_vol_str(v):
    v = str(v).upper().replace(',','').replace(' ','')
    if 'M' in v: return float(v.replace('M',''))*1e6
    if 'K' in v: return float(v.replace('K',''))*1e3
    try: return float(v)
    except: return 0

def fetch_advanced_data(ticker):
    f_shares, a_vol = 0, 1
    try:
        t = yf.Ticker(ticker)
        f_shares = t.info.get('floatShares', 0)
        a_vol = t.info.get('averageVolume', 1)
    except: pass
    return f_shares, a_vol

def fetch_news(ticker):
    news_list = []
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=5); root = ET.fromstring(r.content)
        for item in root.findall('./channel/item')[:4]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            dt = parser.parse(item.find('pubDate').text)
            news_list.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': dt.strftime('%Y/%m/%d %H:%M')
            })
    except: pass
    return news_list

# --- [ 3. 掃描器引擎 ] ---
def scanner_job():
    global MASTER_BRAIN, alert_log
    while True:
        try:
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=5)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            final_stocks = []
            if table:
                for tr in table.find('tbody').find_all('tr')[:30]:
                    tds = tr.find_all('td')
                    sym = tds[1].text.strip()
                    p_num = float(tds[4].text.replace('$','').replace(',',''))
                    
                    if 1.0 <= p_num <= 30.0:
                        cell = MASTER_BRAIN["details"].get(sym, {"HOD_num": 0})
                        if p_num > cell["HOD_num"]: cell["HOD_num"] = p_num
                        drop = f"{((p_num - cell['HOD_num']) / cell['HOD_num'] * 100):.1f}%" if cell["HOD_num"] > 0 else "0.0%"
                        
                        f, a = fetch_advanced_data(sym)
                        vol_n = parse_vol_str(tds[5].text)
                        
                        item = {
                            "Code": sym, "Price": f"${p_num:.2f}", "Change": tds[3].text,
                            "Volume": tds[5].text, "RVOL": f"{vol_n/a:.1f}x" if a > 0 else "1.0x",
                            "Drop": drop, "HOD": f"${cell['HOD_num']:.2f}", "Time": datetime.now().strftime('%H:%M:%S'),
                            "FloatStr": f"{f/1e6:.1f}M" if f > 0 else "N/A", "Type": "🆕NEW",
                            "NewsList": fetch_news(sym)
                        }
                        final_stocks.append(item)
                        MASTER_BRAIN["details"][sym] = item
            
            MASTER_BRAIN["stocks"] = final_stocks
            MASTER_BRAIN["alerts"] = final_stocks[:15]
            time.sleep(10)
        except: time.sleep(5)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)