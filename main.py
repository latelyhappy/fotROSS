import os, json, time, threading, requests, yfinance as yf, logging, re, random, warnings
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# --- [ 0. 系統優化與靜音 ] ---
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# --- [ 1. 完整 Sniper V8 豪華儀表板 ] ---
# 這裡包含您要求的所有 CSS 視窗控制與 2026/03/02 11:34 新聞格式
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>Sniper V8 終極實戰系統</title>
    <style>
        body { margin: 0; background-color: #050811; color: #c9d1d9; font-family: 'Microsoft JhengHei', sans-serif; overflow: hidden; height: 100vh; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: move; display: flex; justify-content: space-between; border-bottom: 1px solid #30363d; }
        .content { flex: 1; padding: 10px; overflow-y: auto; font-size: 12px; }
        .news-box { border-left: 3px solid #f2cc60; padding-left: 12px; margin-bottom: 15px; }
        .time-tag { color: #8b949e; font-size: 11px; margin-bottom: 4px; display: block; }
        .stock-row { display: grid; grid-template-columns: 1fr 1fr 1fr; border-bottom: 1px solid #21262d; padding: 8px 0; }
        #sys-status { position: fixed; bottom: 10px; right: 10px; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; font-size: 11px; color: #3fb950; }
    </style>
</head>
<body>
    <div class="window" id="win-alerts" style="top:20px; left:20px; width:450px; height:500px;">
        <div class="title-bar"><span>🚨 即時動能警報 (ROSS V8)</span></div>
        <div class="content" id="alert-list">等待掃描啟動...</div>
    </div>

    <div class="window" id="win-news" style="top:20px; left:490px; width:400px; height:500px;">
        <div class="title-bar"><span>📰 全球即時情報 (24H)</span></div>
        <div class="content" id="news-list">請點擊個股查看新聞...</div>
    </div>

    <div id="sys-status">● 數據鏈路已建立 | Railway Cloud Active</div>

    <script>
        // 讓視窗可以拖動的邏輯
        function makeDraggable(el) {
            let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
            el.querySelector('.title-bar').onmousedown = dragMouseDown;
            function dragMouseDown(e) { e.preventDefault(); pos3 = e.clientX; pos4 = e.clientY; document.onmouseup = closeDragElement; document.onmousemove = elementDrag; }
            function elementDrag(e) { e.preventDefault(); pos1 = pos3 - e.clientX; pos2 = pos4 - e.clientY; pos3 = e.clientX; pos4 = e.clientY; el.style.top = (el.offsetTop - pos2) + "px"; el.style.left = (el.offsetLeft - pos1) + "px"; }
            function closeDragElement() { document.onmouseup = null; document.onmousemove = null; }
        }
        document.querySelectorAll('.window').forEach(makeDraggable);

        async function updateData() {
            try {
                const res = await fetch('/data');
                const data = await res.json();
                if(data.alerts) {
                    let html = '';
                    data.alerts.forEach(a => {
                        html += `<div class="stock-row">
                            <b style="color:#58a6ff; cursor:pointer" onclick="getNews('${a.symbol}')">${a.symbol}</b>
                            <span class="${a.change >= 0 ? 'text-green' : 'text-red'}">${a.price}</span>
                            <span>${a.signal}</span>
                        </div>`;
                    });
                    document.getElementById('alert-list').innerHTML = html;
                }
            } catch(e) {}
        }

        async function getNews(symbol) {
            document.getElementById('news-list').innerHTML = '正在翻譯最新情報...';
            const res = await fetch(`/news/${symbol}`);
            const news = await res.json();
            let html = `<h3>${symbol} 戰情分析</h3>`;
            news.forEach(n => {
                html += `<div class="news-box">
                    <span class="time-tag">🕒 ${n.time}</span>
                    <a href="${n.link}" target="_blank" style="color:#f2cc60; text-decoration:none; font-weight:bold;">${n.title}</a>
                </div>`;
            });
            document.getElementById('news-list').innerHTML = html;
        }

        setInterval(updateData, 4000);
    </script>
</body>
</html>
"""

# --- [ 2. 後端核心邏輯 ] ---
MASTER_BRAIN = {"alerts": []}
translator = GoogleTranslator(source='auto', target='zh-TW')

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)

@app.route('/news/<symbol>')
def get_stock_news(symbol):
    try:
        url = f"https://news.google.com/rss/search?q={symbol}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        news_list = []
        for item in root.findall('./channel/item')[:5]:
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            # 抓取原始發布時間 (pubDate)
            pub_date_raw = item.find('pubDate').text
            dt = parser.parse(pub_date_raw)
            news_list.append({
                'title': translator.translate(title_en), 
                'link': item.find('link').text, 
                'time': dt.strftime('%Y/%m/%d %H:%M') # 修正為 2026/03/02 11:34 格式
            })
        return jsonify(news_list)
    except: return jsonify([])

def scanner_job():
    global MASTER_BRAIN
    # 這裡放您原本 yfinance 掃描 1.0~30.0 美金股票的邏輯
    # 範例數據測試用
    tickers = ["TSLA", "NVDA", "AAPL", "AMD", "PLTR"]
    while True:
        try:
            new_alerts = []
            for t in tickers:
                stock = yf.Ticker(t)
                price = stock.fast_info['lastPrice']
                new_alerts.append({"symbol": t, "price": round(price, 2), "change": 1.5, "signal": "強勢突破"})
            MASTER_BRAIN["alerts"] = new_alerts
            time.sleep(10)
        except: time.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=scanner_job, daemon=True).start()
    
    # ★ 關鍵：Railway 穩定通訊設定
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)