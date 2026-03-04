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
MASTER_BRAIN = {"sniper": [], "drop": [], "stocks": [], "details": {}}
stock_info_cache = {}
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 豪華版 UI 介面：全欄位顯示與視窗動態調整 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V164.6 - 10s 智能同步版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: grab; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 11px; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 6px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .row-sniper { background: rgba(63, 185, 80, 0.15) !important; border-left: 3px solid #3fb950; }
        .row-drop { background: rgba(255, 51, 102, 0.2) !important; border-left: 3px solid #ff3366; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 8px; border-radius: 6px; text-align: center; flex: 1; margin: 3px; }
        .p-val { font-size: 20px; font-weight: bold; color: #fff; font-family: 'Consolas'; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 11px; z-index: 1000; background: rgba(13,17,23,0.9); padding: 4px 8px; border-radius: 4px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <div class="window" id="win-sniper" style="top:10px; left:10px; width:540px; height:400px;"><div class="title-bar"><span>🚀 狙擊手進場區 (大量/跳空突破)</span></div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-drop" style="top:420px; left:10px; width:540px; height:400px;"><div class="title-bar"><span>📉 下跌避難區 (拋售/Ross警告)</span></div><div class="content" id="drop-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-gainers" style="top:10px; left:560px; width:800px; height:810px;"><div class="title-bar"><span>🏆 強勢掃描榜 (包含漲幅與浮動股數)</span></div><div class="content" id="gainer-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-pillars" style="top:10px; left:1370px; width:450px; height:810px;"><div class="title-bar"><span>📊 核心五檔與戰情新聞</span></div><div class="content" id="pillar-list"></div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 初始化數據中...</div>

    <script>
        async function update() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 同步更新成功 | ' + new Date().toLocaleTimeString();
                
                // 1. 狙擊區
                let sniperH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1.2fr;"><div>代碼</div><div>價格</div><div>漲幅$</div><div>量比</div><div>訊號</div></div>';
                data.sniper.forEach(s => {
                    sniperH += `<div class="grid-row row-sniper" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1.2fr;" onclick="loadDetail('${s.Code}')">
                        <div style="color:#58a6ff; font-weight:bold;">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.RVOL}</div><div style="font-weight:bold;">${s.Type}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = sniperH;

                // 2. 下跌區
                let dropH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1.2fr;"><div>代碼</div><div>價格</div><div>回落%</div><div>換手</div><div>訊號</div></div>';
                data.drop.forEach(d => {
                    dropH += `<div class="grid-row row-drop" style="grid-template-columns: 0.8fr 0.8fr 0.8fr 0.8fr 1.2fr;" onclick="loadDetail('${d.Code}')">
                        <div style="color:#58a6ff; font-weight:bold;">${d.Code}</div><div>${d.Price}</div><div class="text-red">${d.Drop}</div><div>${d.Turnover}</div><div style="font-weight:bold;">${d.Type}</div>
                    </div>`;
                });
                document.getElementById('drop-list').innerHTML = dropH;

                // 3. 強勢榜 (包含漲幅% / 漲幅$ / 浮動股數) 
                let gainerH = '<div class="grid-row grid-th" style="grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr 1fr;"><div>代碼</div><div>價格</div><div>漲幅%</div><div>漲幅$</div><div>浮動股數</div><div>量比</div></div>';
                data.stocks.forEach(s => {
                    gainerH += `<div class="grid-row" style="grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr 1fr;" onclick="loadDetail('${s.Code}')">
                        <div style="color:#58a6ff; font-weight:bold;">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.FloatStr}</div><div>${s.RVOL}</div>
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

            let newsH = "";
            d.NewsList.forEach(n => {
                newsH += `<div style="border-left:3px solid #f2cc60; padding-left:10px; margin-bottom:10px;"><span style="color:#8b949e; font-size:10px;">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none; font-weight:bold; font-size:12px;">${n.title}</a></div>`;
            });

            document.getElementById('pillar-list').innerHTML = `
                <div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:15px;">
                    <div class="p-box">最高價 (HOD)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover}</div></div>
                    <div class="p-box">回落幅度<div class="p-val" style="color:#f85149;">${d.Drop}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap}</div></div>
                    <div class="p-box">浮動股數<div class="p-val" style="font-size:16px;">${d.FloatStr}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                </div>
                <h3 style="border-bottom:1px solid #30363d; padding-bottom:5px;">📰 即時情報翻譯</h3>
                ${newsH || '<p style="color:#8b949e">暫無相關新聞</p>'}`;
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
        setInterval(update, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心運算引擎 ] ---
def format_volume_km(vol): #
    if vol <= 0: return "N/A"
    if vol >= 1e6: return f"{vol/1e6:.1f}M"
    if vol >= 1e3: return f"{vol/1e3:.0f}K"
    return str(int(vol))

def parse_vol_str(v): #
    v = str(v).upper().replace(',','').replace(' ','')
    if 'M' in v: return float(v.replace('M',''))*1e6
    if 'K' in v: return float(v.replace('K',''))*1e3
    try: return float(v)
    except: return 0

def fetch_advanced_data(ticker): #
    f_shares, a_vol, prev_close = 0, 1, 0
    try:
        t = yf.Ticker(ticker); info = t.info
        f_shares = info.get('floatShares', 0) or info.get('sharesOutstanding', 1)
        a_vol = info.get('averageVolume', 1)
        prev_close = info.get('previousClose', 0)
    except: pass
    return f_shares, a_vol, prev_close

def fetch_news(ticker): #
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

# --- [ 3. 掃描引擎：核心 10秒 邏輯 ] ---
def scanner_job():
    global MASTER_BRAIN
    while True:
        try:
            url = "https://stockanalysis.com/markets/premarket/gainers/"
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
            
            if table:
                temp_stocks, sniper_list, drop_list = [], [], []
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
                        
                        change_amt = p_num - prev if prev > 0 else 0
                        gap_pct = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol_val = vol_n / a if a > 0 else 1.0
                        drop_pct = ((p_num - cell['HOD_num']) / cell['HOD_num'] * 100) if cell['HOD_num'] > 0 else 0

                        item = {
                            "Code": sym, "Price": f"${p_num:.2f}", "Change": tds[3].text,
                            "ChangeAmt": f"+${change_amt:.2f}" if change_amt > 0 else f"-${abs(change_amt):.2f}",
                            "Volume": format_volume_km(vol_n), "RVOL": f"{rvol_val:.1f}x",
                            "Gap": f"{gap_pct:.1f}%", "Turnover": f"{(vol_n/f*100):.1f}%" if f > 0 else "0%",
                            "Drop": f"{drop_pct:.1f}%", "HOD": f"${cell['HOD_num']:.2f}",
                            "FloatStr": format_volume_km(f), "Type": "🆕NEW",
                            "NewsList": fetch_news(sym) if sym not in MASTER_BRAIN["details"] else MASTER_BRAIN["details"][sym]["NewsList"]
                        }

                        # 狙擊判定邏輯 (大量且上漲)
                        if gap_pct > 3.0 and rvol_val > 5.0:
                            item["Type"] = "🚀 動能狙擊"
                            sniper_list.append(item)
                        elif rvol_val > 10.0:
                            item["Type"] = "💥 極端爆量"
                            sniper_list.append(item)

                        # 下跌判定邏輯 (大量拋售/Ross警告)
                        if drop_pct < -2.0:
                            item["Type"] = "🔴 Ross 下跌警告"
                            drop_list.append(item)
                        elif change_amt < 0 and rvol_val > 2.0:
                            item["Type"] = "⚠️ 大量拋售"
                            drop_list.append(item)

                        temp_stocks.append(item)
                        MASTER_BRAIN["details"][sym] = item
                
                MASTER_BRAIN["stocks"] = temp_stocks
                MASTER_BRAIN["sniper"] = sniper_list
                MASTER_BRAIN["drop"] = drop_list
            
            # --- ★ 核心頻率控制：10秒 左右 正負3秒 ---
            wait_time = random.uniform(7.0, 13.0) 
            time.sleep(wait_time)
        except Exception as e: 
            time.sleep(10)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
