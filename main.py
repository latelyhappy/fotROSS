import os, time, threading, requests, random, warnings, yfinance as yf
from datetime import datetime, timedelta
import pytz
import xml.etree.ElementTree as ET
from deep_translator import GoogleTranslator
from dateutil import parser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__)
CORS(app)

# ★ 終極 7 區塊數據中樞 
MASTER_BRAIN = {
    "gappers": [], "high_vol": [], "ipos": [],       
    "hod": [], "surge": [], "washouts": [], "halts": [], 
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極 UI 介面：全中文與 ROSS 實戰配色 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V214.0 - 實戰配色量化版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; transform-origin: top left; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 5px 15px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        
        /* ★ 區塊標題統一暗藍色背景 + 純白體字 ★ */
        .title-bar { 
            background: #0d1f3d !important; 
            color: #ffffff !important; 
            padding: 5px 10px; font-size: 11px; font-weight: bold; cursor: grab; 
            display: flex; justify-content: space-between; align-items: center; 
            border-bottom: 1px solid #30363d; 
        }
        /* 隱藏原本的各色標題背景，統一交由 title-bar 處理 */
        .bg-blue, .bg-green, .bg-gold, .bg-red, .bg-purple, .bg-dark { background: transparent; }
        
        .content { flex: 1; padding: 4px; overflow-y: auto; font-size: 10.5px; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100;}
        
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; transition: background 0.1s; }
        .grid-row:hover { background: #161b22; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; padding-bottom: 5px; }
        
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #ff7b72; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .text-gold { color: #f2cc60; font-weight: bold; } 
        
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 6px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 14px; font-weight: bold; color: #fff; margin-top: 2px; font-family: 'Consolas'; }
        
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; z-index: 1000; }
        #zoom-controls { position: fixed; top: 10px; right: 10px; background: rgba(13,17,23,0.9); padding: 5px; border: 1px solid #30363d; border-radius: 4px; z-index: 2000; }
        #zoom-controls button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; cursor: pointer; padding: 4px 8px; border-radius: 3px; font-weight: bold; }
        #zoom-controls button:hover { background: #30363d; }
        
        /* ★ 實戰閃爍動畫 (區分多空顏色) ★ */
        @keyframes flashGreen { 0% { background-color: rgba(63, 185, 80, 0.4); } 100% { background-color: transparent; } }
        @keyframes flashRed { 0% { background-color: rgba(255, 123, 114, 0.4); } 100% { background-color: transparent; } }
        
        .flash-green { animation: flashGreen 1.5s ease-out; border-left: 2px solid #3fb950; }
        .flash-red { animation: flashRed 1.5s ease-out; border-left: 2px solid #ff7b72; }

        .row-news-today { background-color: rgba(171, 71, 188, 0.25); border-left: 2px solid #d500f9; }
        .row-news-today:hover { background-color: rgba(171, 71, 188, 0.4); }

        .news-header { margin-top:5px; border-bottom:1px solid #30363d; padding-bottom:3px; font-size: 12px; color: #fff; }
        .news-item-container { border-left: 2px solid #8b949e; padding-left: 6px; margin-bottom: 8px; line-height: 1.3; }
        .news-date-tag { font-size: 10px; font-weight: bold; margin-bottom: 2px; display: inline-block; }
        .news-title-link { font-size: 12px; font-weight: bold; color: #c9d1d9; text-decoration: none; display: inline-block; }
        .news-title-link:hover { color: #58a6ff; text-decoration: underline; }
        
        .pause-btn { background: #f85149; border: 1px solid #fff; color: white; border-radius: 3px; cursor: pointer; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: 10px;}
    </style>
</head>
<body>
    <div id="zoom-controls">
        <button onclick="changeZoom(0.1)">🔍 +</button>
        <button onclick="changeZoom(-0.1)">🔍 -</button>
        <button onclick="resetZoom()">🔄 重置</button>
    </div>

    <div class="window" id="win-gap" style="top:10px; left:10px; width:400px; height:280px;"><div class="title-bar bg-blue">1. 盤前跳空漲幅榜 (Top Gappers)</div><div class="content" id="gap-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-vol" style="top:300px; left:10px; width:400px; height:280px;"><div class="title-bar bg-gold">3. 異常爆量上漲 (High Volume)</div><div class="content" id="vol-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-ipo" style="top:590px; left:10px; width:400px; height:280px;"><div class="title-bar bg-purple">7. 極低流通與新股 (Low Float / IPOs)</div><div class="content" id="ipo-list"></div><div class="resize-handle"></div></div>

    <div class="window" id="win-hod" style="top:10px; left:420px; width:500px; height:430px;"><div class="title-bar bg-green">2. 突破今日新高 (HOD Momentum) <button id="pause-btn" class="pause-btn" onclick="togglePause(event)">⏸️ 暫停滾動</button></div><div class="content" id="hod-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-surge" style="top:450px; left:420px; width:500px; height:420px;"><div class="title-bar bg-green">4. 短線急拉連擊 (Surging Up)</div><div class="content" id="surge-list"></div><div class="resize-handle"></div></div>

    <div class="window" id="win-wash" style="top:10px; left:930px; width:440px; height:280px;"><div class="title-bar bg-red">6. 高檔大幅回落 (Reversals / Drops)</div><div class="content" id="wash-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-halt" style="top:300px; left:930px; width:440px; height:280px;"><div class="title-bar bg-red">5. 極端波動準熔斷 (Extreme / Halts)</div><div class="content" id="halt-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-detail" style="top:590px; left:930px; width:440px; height:280px;"><div class="title-bar bg-dark">📊 戰情與新聞分析 (單擊代碼載入)</div><div class="content" id="detail-list"><div style="padding:10px; color:#8b949e;">請點擊任何股票代碼以載入戰情報告...</div></div><div class="resize-handle"></div></div>

    <div id="sys-status">🔄 掃描引擎連線中...</div>

    <script>
        let currentZoom = parseFloat(localStorage.getItem('ross_zoom')) || 1.0;
        document.body.style.zoom = currentZoom; 

        function saveLayout() {
            const layout = {};
            document.querySelectorAll('.window').forEach(win => {
                layout[win.id] = { top: win.style.top, left: win.style.left, width: win.style.width, height: win.style.height };
            });
            localStorage.setItem('ross_layout', JSON.stringify(layout));
        }

        function changeZoom(delta) {
            currentZoom = Math.max(0.5, Math.min(2.0, currentZoom + delta));
            document.body.style.zoom = currentZoom;
            localStorage.setItem('ross_zoom', currentZoom);
        }

        function resetZoom() {
            currentZoom = 1.0;
            document.body.style.zoom = currentZoom;
            localStorage.removeItem('ross_zoom');
            localStorage.removeItem('ross_layout');
            location.reload(); 
        }

        window.addEventListener('DOMContentLoaded', () => {
            const saved = JSON.parse(localStorage.getItem('ross_layout'));
            if(saved) {
                for(const id in saved) {
                    const win = document.getElementById(id);
                    if(win && saved[id]) {
                        win.style.top = saved[id].top; win.style.left = saved[id].left;
                        win.style.width = saved[id].width; win.style.height = saved[id].height;
                    }
                }
            }
        });

        document.querySelectorAll('.window').forEach(win => {
            const title = win.querySelector('.title-bar');
            const handle = win.querySelector('.resize-handle');
            title.onmousedown = (e) => {
                if(e.target.tagName === 'BUTTON') return; // 避免拖動時觸發按鈕
                let startX = e.clientX, startY = e.clientY;
                let startTop = win.offsetTop, startLeft = win.offsetLeft;
                document.onmousemove = (ev) => {
                    let dx = (ev.clientX - startX) / currentZoom;
                    let dy = (ev.clientY - startY) / currentZoom;
                    win.style.top = (startTop + dy) + "px";
                    win.style.left = (startLeft + dx) + "px";
                };
                document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; saveLayout(); };
            };
            handle.onmousedown = (e) => {
                let startW = win.offsetWidth, startH = win.offsetHeight;
                let startX = e.clientX, startY = e.clientY;
                document.onmousemove = (ev) => {
                    let dx = (ev.clientX - startX) / currentZoom;
                    let dy = (ev.clientY - startY) / currentZoom;
                    win.style.width = (startW + dx) + 'px';
                    win.style.height = (startH + dy) + 'px';
                };
                document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; saveLayout(); };
            };
        });

        let isLivePaused = false;
        function togglePause(e) {
            e.stopPropagation();
            isLivePaused = !isLivePaused;
            const btn = document.getElementById('pause-btn');
            if(isLivePaused) {
                btn.innerText = '▶️ 恢復滾動';
                btn.style.background = '#137333';
            } else {
                btn.innerText = '⏸️ 暫停滾動';
                btn.style.background = '#a50e0e';
            }
        }

        function openTW(sym) { window.open(`https://tw.tradingview.com/chart/?symbol=${sym}`, '_blank'); }

        function formatFloat(floatStr) {
            let floatVal = parseFloat(floatStr.replace('M','').replace('K',''));
            return (floatStr.includes('M') && floatVal < 20.0 || floatStr.includes('K')) ? "text-gold" : "";
        }

        function checkTodayNews(sym, detailsData) {
            if(detailsData[sym] && detailsData[sym].NewsList) {
                return detailsData[sym].NewsList.some(n => n.category === 'today');
            }
            return false;
        }

        function buildTable(dataArray, detailsData, cols, colTemplate, showTime=false, flashClass="flash-green") {
            let html = `<div class="grid-row grid-th" style="grid-template-columns: ${colTemplate};">`;
            cols.forEach(c => html += `<div>${c}</div>`);
            html += '</div>';

            dataArray.forEach(item => {
                let rowClass = "grid-row";
                if (checkTodayNews(item.Code, detailsData)) rowClass += " row-news-today";
                if (showTime && item.Time === detailsData.last_update) rowClass += " " + flashClass; // 套用指定閃爍顏色

                html += `<div class="${rowClass}" style="grid-template-columns: ${colTemplate};" onclick="loadDetail('${item.Code}')" ondblclick="openTW('${item.Code}')">`;
                cols.forEach(c => {
                    if(c === '時間') html += `<div>${item.Time}</div>`;
                    else if(c === '代碼') html += `<div class="text-blue">${item.Code}</div>`;
                    else if(c === '價格') html += `<div>${item.Price}</div>`;
                    else if(c === '漲幅%') html += `<div class="text-green">${item.Change}</div>`;
                    else if(c === '跳空%') html += `<div class="text-green">${item.Gap}</div>`;
                    else if(c === '交易量') html += `<div class="text-gold">${item.Volume}</div>`; 
                    else if(c === '浮動股') html += `<div class="${formatFloat(item.FloatStr)}">${item.FloatStr}</div>`;
                    else if(c === '量比') html += `<div class="text-gold">${item.RVOL}</div>`;
                    else if(c === '回落%') html += `<div class="text-red">${item.Drop}</div>`;
                    else if(c === '連擊') html += `<div class="text-red">${item.Streak}</div>`;
                });
                html += '</div>';
            });
            return html;
        }

        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                data.details.last_update = data.last_update;
                document.getElementById('sys-status').innerText = '✅ 更新時間(TW): ' + data.last_update + ' | 總掃描: ' + data.scan_count;

                // 1. Top Gappers
                document.getElementById('gap-list').innerHTML = buildTable(
                    data.gappers, data.details, 
                    ['代碼','價格','跳空%','交易量','浮動股','量比'], '0.8fr 1fr 1fr 1.2fr 1fr 0.8fr'
                );
                // 2. High Volume
                document.getElementById('vol-list').innerHTML = buildTable(
                    data.high_vol, data.details, 
                    ['代碼','價格','漲幅%','量比','交易量','浮動股'], '0.8fr 1fr 1fr 1fr 1.2fr 1fr'
                );
                // 3. Low Float IPOs
                document.getElementById('ipo-list').innerHTML = buildTable(
                    data.ipos, data.details, 
                    ['代碼','價格','浮動股','交易量','漲幅%','量比'], '0.8fr 1fr 1fr 1.2fr 1fr 0.8fr'
                );
                
                // 4. HOD Momentum (綠色閃爍)
                if (!isLivePaused) {
                    document.getElementById('hod-list').innerHTML = buildTable(
                        data.hod, data.details, 
                        ['時間','代碼','價格','漲幅%','交易量','量比','浮動股'], '1fr 0.8fr 1fr 1fr 1.2fr 0.8fr 1fr', true, 'flash-green'
                    );
                }

                // 5. Surging Up (綠色閃爍)
                document.getElementById('surge-list').innerHTML = buildTable(
                    data.surge, data.details, 
                    ['時間','代碼','價格','連擊','交易量','量比'], '1fr 0.8fr 1fr 0.8fr 1.2fr 0.8fr', true, 'flash-green'
                );

                // 6. Reversals / Drops (紅色閃爍)
                document.getElementById('wash-list').innerHTML = buildTable(
                    data.washouts, data.details, 
                    ['時間','代碼','價格','回落%','交易量','量比'], '1fr 0.8fr 1fr 1fr 1.2fr 0.8fr', true, 'flash-red'
                );
                
                // 7. Halts / Extreme (紅色閃爍)
                document.getElementById('halt-list').innerHTML = buildTable(
                    data.halts, data.details, 
                    ['時間','代碼','價格','跳空%','交易量','浮動股'], '1fr 0.8fr 1fr 1fr 1.2fr 1fr', true, 'flash-red'
                );

            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data?t=' + Date.now());
            const data = await res.json();
            const d = data.details[sym];
            if(!d) return;

            let newsHTML = '<h3 class="news-header">📰 48H 催化劑情報 (台灣時間)</h3>';
            if (d.NewsList && d.NewsList.length > 0) {
                d.NewsList.forEach(n => {
                    if(n.link === '#') {
                        newsHTML += `<div style="color:#8b949e; font-size:10px;">${n.title}</div>`;
                    } else {
                        let borderColor = n.category === "today" ? "#d500f9" : (n.category === "yesterday" ? "#58a6ff" : "#8b949e");
                        let dateTag = n.category === "today" ? "🔥 本日" : (n.category === "yesterday" ? "📆 昨日" : "📅");
                        newsHTML += `
                        <div class="news-item-container" style="border-left-color: ${borderColor};">
                            <span class="news-date-tag" style="color:${borderColor};">${dateTag} ${n.time}</span><br>
                            <a href="${n.link}" target="_blank" class="news-title-link">${n.title}</a>
                        </div>`;
                    }
                });
            } else { newsHTML += '<div style="color:#8b949e; font-size:10px;">檢索中...</div>'; }

            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:4px; margin-bottom:5px;">
                    <div class="p-box">今日最高<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">量比<div class="p-val">${d.RVOL}</div></div>
                    <div class="p-box">浮動股<div class="p-val" style="color:#58a6ff;">${d.FloatStr}</div></div>
                </div>${newsHTML}`;
        }

        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 新聞與靜態數據模組 ] ---
def fetch_news_bg(ticker, cell):
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:2d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, headers=STEALTH_HEADERS, timeout=5)
        root = ET.fromstring(r.content)
        tz_tw = pytz.timezone('Asia/Taipei')
        now_tw = datetime.now(tz_tw)
        news = []
        for item in root.findall('./channel/item')[:3]: 
            title_en = item.find('title').text.rsplit(" - ", 1)[0]
            pub_dt_tw = parser.parse(item.find('pubDate').text).astimezone(tz_tw)
            
            if pub_dt_tw.date() == now_tw.date(): cat = "today"
            elif pub_dt_tw.date() == (now_tw.date() - timedelta(days=1)): cat = "yesterday"
            else: cat = "older"
                
            news.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': pub_dt_tw.strftime('%m/%d %H:%M'),
                'category': cat
            })
        cell["NewsList"] = news if news else [{"title": "無重大新聞", "link": "#", "time": "", "category": "none"}]
    except:
        cell["NewsList"] = [{"title": "新聞連線異常", "link": "#", "time": "", "category": "none"}]

def get_static(ticker):
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker)
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000)
        p = i.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

def format_vol_km(v_float):
    if v_float >= 1_000_000:
        return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000:
        return f"{v_float/1_000:.1f}K"
    else:
        return f"{int(v_float)}"

def parse_vol(v_str):
    v_str = v_str.upper().replace(',', '').strip()
    try:
        if 'M' in v_str: return float(v_str.replace('M', '')) * 1e6
        if 'K' in v_str: return float(v_str.replace('K', '')) * 1e3
        return float(v_str)
    except: return 0.0

# ★ 新增：即時抓取 NASDAQ 官方熔斷 (Trade Halts) 數據 ★
def fetch_official_halts():
    global MASTER_BRAIN
    try:
        # 這是 NASDAQ 官方提供的免費即時熔斷 XML 資料流
        url = "http://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
        r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
        
        # 移除 XML 的 Namespace 以便輕鬆解析
        xml_data = r.text.replace('ndaq:', '') 
        root = ET.fromstring(xml_data)
        
        tz_tw = pytz.timezone('Asia/Taipei')
        tz_us = pytz.timezone('US/Eastern')
        now_us = datetime.now(tz_us)
        today_us_str = now_us.strftime("%m/%d/%Y") # NASDAQ 格式為 MM/DD/YYYY
        
        new_halts = []
        # 已存在畫面上的熔斷代碼，避免重複添加
        existing_halt_syms = [h["Code"] for h in MASTER_BRAIN["halts"]]
        
        for item in root.findall('./channel/item'):
            halt_date = item.find('HaltDate')
            # 只抓取「今天」發生的熔斷
            if halt_date is None or halt_date.text != today_us_str:
                continue
                
            title = item.find('title')
            if title is None: continue
            sym = title.text.replace('Symbol: ', '').strip()
            
            # 如果已經在畫面上，就跳過
            if sym in existing_halt_syms:
                continue
                
            halt_time_us = item.find('HaltTime').text # 例如: 09:35:12
            
            # 將美國東岸時間精準轉換為台灣時間
            try:
                dt_us = datetime.strptime(f"{today_us_str} {halt_time_us}", "%m/%d/%Y %H:%M:%S")
                dt_us = tz_us.localize(dt_us)
                time_tw_str = dt_us.astimezone(tz_tw).strftime('%H:%M:%S')
            except:
                time_tw_str = halt_time_us # 轉換失敗則顯示原時間
                
            # 抓取該檔股票的基礎資料以供 UI 顯示
            f, a, prev = get_static(sym)
            try:
                # 這裡簡單使用 yf 抓取當下最新價格
                t = yf.Ticker(sym)
                price = t.info.get('regularMarketPrice', prev)
                vol = t.info.get('regularMarketVolume', 0)
                if price is None: price = prev
                if vol is None: vol = 0
            except:
                price = prev; vol = 0
                
            gap_p = ((price - prev) / prev * 100) if prev > 0 else 0
            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
            
            halt_item = {
                "Time": time_tw_str, "Code": sym, "Price": f"${price:.2f}",
                "Change": f"{gap_p:.2f}%", 
                "Volume": format_vol_km(vol), # 量化成交量
                "RVOL": "N/A", "Gap": f"{gap_p:.2f}%", "Drop": "0.0%",
                "FloatStr": float_str, "Turnover": "0%", 
                "Streak": "x1", "gap_num": gap_p, "rvol_num": 0, "f_num": f
            }
            new_halts.append(halt_item)
            
        # 若有新熔斷股票，將其「插頂」加入歷史清單
        if new_halts:
            # 依照時間順序反轉（最新的在最上面）
            new_halts.reverse()
            MASTER_BRAIN["halts"] = (new_halts + MASTER_BRAIN["halts"])[:1000]
            
    except Exception as e:
        pass # 背景靜默錯誤，不影響主系統運作

# --- [ 3. 中央引擎：7 路智能分流 ] ---
def scanner_engine():
    global MASTER_BRAIN
    count = 0
    print("🔥 啟動七星陣列掃描引擎 (全中文實戰配色版)...")
    
    tz_tw = pytz.timezone('Asia/Taipei')
    tz_us = pytz.timezone('US/Eastern')
    
    while True:
        try:
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            now_us = datetime.now(tz_us)
            
            if 4 <= now_us.hour < 9 or (now_us.hour == 9 and now_us.minute < 30):
                url = "https://stockanalysis.com/markets/premarket/gainers/"
            elif 9 <= now_us.hour < 16:
                url = "https://stockanalysis.com/markets/gainers/"
            else:
                url = "https://stockanalysis.com/markets/after-hours/"

            r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            if r.status_code == 404:
                url = "https://stockanalysis.com/markets/premarket/gainers/"
                r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                table = soup.find('table')
                if table:
                    # ★ 修改：移除了 c_halt 的定義與假熔斷邏輯
                    t_all, c_hod, c_surge, c_wash = [], [], [], []
                    
                    for tr in table.find_all('tr')[1:40]: 
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        
                        sym = tds[1].text.strip()
                        try: p_num = float(tds[4].text.replace('$','').replace(',',''))
                        except: continue
                        
                        if 1.0 <= p_num <= 30.0:
                            f, a, prev = get_static(sym)
                            
                            # 讀取並量化轉換成交量
                            raw_vol_str = tds[5].text.strip()
                            vol_raw = parse_vol(raw_vol_str)
                            formatted_volume = format_vol_km(vol_raw)
                            
                            cell = MASTER_BRAIN["details"].get(sym, {"HOD": p_num, "NewsList": [], "streak": 0, "last_act": ""})
                            is_hod_break = False
                            
                            if p_num > cell["HOD"]: 
                                cell["HOD"] = p_num
                                cell["streak"] += 1
                                is_hod_break = True
                            
                            gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                            rvol = vol_raw / a if a > 0 else 1.0
                            drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0
                            
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            turnover_str = f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%"
                            
                            item = {
                                "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": tds[3].text.strip(), 
                                "Volume": formatted_volume, 
                                "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%", "Drop": f"{drop_p:.1f}%",
                                "FloatStr": float_str, "Turnover": turnover_str, 
                                "Streak": f"x{cell['streak']}", "gap_num": gap_p, "rvol_num": rvol, "f_num": f
                            }
                            t_all.append(item)

                            # 2. 高檔大幅回落
                            if drop_p < -2.0 and cell["last_act"] != f"drop_{drop_p:.0f}":
                                c_wash.append(item)
                                cell["last_act"] = f"drop_{drop_p:.0f}"

                            # 3. 突破新高 & 連擊
                            if is_hod_break and rvol > 1.2:
                                c_hod.append(item)
                                if cell["streak"] >= 2: c_surge.append(item)
                                cell["last_act"] = "hod"

                            if not cell["NewsList"]: 
                                threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                                
                            cell["HOD_str"] = f"${cell['HOD']:.2f}"
                            cell["RVOL"] = item["RVOL"]
                            cell["FloatStr"] = float_str
                            MASTER_BRAIN["details"][sym] = cell

                    count += 1
                    
                    gappers = sorted(t_all, key=lambda x: x["gap_num"], reverse=True)[:20]
                    high_vol = sorted(t_all, key=lambda x: x["rvol_num"], reverse=True)[:20]
                    ipos = sorted([x for x in t_all if x["f_num"] < 10000000], key=lambda x: x["gap_num"], reverse=True)[:20]
                    
                    # ★ 修改：在此處移除了 "halts" 陣列的更新，交由 fetch_official_halts 專職處理
                    MASTER_BRAIN.update({
                        "gappers": gappers, "high_vol": high_vol, "ipos": ipos,
                        "hod": (c_hod + MASTER_BRAIN["hod"])[:1000],
                        "surge": (c_surge + MASTER_BRAIN["surge"])[:1000],
                        "washouts": (c_wash + MASTER_BRAIN["washouts"])[:1000],
                        "last_update": current_time_tw, "scan_count": count
                    })
            
            # ★ 呼叫：每次迴圈同步抓取 NASDAQ 官方的真實熔斷資訊 ★
            fetch_official_halts()
            
            time.sleep(random.uniform(5.0, 10.0))
        except: time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
