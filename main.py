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
    "last_update": "尚未開始", "server_time": ""
}
# 快取機制：(float, avg_vol, prev_close, timestamp)
stock_static_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. UI 介面：加入「通訊心跳」監控 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V165.1 - 極速同步版</title>
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
        .heartbeat { width: 8px; height: 8px; background: #3fb950; border-radius: 50%; display: inline-block; margin-right: 5px; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 2. 狙擊手 (Gap > 3% + RVOL > 5x)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-live" style="top:10px; left:500px; width:480px; height:320px;"><div class="title-bar">📡 4. 即時報警 (3-5s 極速循環)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-drop" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 5. 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-rank" style="top:340px; left:500px; width:480px; height:640px;"><div class="title-bar">🏆 3. 排行榜 (全資料同步)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-details" style="top:670px; left:10px; width:480px; height:310px;"><div class="title-bar">📊 1. 戰情細節與新聞</div><div class="content" id="detail-list">點擊代碼...</div><div class="resize-handle"></div></div>

    <div id="sys-status"><span class="heartbeat" id="hb"></span><span id="stat-text">正在連接後端...</span></div>

    <script>
        let hbState = true;
        async function refreshUI() {
            try {
                // ★ Cache Buster: 加入 Date.now() 確保每次都是最新請求
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                
                hbState = !hbState;
                document.getElementById('hb').style.opacity = hbState ? "1" : "0.3";
                document.getElementById('stat-text').innerText = '最後掃描: ' + data.last_update + ' | 本地: ' + new Date().toLocaleTimeString();

                // 2. 狙擊手
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    snipH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;

                // 4. 即時報警
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>動態</div></div>';
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
                        <div class="text-blue">${s.Code}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div><div>${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('rank-list').innerHTML = rankH;
            } catch(e) { console.error("UI Update Error:", e); }
        }

        async function loadDetail(sym) {
            const res = await fetch('/data?t=' + Date.now());
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;
            let newsHTML = '<h3 style="margin-top:15px; border-bottom:1px solid #30363d;">📰 即時情報翻譯</h3>';
            d.NewsList.forEach(n => {
                newsHTML += `<div class="news-item"><span style="color:#8b949e; font-size:10px;">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none; font-weight:bold;">${n.title}</a></div>`;
            });
            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap}</div></div>
                    <div class="p-box">平均量比<div class="p-val">${d.RVOL}</div></div>
                </div>${newsHTML}`;
        }

        // 視窗拖拽縮放維持原樣
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
        setInterval(refreshUI, 2000); // 2秒前端主動向後端要資料
    </script>
</body>
</html>
"""

# --- [ 2. 核心數據函數：加入快取機制減少 API 請求 ] ---
def fetch_static_info(ticker):
    # 檢查快取 (1小時內有效)
    now = time.time()
    if ticker in stock_static_cache:
        f, a, p, ts = stock_static_cache[ticker]
        if now - ts < 3600: return f, a, p

    try:
        t = yf.Ticker(ticker)
        # 僅獲取絕對必要的靜態數據
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1)
        a = i.get('averageVolume', 1)
        p = i.get('previousClose', 0)
        stock_static_cache[ticker] = (f, a, p, now)
        return f, a, p
    except: return 0, 1, 0

def fetch_news(ticker):
    news_list = []
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=3)
        root = ET.fromstring(r.content)
        for item in root.findall('./channel/item')[:3]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            news_list.append({'title': translator.translate(title_en), 'link': item.find('link').text, 'time': datetime.now().strftime('%H:%M')})
    except: pass
    return news_list

# --- [ 3. 掃描引擎：優化循環速度 ] ---
def central_scanner():
    global MASTER_BRAIN
    while True:
        try:
            scan_time = datetime.now().strftime('%H:%M:%S')
            # 優先從 StockAnalysis 獲取即時價格與交易量 (這部分很快，不會被封)
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
                if table:
                    temp_rank, temp_snip, temp_drop, temp_live = [], [], [], []
                    for tr in table.find_all('tr')[1:30]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        sym = tds[1].text.strip()
                        p_num = float(tds[4].text.replace('$','').replace(',',''))
                        
                        if 1.0 <= p_num <= 30.0:
                            # 關鍵：使用快取的靜態數據，避免每 3 秒請求一次 Yahoo Finance
                            f, a, prev = fetch_static_info(sym)
                            
                            cell = MASTER_BRAIN["details"].get(sym, {"HOD": 0, "NewsList": []})
                            vol_raw = float(tds[5].text.replace('K','000').replace('M','000000').replace(',',''))
                            
                            if p_num > cell["HOD"]: cell["HOD"] = p_num
                            gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                            rvol_v = vol_raw / a if a > 0 else 1.0
                            drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0

                            item = {
                                "Time": scan_time, "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": tds[3].text, "ChangeAmt": f"${(p_num-prev):.2f}", "RVOL": f"{rvol_v:.1f}x",
                                "Gap": f"{gap_p:.1f}%", "Turnover": f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%",
                                "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}", 
                                "FloatStr": f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K", "Type": "🆕NEW"
                            }

                            if gap_p > 3.0 and rvol_v > 5.0: item["Type"] = "🚀 狙擊進場"; temp_snip.append(item)
                            if drop_p < -2.0: item["Type"] = "🔴 Ross 警告"; temp_drop.append(item)
                            if p_num >= cell["HOD"]: item["Type"] = "🔥 HOD 突破"
                            
                            temp_live.append(item); temp_rank.append(item)
                            # 新聞異步更新，避免卡死主循環
                            item["NewsList"] = cell["NewsList"] if cell["NewsList"] else []
                            MASTER_BRAIN["details"][sym] = item
                    
                    MASTER_BRAIN.update({"stocks": temp_rank, "sniper": temp_snip, "drop": temp_drop, "live": temp_live, "last_update": scan_time})

            # 極速冷卻：3秒
            time.sleep(3)
        except Exception as e:
            print(f"Scanner Loop Warning: {e}")
            time.sleep(5)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=central_scanner, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
