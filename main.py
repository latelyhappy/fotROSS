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

# ★ 數據中樞 (MASTER_BRAIN)
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], "live": [], 
    "details": {}, "last_update": "N/A"
}
stock_cache = {} # 靜態數據快取 (Float, AvgVol, PrevClose)
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 豪華 UI 介面：支援所有核心功能 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V165.6 - 數據同步修正版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; align-items: center; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; position: relative; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 6px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-sniper { background: rgba(63, 185, 80, 0.18) !important; border-left: 3px solid #3fb950; }
        .row-drop { background: rgba(255, 51, 102, 0.22) !important; border-left: 3px solid #ff3366; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 10px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 20px; font-weight: bold; color: #fff; margin-top: 4px; }
        .news-item { border-left: 3px solid #f2cc60; padding-left: 10px; margin-bottom: 12px; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 2. 狙擊手 (跳空 + 大量)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-live" style="top:10px; left:500px; width:480px; height:320px;"><div class="title-bar">📡 4. 即時報警 (10s 全面同步)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-drop" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 5. 下跌警報 (Ross Drop)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-rank" style="top:340px; left:500px; width:480px; height:640px;"><div class="title-bar">🏆 3. 排行掃描 (1-30 USD)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-details" style="top:670px; left:10px; width:480px; height:310px;"><div class="title-bar">📊 1. 指標詳情與戰情</div><div class="content" id="detail-list">點擊個股代碼...</div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 掃描引擎同步中...</div>

    <script>
        async function refreshUI() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 更新: ' + data.last_update + ' | 本地: ' + new Date().toLocaleTimeString();

                // 2. 狙擊手
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    snipH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;

                // 4. 即時報警 (修正：直接顯示當前掃描快照，確保數據必動)
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>狀態</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;" onclick="loadDetail('${l.Code}')">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div>${l.Type}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 5. 下跌警報
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;"><div>代碼</div><div>價格</div><div>回落%</div><div>訊號</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row row-drop" style="grid-template-columns: 0.8fr 1fr 1.1fr 1.1fr;" onclick="loadDetail('${d.Code}')">
                        <div class="text-blue">${d.Code}</div><div>${d.Price}</div><div class="text-red">${d.Drop}</div><div>${d.Type}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 3. 排行榜
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;"><div>代碼</div><div>漲幅%</div><div>漲幅$</div><div>浮動股</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 0.8fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue" style="font-weight:bold;">${s.Code}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div><div>${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('rank-list').innerHTML = rankH;
            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data?t=' + Date.now());
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;

            let newsHTML = '<h3 style="margin-top:15px; border-bottom:1px solid #30363d;">📰 即時情報翻譯</h3>';
            if (d.NewsList && d.NewsList.length > 0) {
                d.NewsList.forEach(n => {
                    newsHTML += `<div class="news-item"><span style="color:#8b949e; font-size:10px;">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none; font-weight:bold;">${n.title}</a></div>`;
                });
            } else {
                newsHTML += '<p style="color:#8b949e">正在檢索新聞...</p>';
            }

            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap}</div></div>
                    <div class="p-box">平均量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                </div>${newsHTML}`;
        }

        // 視窗交互與拖動
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
        setInterval(refreshUI, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心數據模組：補全新聞與指標 ] ---
def fetch_news(ticker): #
    news_list = []
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        for item in root.findall('./channel/item')[:3]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            dt = parser.parse(item.find('pubDate').text)
            news_list.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': dt.strftime('%Y/%m/%d %H:%M')
            })
    except: pass
    return news_list

def get_static_data(ticker): #
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker); i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1)
        a = i.get('averageVolume', 1)
        p = i.get('previousClose', 0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

# --- [ 3. 中央掃描引擎：強效同步邏輯 ] ---
def scanner_loop():
    global MASTER_BRAIN
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=8)
            if r.status_code != 200: 
                time.sleep(5); continue

            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            if not table: 
                time.sleep(5); continue

            temp_rank, temp_snip, temp_drop, temp_live = [], [], [], []
            for tr in table.find_all('tr')[1:30]:
                tds = tr.find_all('td')
                if len(tds) < 5: continue
                sym = tds[1].text.strip()
                p_num = float(tds[4].text.replace('$','').replace(',',''))
                
                if 1.0 <= p_num <= 30.0:
                    f, a, prev = get_static_data(sym)
                    vol_raw = float(tds[5].text.replace('K','000').replace('M','000000').replace(',',''))
                    
                    cell = MASTER_BRAIN["details"].get(sym, {"HOD": p_num, "NewsList": []})
                    if p_num > cell["HOD"]: cell["HOD"] = p_num
                    
                    gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                    rvol = vol_raw / a if a > 0 else 1.0
                    drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0

                    item = {
                        "Time": current_time, "Code": sym, "Price": f"${p_num:.2f}",
                        "Change": tds[3].text, "ChangeAmt": f"${(p_num-prev):.2f}", "RVOL": f"{rvol:.1f}x",
                        "Gap": f"{gap_p:.1f}%", "Turnover": f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%",
                        "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}", 
                        "FloatStr": f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K", "Type": "🆕 掃描"
                    }

                    # 篩選分流
                    if gap_p > 3.0 and rvol > 5.0:
                        item["Type"] = "🚀 第一根狙擊"; temp_snip.append(item)
                    if drop_p < -2.0:
                        item["Type"] = "🔴 Ross 下跌"; temp_drop.append(item)
                    if p_num >= cell["HOD"]:
                        item["Type"] = "🔥 HOD 突破"
                    
                    # 即時報警：加入所有當前掃描到的項目 (保證會動)
                    temp_live.append(item)
                    temp_rank.append(item)

                    # 異步抓取新聞
                    if not cell["NewsList"] or "🚀" in item["Type"]:
                        cell["NewsList"] = fetch_news(sym)

                    MASTER_BRAIN["details"][sym] = {
                        "HOD": f"${cell['HOD']:.2f}", "NewsList": cell["NewsList"], 
                        "Gap": item["Gap"], "Turnover": item["Turnover"], "RVOL": item["RVOL"]
                    }

            # 更新 MASTER_BRAIN 並設定刷新時間
            MASTER_BRAIN.update({
                "stocks": temp_rank, "sniper": temp_snip, "drop": temp_drop, 
                "live": temp_live[:20], "last_update": current_time
            })
            
            time.sleep(random.uniform(7.0, 13.0)) # 遵循 10s (±3s) 節奏
        except: time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
