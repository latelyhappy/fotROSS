import os, time, threading, requests, random, warnings, yfinance as yf
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__); CORS(app)

# ★ 終極數據大腦：1000筆容量 + 新聞快取
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], "live": [],
    "details": {}, "last_update": "系統啟動中...", "scan_count": 0
}
stock_cache = {} # 存放 Float, AvgVol, PrevClose 避免 yfinance 卡死
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極 UI 介面：加入低流通高亮與閃爍動畫 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V200.6 - 終極完全體</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100;}
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; transition: background 0.2s; }
        .grid-row:hover { background: #161b22; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .text-gold { color: #f2cc60; font-weight: bold; } /* 低流通股專用金色 */
        
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 8px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 18px; font-weight: bold; color: #fff; margin-top: 4px; font-family: 'Consolas'; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; z-index: 1000; }
        
        /* 新狙擊閃爍動畫 */
        @keyframes flash { 0% { background-color: rgba(63, 185, 80, 0.5); } 100% { background-color: transparent; } }
        .flash-row { animation: flash 1.5s ease-out; border-left: 3px solid #3fb950; }
        .drop-row { border-left: 3px solid #ff3366; background: rgba(255, 51, 102, 0.1); }
    </style>
</head>
<body>
    <div class="window" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 狙擊手 (Gap>3%, RVOL>5x)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" style="top:10px; left:500px; width:540px; height:600px;"><div class="title-bar">📡 即時報警 (1000筆歷史滾動)</div><div class="content" id="live-list"></div><div class="resize-handle"></div></div>
    <div class="window" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" style="top:620px; left:500px; width:540px; height:360px;"><div class="title-bar">🏆 強勢榜 (1-30 USD)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>
    <div class="window" style="top:670px; left:10px; width:480px; height:310px;"><div class="title-bar">📊 戰情與新聞 (點擊代碼)</div><div class="content" id="detail-list"><div style="color:#8b949e; padding:10px;">請點擊任何股票代碼以載入戰情分析...</div></div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 掃描引擎連線中...</div>

    <script>
        let prevSniperCount = 0;

        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 狀態: 正常 | 最後掃描: ' + data.last_update + ' | 總次數: ' + data.scan_count;

                // 2. 狙擊手 (加入新目標閃爍)
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1fr;"><div>代碼</div><div>價格</div><div>跳空%</div><div>量比</div></div>';
                let currentSniperCount = data.sniper.length;
                let isNewSniper = currentSniperCount > prevSniperCount;
                
                data.sniper.forEach(s => {
                    let rowClass = isNewSniper ? "grid-row flash-row" : "grid-row";
                    snipH += `<div class="${rowClass}" style="grid-template-columns: 0.8fr 1fr 1fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Gap}</div><div class="text-gold">${s.RVOL}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;
                prevSniperCount = currentSniperCount;

                // 4. 即時報警 (1000筆歷史)
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1.2fr;"><div>時間</div><div>代碼</div><div>價格</div><div>漲跌%</div><div>觸發</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1.2fr;" onclick="loadDetail('${l.Code}')">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div class="${l.Change.includes('-') ? 'text-red' : 'text-green'}">${l.Change}</div><div style="color:#8b949e">${l.Type}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 5. 下跌警報
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1fr;"><div>代碼</div><div>價格</div><div>最高(HP)</div><div>回落%</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row drop-row" style="grid-template-columns: 0.8fr 1fr 1fr 1fr;" onclick="loadDetail('${d.Code}')">
                        <div class="text-blue">${d.Code}</div><div>${d.Price}</div><div>${d.HOD}</div><div class="text-red">${d.Drop}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 3. 強勢榜 (加入 Float < 20M 高亮)
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1.2fr 1fr;"><div>代碼</div><div>價格</div><div>漲幅%</div><div>浮動股(Float)</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    let floatVal = parseFloat(s.FloatStr.replace('M','').replace('K',''));
                    let isLowFloat = s.FloatStr.includes('M') && floatVal < 20.0 || s.FloatStr.includes('K');
                    let floatClass = isLowFloat ? "text-gold" : "";
                    
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 1.2fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div class="${floatClass}">${s.FloatStr}</div><div>${s.RVOL}</div>
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

            let newsHTML = '<h3 style="margin-top:10px; border-bottom:1px solid #30363d; padding-bottom:5px;">📰 24H 情報翻譯</h3>';
            if (d.NewsList && d.NewsList.length > 0) {
                d.NewsList.forEach(n => {
                    newsHTML += `<div style="border-left:3px solid #f2cc60; padding-left:8px; margin-bottom:8px;"><span style="color:#8b949e; font-size:10px;">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none;">${n.title}</a></div>`;
                });
            } else {
                newsHTML += '<div style="color:#8b949e;">檢索中或無重大新聞...</div>';
            }

            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover || 'N/A'}</div></div>
                    <div class="p-box">浮動股數<div class="p-val" style="color:#58a6ff;">${d.FloatStr}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
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
        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 數據獲取模組 (非同步防卡死) ] ---
def fetch_news_bg(ticker, cell): #
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        news = []
        for item in root.findall('./channel/item')[:3]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            news.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': parser.parse(item.find('pubDate').text).strftime('%Y/%m/%d %H:%M')
            })
        cell["NewsList"] = news
    except: pass

def get_static(ticker): #
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker); i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000); p = i.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

# --- [ 3. 中央引擎：時區判定與 1000筆 滾動 ] ---
def scanner_engine():
    global MASTER_BRAIN
    count = 0
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            
            # 自動盤前/盤後網址切換 (美東時間 04:00~16:00 盤前/盤中，其餘盤後)
            tz = pytz.timezone('US/Eastern'); now_us = datetime.now(tz)
            url = "https://stockanalysis.com/markets/premarket/gainers/" if 4 <= now_us.hour < 16 else "https://stockanalysis.com/markets/after-hours/gainers/"
            
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
                if table:
                    temp_stocks, temp_snip, temp_drop, current_scan = [], [], [], []
                    
                    for tr in table.find_all('tr')[1:30]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        sym = tds[1].text.strip()
                        p_num = float(tds[4].text.replace('$','').replace(',',''))
                        
                        if 1.0 <= p_num <= 30.0:
                            f, a, prev = get_static(sym)
                            vol_raw = float(tds[5].text.replace('K','000').replace('M','000000').replace(',',''))
                            cell = MASTER_BRAIN["details"].get(sym, {"HOD": p_num, "NewsList": []})
                            
                            if p_num > cell["HOD"]: cell["HOD"] = p_num
                            gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                            rvol = vol_raw / a if a > 0 else 1.0
                            drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"

                            item = {
                                "Time": current_time, "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": tds[3].text.strip(), "ChangeAmt": f"${(p_num-prev):.2f}",
                                "Drop": f"{drop_p:.1f}%", "HOD": f"${cell['HOD']:.2f}",
                                "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%", "FloatStr": float_str,
                                "Turnover": f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%", "Type": "掃描更新"
                            }
                            
                            # Ross 核心邏輯判定
                            if gap_p > 3.0 and rvol > 5.0: 
                                item["Type"] = "🚀 爆發"; temp_snip.append(item)
                            if drop_p < -2.0: 
                                item["Type"] = "🔴 回落"; temp_drop.append(item)
                            
                            current_scan.append(item)
                            temp_stocks.append(item)
                            
                            # 背景獲取新聞 (不卡死主執行緒)
                            if not cell["NewsList"]: threading.Thread(target=fetch_news_bg, args=(sym, cell)).start()
                            MASTER_BRAIN["details"][sym] = {**cell, "Gap": item["Gap"], "Turnover": item["Turnover"], "RVOL": item["RVOL"], "FloatStr": float_str}

                    count += 1
                    # ★ 保留 1000 筆歷史紀錄
                    new_live = (current_scan + MASTER_BRAIN["live"])[:1000]
                    
                    MASTER_BRAIN.update({
                        "stocks": temp_stocks, "sniper": temp_snip, "drop": temp_drop,
                        "live": new_live, "last_update": current_time, "scan_count": count
                    })
            
            time.sleep(random.uniform(5.0, 10.0)) # 縮短至 5-10 秒提高即時性
        except: time.sleep(5)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
