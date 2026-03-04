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

# 核心數據容器
MASTER_BRAIN = {"alerts": [], "stocks": [], "raw_top20": [], "details": {}}
alert_log, stock_info_cache, daily_news_memory = [], {}, {}
translator = GoogleTranslator(source='auto', target='zh-TW')

STEALTH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

# --- [ 1. 豪華版 UI 介面：完整支援拖拽、縮放與 Ross 警告 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>Sniper V8 終極雲端系統</title>
    <style>
        body { margin: 0; padding: 0; background-color: #050811; color: #c9d1d9; font-family: sans-serif; overflow-x: hidden; }
        .window { position: absolute; background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; min-width: 200px; z-index: 1; }
        .title-bar { background-color: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: grab; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; user-select: none; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 12px; position: relative; }
        .resize-handle { width: 15px; height: 15px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100; }
        
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 8px 0; cursor: pointer; transition: background 0.1s; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-ross { background-color: rgba(255, 51, 102, 0.25) !important; border-left: 3px solid #ff3366; }
        .row-hod { background-color: rgba(63, 185, 80, 0.12) !important; border-left: 3px solid #3fb950; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 12px; border-radius: 6px; text-align: center; flex: 1; }
        .p-val { font-size: 24px; font-weight: bold; color: #fff; margin-top: 5px; font-family: 'Consolas'; }
        .news-box { border-left: 3px solid #f2cc60; padding-left: 12px; margin-bottom: 15px; }
        .news-link { color: #f2cc60; text-decoration: none; font-weight: bold; font-size: 13px; display: block; margin-top: 4px; }
        #sys-status { position: fixed; bottom: 12px; left: 12px; color: #8b949e; font-size: 12px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 6px 12px; border-radius: 4px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <div class="window" id="win-alerts" style="top:10px; left:10px; width:550px; height:450px;"><div class="title-bar"><span>🚨 即時動能警報 (Ross/HOD)</span></div><div class="content" id="alert-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-gainers" style="top:470px; left:10px; width:550px; height:480px;"><div class="title-bar"><span>🏆 強勢榜 (1-30 USD)</span></div><div class="content" id="gainer-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-quote" style="top:10px; left:570px; width:450px; height:450px;"><div class="title-bar"><span>📰 24H 即時情報翻譯</span></div><div class="content" id="news-list">點擊個股開始狙擊...</div><div class="resize-handle"></div></div>
    <div class="window" id="win-pillars" style="top:470px; left:570px; width:450px; height:480px;"><div class="title-bar"><span>📊 核心五檔數據</span></div><div class="content" id="pillar-list"></div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 數據鏈路同步中...</div>

    <script>
        async function update() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ V164.5 雲端版 | ' + new Date().toLocaleTimeString();
                
                // 警報列表渲染 [cite: 1, 67, 108]
                let alertH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 1fr 0.8fr;"><div>時間</div><div>代碼</div><div>價格</div><div>量比</div><div>回落</div><div>訊號</div></div>';
                data.alerts.forEach(a => {
                    let isRoss = parseFloat(a.Drop) < -2.0;
                    let isHOD = a.Type.includes('HOD');
                    alertH += `<div class="grid-row ${isRoss ? 'row-ross' : (isHOD ? 'row-hod' : '')}" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 1fr 0.8fr;" onclick="loadDetail('${a.Code}')">
                        <div>${a.Time}</div><div class="text-blue" style="font-weight:bold;">${a.Code}</div><div>${a.Price}</div><div>${a.RVOL}</div><div class="${isRoss ? 'text-red' : ''}">${a.Drop}</div><div>${a.Type}</div>
                    </div>`;
                });
                document.getElementById('alert-list').innerHTML = alertH;

                // 強勢榜渲染 [cite: 1, 74, 106]
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

            // 新聞翻譯渲染 [cite: 1, 62, 90]
            let newsH = `<h3>${sym} 戰情中心</h3>`;
            d.NewsList.forEach(n => {
                newsH += `<div class="news-box"><span style="color:#8b949e">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" class="news-link">${n.title}</a></div>`;
            });
            document.getElementById('news-list').innerHTML = newsH || '暫無今日新聞';

            // 核心五檔渲染 [cite: 1, 64, 105]
            document.getElementById('pillar-list').innerHTML = `
                <div style="display:flex; flex-wrap:wrap; gap:5px;">
                    <div class="p-box">最高價 (HOD/HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">回落幅度 (%)<div class="p-val" style="color:#f85149;">${d.Drop}</div></div>
                    <div class="p-box">成交量<div class="p-val" style="font-size:18px;">${d.Volume}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">浮動股數<div class="p-val">${d.FloatStr}</div></div>
                </div>`;
        }

        // 視窗調整邏輯 (復原自 260225) [cite: 1, 45, 51]
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

        setInterval(update, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心運算邏輯：復原 260225 數據處理 ] ---
def format_volume_km(vol): # [cite: 1, 86]
    if vol <= 0: return "N/A"
    if vol >= 1e6: return f"{vol/1e6:.1f}M"
    if vol >= 1e3: return f"{vol/1e3:.0f}K"
    return str(int(vol))

def parse_vol_str(v): # [cite: 1, 86]
    v = str(v).upper().replace(',','').replace(' ','')
    if 'M' in v: return float(v.replace('M',''))*1e6
    if 'K' in v: return float(v.replace('K',''))*1e3
    try: return float(v)
    except: return 0

def fetch_advanced_data(ticker): # [cite: 1, 87, 88]
    f_shares, a_vol, prev_close = 0, 1, 0
    try:
        t = yf.Ticker(ticker); info = t.info
        f_shares = info.get('floatShares', 0) or info.get('sharesOutstanding', 1)
        a_vol = info.get('averageVolume', 1)
        prev_close = info.get('previousClose', 0)
    except: pass
    return f_shares, a_vol, prev_close

def fetch_news(ticker): # [cite: 1, 89, 90]
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
                'time': dt.strftime('%Y/%m/%d %H:%M') # 2026 精確格式
            })
    except: pass
    return news_list

# --- [ 3. 狙擊引擎：解決第一行空白與時間同步 ] ---
def scanner_job():
    global MASTER_BRAIN, alert_log
    while True:
        try:
            tz_us = pytz.timezone('US/Eastern')
            tz_tw = pytz.timezone('Asia/Taipei')
            now_us = datetime.now(tz_us)
            
            # 自動切換盤前/盤後網址 [cite: 1, 92]
            url = "https://stockanalysis.com/markets/premarket/gainers/" if now_us.hour < 16 else "https://stockanalysis.com/markets/after-hours/gainers/"
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=5)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            
            if table:
                temp_stocks = []
                for tr in table.find_all('tr')[1:35]:
                    tds = tr.find_all('td')
                    if len(tds) < 5: continue
                    sym = tds[1].text.strip()
                    p_num = float(tds[4].text.replace('$','').replace(',',''))
                    
                    if 1.0 <= p_num <= 30.0:
                        # 關鍵修復：預先抓取數據，防止警報第一行空白 
                        if sym not in stock_info_cache:
                            f, a, prev = fetch_advanced_data(sym)
                            stock_info_cache[sym] = (f, a, prev)
                        else:
                            f, a, prev = stock_info_cache[sym]

                        cell = MASTER_BRAIN["details"].get(sym, {"HOD_num": 0, "NewsList": []})
                        vol_n = parse_vol_str(tds[5].text)
                        
                        # HP/HOD 追蹤邏輯 [cite: 1, 97, 105]
                        if p_num > cell["HOD_num"]: cell["HOD_num"] = p_num
                        drop_pct = ((p_num - cell['HOD_num']) / cell['HOD_num'] * 100) if cell['HOD_num'] > 0 else 0
                        rvol_val = vol_n / a if a > 0 else 1.0
                        
                        # 訊號判定：Ross Signal 與 HOD 突破 [cite: 1, 106, 108]
                        a_type = "🆕NEW"
                        if drop_pct < -2.0: a_type = "🔴Ross警告"
                        elif p_num >= cell["HOD_num"] and rvol_val > 1.2: a_type = "🔥HOD突破"

                        item = {
                            "Time": datetime.now(tz_tw).strftime('%H:%M:%S'), # 時間同步 
                            "Code": sym, "Price": f"${p_num:.2f}",
                            "Change": tds[3].text, "Volume": format_volume_km(vol_n), "RVOL": f"{rvol_val:.1f}x",
                            "Gap": f"{((p_num - prev)/prev*100):.1f}%" if prev > 0 else "0.0%",
                            "Turnover": f"{(vol_n/f*100):.1f}%" if f > 0 else "0%",
                            "Drop": f"{drop_pct:.1f}%", "HOD": f"${cell['HOD_num']:.2f}", 
                            "Type": a_type, "FloatStr": format_volume_km(f),
                            "NewsList": cell.get("NewsList") if cell.get("NewsList") else fetch_news(sym)
                        }
                        temp_stocks.append(item)
                        MASTER_BRAIN["details"][sym] = item
                
                MASTER_BRAIN["stocks"] = temp_stocks
                # 保持警報列表為最新 15 筆
                MASTER_BRAIN["alerts"] = temp_stocks[:15]
            time.sleep(6)
        except: time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
