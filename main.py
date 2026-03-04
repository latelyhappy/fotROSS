import os, time, threading, requests, random, warnings, yfinance as yf
from datetime import datetime
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__); CORS(app)

# ★ 強化版數據中樞：支援 1000 筆歷史紀錄
MASTER_BRAIN = {
    "sniper": [], "drop": [], "stocks": [], 
    "live": [], # 歷史滾動表格
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. UI 介面：滾動式歷史表格 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V168.0 - 歷史滾動版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 8px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 18px; font-weight: bold; color: #fff; margin-top: 4px; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="window" style="top:10px; left:10px; width:480px; height:320px;"><div class="title-bar">🚀 狙擊手 (當前掃描結果)</div><div class="content" id="sniper-list"></div></div>
    
    <div class="window" style="top:10px; left:500px; width:520px; height:600px;"><div class="title-bar">📡 即時報警 (歷史滾動 - 1000筆)</div><div class="content" id="live-list"></div></div>
    
    <div class="window" style="top:340px; left:10px; width:480px; height:320px;"><div class="title-bar">📉 下跌警報 (Drop > 2%)</div><div class="content" id="drop-list"></div></div>
    <div class="window" style="top:620px; left:500px; width:520px; height:360px;"><div class="title-bar">🏆 排行榜 (1-30 USD)</div><div class="content" id="rank-list"></div></div>
    <div class="window" style="top:670px; left:10px; width:480px; height:310px;"><div class="title-bar">📊 指標詳情與戰情</div><div class="content" id="detail-list">點擊代碼查看...</div></div>

    <div id="sys-status">🔄 數據鏈路同步中...</div>

    <script>
        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 更新: ' + data.last_update + ' | 次數: ' + data.scan_count;

                // 2. 狙擊手
                document.getElementById('sniper-list').innerHTML = data.sniper.map(s => `<div class="grid-row" onclick="loadDetail('${s.Code}')"><div>${s.Code}</div><div class="text-green">${s.Change}</div><div>${s.Price}</div></div>`).join('');
                
                // 4. 即時報警 (歷史表格)
                let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>漲跌%</div></div>';
                data.live.forEach(l => {
                    liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr;" onclick="loadDetail('${l.Code}')">
                        <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div>${l.Change}</div>
                    </div>`;
                });
                document.getElementById('live-list').innerHTML = liveH;

                // 5. 下跌警報
                document.getElementById('drop-list').innerHTML = data.drop.map(d => `<div class="grid-row" onclick="loadDetail('${d.Code}')"><div>${d.Code}</div><div class="text-red">${d.Drop}</div></div>`).join('');
                
                // 3. 排行榜
                document.getElementById('rank-list').innerHTML = data.stocks.map(s => `<div class="grid-row" onclick="loadDetail('${s.Code}')"><div>${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div></div>`).join('');
            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data?t=' + Date.now());
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;

            let newsHTML = '<h3 style="margin-top:15px; border-bottom:1px solid #30363d;">📰 即時情報翻譯</h3>';
            if (d.NewsList) {
                d.NewsList.forEach(n => {
                    newsHTML += `<div style="border-left:3px solid #f2cc60; padding-left:10px; margin-bottom:10px;"><span style="color:#8b949e; font-size:10px;">🕒 ${n.time}</span><br><a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none;">${n.title}</a></div>`;
                });
            }

            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover || '0%'}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap || '0%'}</div></div>
                    <div class="p-box">平均量比<div class="p-val">${d.RVOL}</div></div>
                </div>${newsHTML}`;
        }
        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 數據抓取與翻譯模組 ] ---
def fetch_news(ticker): #
    news_list = []
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        for item in root.findall('./channel/item')[:3]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            news_list.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': parser.parse(item.find('pubDate').text).strftime('%Y/%m/%d %H:%M')
            })
    except: pass
    return news_list

def get_static(ticker): #
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker); i = t.info
        f = i.get('floatShares', 1000000); a = i.get('averageVolume', 500000); p = i.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

# --- [ 3. 中央引擎：歷史滾動與分流 ] ---
def scanner_engine():
    global MASTER_BRAIN
    count = 0
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M:%S')
            r = requests.get("https://stockanalysis.com/markets/premarket/gainers/", headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
                if table:
                    temp_stocks, temp_snip, temp_drop, current_scan_items = [], [], [], []
                    for tr in table.find_all('tr')[1:25]:
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

                            item = {
                                "Time": current_time, "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": tds[3].text.strip(), "Drop": f"{drop_p:.1f}%",
                                "HOD": f"${cell['HOD']:.2f}", "RVOL": f"{rvol:.1f}x",
                                "Turnover": f"{(vol_raw/f*100):.1f}%", "Gap": f"{gap_p:.1f}%"
                            }
                            
                            if "+" in item["Change"] and float(item["Change"].replace('%','').replace('+','')) > 5.0:
                                temp_snip.append(item)
                            if drop_p < -2.0: temp_drop.append(item)
                            
                            current_scan_items.append(item)
                            temp_stocks.append(item)
                            
                            # 背景抓新聞
                            if not cell["NewsList"]: cell["NewsList"] = fetch_news(sym)
                            MASTER_BRAIN["details"][sym] = cell

                    count += 1
                    # ★ 歷史滾動：將新抓到的資料堆疊到前面，保留 1000 筆
                    new_live = (current_scan_items + MASTER_BRAIN["live"])[:1000]
                    
                    MASTER_BRAIN.update({
                        "stocks": temp_stocks, "sniper": temp_snip, "drop": temp_drop,
                        "live": new_live, "last_update": current_time, "scan_count": count
                    })
                    print(f"✅ 第 {count} 次掃描完成 - {current_time}")
            
            time.sleep(random.uniform(7.0, 13.0)) # 10s ±3s 頻率
        except: time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
