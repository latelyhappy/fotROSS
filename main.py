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
app = Flask(__name__); CORS(app)

# ★ 數據中樞 (靜默純淨版)
MASTER_BRAIN = {
    "sniper": [], "stocks": [], "live": [],
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')
STEALTH_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- [ 1. 終極 UI 介面：三欄純淨排版 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V208.0 - 精準同步版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; transform-origin: top left; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 10px 30px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #1E3A8A; color: white; padding: 6px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; align-items: center; }
        .content { flex: 1; padding: 8px; overflow-y: auto; font-size: 11px; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100;}
        
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 6px 0; cursor: pointer; transition: background 0.1s; }
        .grid-row:hover { background: #161b22; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; padding-bottom: 8px; }
        
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #ff7b72; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .text-gold { color: #f2cc60; font-weight: bold; } 
        
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 8px; border-radius: 4px; text-align: center; }
        .p-val { font-size: 18px; font-weight: bold; color: #fff; margin-top: 4px; font-family: 'Consolas'; }
        
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; z-index: 1000; }
        #zoom-controls { position: fixed; top: 10px; right: 10px; background: rgba(13,17,23,0.9); padding: 5px; border: 1px solid #30363d; border-radius: 4px; z-index: 2000; }
        #zoom-controls button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; cursor: pointer; padding: 4px 8px; border-radius: 3px; font-weight: bold; }
        #zoom-controls button:hover { background: #30363d; }
        
        @keyframes flash { 0% { background-color: rgba(63, 185, 80, 0.5); } 100% { background-color: transparent; } }
        .flash-row { animation: flash 1.5s ease-out; border-left: 3px solid #3fb950; }

        .news-header { margin-top:10px; border-bottom:1px solid #30363d; padding-bottom:5px; font-size: 14px; color: #fff; }
        .news-item-container { border-left: 3px solid #8b949e; padding-left: 10px; margin-bottom: 12px; line-height: 1.4; }
        .news-date-tag { font-size: 12px; font-weight: bold; margin-bottom: 4px; display: inline-block; }
        .news-title-link { font-size: 16px; font-weight: bold; color: #c9d1d9; text-decoration: none; display: inline-block; }
        .news-title-link:hover { color: #58a6ff; text-decoration: underline; }
        .news-empty-msg { font-size: 14px; color: #8b949e; padding: 10px 0; }
        
        .pause-btn { background: #f85149; border: none; color: white; border-radius: 3px; cursor: pointer; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: 10px;}
    </style>
</head>
<body>
    <div id="zoom-controls">
        <button onclick="changeZoom(0.1)">🔍 放大 (+)</button>
        <button onclick="changeZoom(-0.1)">🔍 縮小 (-)</button>
        <button onclick="resetZoom()">🔄 重置排版</button>
    </div>

    <div class="window" id="win-sniper" style="top:10px; left:10px; width:540px; height:730px;"><div class="title-bar">🚀 狙擊手 (1000筆歷史滾動)</div><div class="content" id="sniper-list"></div><div class="resize-handle"></div></div>
    
    <div class="window" id="win-live" style="top:10px; left:560px; width:640px; height:360px;">
        <div class="title-bar">📡 即時報警 (純動能訊號) <button id="pause-btn" class="pause-btn" onclick="togglePause(event)">⏸️ 暫停滾動</button></div>
        <div class="content" id="live-list"></div><div class="resize-handle"></div>
    </div>
    <div class="window" id="win-detail" style="top:380px; left:560px; width:640px; height:360px;"><div class="title-bar">📊 戰情與新聞 (單擊載入/雙擊TW)</div><div class="content" id="detail-list"><div class="news-empty-msg" style="padding:10px;">請點擊任何股票代碼以載入戰情分析...</div></div><div class="resize-handle"></div></div>

    <div class="window" id="win-rank" style="top:10px; left:1210px; width:540px; height:730px;"><div class="title-bar">🏆 強勢榜 (1-30 USD)</div><div class="content" id="rank-list"></div><div class="resize-handle"></div></div>

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
                btn.style.background = '#3fb950';
            } else {
                btn.innerText = '⏸️ 暫停滾動';
                btn.style.background = '#f85149';
            }
        }

        function openTW(sym) { window.open(`https://tw.tradingview.com/chart/?symbol=${sym}`, '_blank'); }

        function formatFloat(floatStr) {
            let floatVal = parseFloat(floatStr.replace('M','').replace('K',''));
            return (floatStr.includes('M') && floatVal < 20.0 || floatStr.includes('K')) ? "text-gold" : "";
        }

        async function refresh() {
            try {
                const res = await fetch('/data?t=' + Date.now());
                const data = await res.json();
                document.getElementById('sys-status').innerText = '✅ 狀態: 正常 | 最後掃描(台灣時間): ' + data.last_update + ' | 總次數: ' + data.scan_count;

                // 左欄：狙擊手歷史 (精確匹配更新時間才閃爍，不再重複閃)
                let snipH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 1fr;"><div>時間</div><div>代碼</div><div>價格</div><div>漲幅%</div><div>漲幅$</div><div>交易量</div><div>浮動股</div><div>量比</div><div>跳空%</div></div>';
                data.sniper.forEach(s => {
                    let rowClass = (s.Time === data.last_update) ? "grid-row flash-row" : "grid-row";
                    snipH += `<div class="${rowClass}" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 1fr;" onclick="loadDetail('${s.Code}')" ondblclick="openTW('${s.Code}')">
                        <div>${s.Time}</div><div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Volume}</div><div class="${formatFloat(s.FloatStr)}">${s.FloatStr}</div><div class="text-gold">${s.RVOL}</div><div class="text-green">${s.Gap}</div>
                    </div>`;
                });
                document.getElementById('sniper-list').innerHTML = snipH;

                // 中欄：即時報警 
                if (!isLivePaused) {
                    let liveH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 0.8fr 1.4fr;"><div>時間</div><div>代碼</div><div>價格</div><div>漲幅%</div><div>漲幅$</div><div>交易量</div><div>浮動股</div><div>量比</div><div>換手</div><div>訊號連擊</div></div>';
                    data.live.forEach(l => {
                        liveH += `<div class="grid-row" style="grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 0.8fr 1.4fr;" onclick="loadDetail('${l.Code}')" ondblclick="openTW('${l.Code}')">
                            <div>${l.Time}</div><div class="text-blue">${l.Code}</div><div>${l.Price}</div><div class="${l.Change.includes('-') ? 'text-red' : 'text-green'}">${l.Change}</div><div>${l.ChangeAmt}</div><div>${l.Volume}</div><div class="${formatFloat(l.FloatStr)}">${l.FloatStr}</div><div>${l.RVOL}</div><div>${l.Turnover}</div><div style="color:#ff7b72; font-weight:bold;">${l.Type}</div>
                        </div>`;
                    });
                    document.getElementById('live-list').innerHTML = liveH;
                }

                // 右欄：強勢榜 
                let rankH = '<div class="grid-row grid-th" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 0.8fr;"><div>代碼</div><div>價格</div><div>漲幅%</div><div>漲幅$</div><div>交易量</div><div>浮動股</div><div>量比</div><div>換手</div></div>';
                data.stocks.forEach(s => {
                    rankH += `<div class="grid-row" style="grid-template-columns: 0.8fr 1fr 1fr 1fr 1.2fr 1.2fr 0.8fr 0.8fr;" onclick="loadDetail('${s.Code}')" ondblclick="openTW('${s.Code}')">
                        <div class="text-blue">${s.Code}</div><div>${s.Price}</div><div class="text-green">${s.Change}</div><div class="text-green">${s.ChangeAmt}</div><div>${s.Volume}</div><div class="${formatFloat(s.FloatStr)}">${s.FloatStr}</div><div>${s.RVOL}</div><div>${s.Turnover}</div>
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

            let newsHTML = '<h3 class="news-header">📰 48H 催化劑情報 (台灣時間)</h3>';
            if (d.NewsList && d.NewsList.length > 0) {
                d.NewsList.forEach(n => {
                    if(n.link === '#') {
                        newsHTML += `<div class="news-empty-msg">${n.title}</div>`;
                    } else {
                        let borderColor = "#8b949e";
                        let dateTag = "📅 歷史";
                        
                        if(n.category === "today") {
                            borderColor = "#ff7b72";
                            dateTag = "🔥 本日";
                        } else if (n.category === "yesterday") {
                            borderColor = "#58a6ff";
                            dateTag = "📆 昨日";
                        }
                        
                        newsHTML += `
                        <div class="news-item-container" style="border-left-color: ${borderColor};">
                            <span class="news-date-tag" style="color:${borderColor};">${dateTag} ${n.time}</span><br>
                            <a href="${n.link}" target="_blank" class="news-title-link">${n.title}</a>
                        </div>`;
                    }
                });
            } else {
                newsHTML += '<div class="news-empty-msg">📡 檢索中或無重大新聞...</div>';
            }

            document.getElementById('detail-list').innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:6px;">
                    <div class="p-box">今日最高 (HP)<div class="p-val">${d.HOD}</div></div>
                    <div class="p-box">換手率 (%)<div class="p-val" style="color:#f2cc60;">${d.Turnover || 'N/A'}</div></div>
                    <div class="p-box">浮動股數<div class="p-val" style="color:#58a6ff;">${d.FloatStr}</div></div>
                    <div class="p-box">跳空幅 (%)<div class="p-val" style="color:#3fb950;">${d.Gap || '0%'}</div></div>
                    <div class="p-box">量比 (RVOL)<div class="p-val">${d.RVOL}</div></div>
                    <div class="p-box">漲跌金額<div class="p-val">${d.ChangeAmt}</div></div>
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
        for item in root.findall('./channel/item')[:4]: 
            title_text = item.find('title').text
            title_en = title_text.rsplit(" - ", 1)[0] if " - " in title_text else title_text
            
            pub_dt_utc = parser.parse(item.find('pubDate').text)
            pub_dt_tw = pub_dt_utc.astimezone(tz_tw)
            
            if pub_dt_tw.date() == now_tw.date(): cat = "today"
            elif pub_dt_tw.date() == (now_tw.date() - timedelta(days=1)): cat = "yesterday"
            else: cat = "older"
                
            news.append({
                'title': translator.translate(title_en),
                'link': item.find('link').text,
                'time': pub_dt_tw.strftime('%m/%d %H:%M'),
                'category': cat
            })
            
        cell["NewsList"] = news if news else [{"title": "無過去 48H 相關重大新聞", "link": "#", "time": "", "category": "none"}]
    except Exception as e:
        cell["NewsList"] = [{"title": "新聞伺服器連線異常，請稍後重試", "link": "#", "time": "", "category": "none"}]

def get_static(ticker):
    if ticker in stock_cache: return stock_cache[ticker]
    try:
        t = yf.Ticker(ticker); i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000); p = i.get('previousClose', 1.0)
        stock_cache[ticker] = (f, a, p)
        return f, a, p
    except: return 1000000, 500000, 1.0

def parse_vol(v_str):
    v_str = v_str.upper().replace(',', '').strip()
    try:
        if 'M' in v_str: return float(v_str.replace('M', '')) * 1e6
        if 'K' in v_str: return float(v_str.replace('K', '')) * 1e3
        if 'B' in v_str: return float(v_str.replace('B', '')) * 1e9
        return float(v_str)
    except: return 0.0

# --- [ 3. 智能路由中央引擎 ] ---
def scanner_engine():
    global MASTER_BRAIN
    count = 0
    print("🔥 啟動掃描引擎 (狙擊事件精準同步版)...")
    
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
                soup = BeautifulSoup(r.text, 'lxml'); table = soup.find('table')
                if table:
                    temp_stocks, current_snip_scan, current_scan = [], [], []
                    for tr in table.find_all('tr')[1:30]:
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        
                        sym = tds[1].text.strip()
                        try: p_num = float(tds[4].text.replace('$','').replace(',',''))
                        except: continue
                        
                        if 1.0 <= p_num <= 30.0:
                            f, a, prev = get_static(sym)
                            raw_vol_str = tds[5].text.strip()
                            vol_raw = parse_vol(raw_vol_str)
                                
                            # ★ 加入 sniper_logged 標記，確保狙擊手只在首次發現或創新高時觸發
                            cell = MASTER_BRAIN["details"].get(sym, {"HOD": p_num, "NewsList": [], "streak": 0, "sniper_logged": False})
                            is_hod_break = False
                            
                            if p_num > cell["HOD"]: 
                                cell["HOD"] = p_num
                                cell["streak"] += 1
                                is_hod_break = True
                            
                            gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                            rvol = vol_raw / a if a > 0 else 1.0
                            
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            change_val = p_num - prev
                            change_amt_str = f"+${change_val:.2f}" if change_val >= 0 else f"-${abs(change_val):.2f}"
                            turnover_str = f"{(vol_raw/f*100):.1f}%" if f > 0 else "0%"
                            chg_str = tds[3].text.strip()

                            item = {
                                "Time": current_time_tw,
                                "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": chg_str, "ChangeAmt": change_amt_str,
                                "Volume": raw_vol_str, 
                                "HOD": f"${cell['HOD']:.2f}",
                                "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%", "FloatStr": float_str,
                                "Turnover": turnover_str, "Type": "掃描更新"
                            }
                            
                            is_actionable = False
                            is_sniper_cond = (gap_p > 3.0 and rvol > 5.0)
                            
                            # ★ 1. 狙擊手與即時報警的【100% 同步邏輯】
                            # 只在第一次發現，或是打破今日新高時，才將其同時推入兩個清單
                            if is_sniper_cond and (not cell["sniper_logged"] or is_hod_break): 
                                item["Type"] = f"🚀 爆發 ({cell['streak']}連擊)" if cell['streak'] > 0 else "🚀 爆發"
                                current_snip_scan.append(item)  # 推入狙擊手
                                current_scan.append(item)       # 推入即時報警 (完全相同的物件與時間)
                                cell["sniper_logged"] = True
                                is_actionable = True
                            
                            # ★ 2. 如果未達狙擊手標準，但帶量過高點，則只推入即時報警
                            elif is_hod_break and rvol > 1.2:
                                item["Type"] = f"🔥 新高 ({cell['streak']}連擊)"
                                current_scan.append(item)
                                is_actionable = True
                            
                            temp_stocks.append(item)
                            
                            if not cell["NewsList"]: 
                                threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                                
                            cell["Gap"] = item["Gap"]
                            cell["Turnover"] = item["Turnover"]
                            cell["RVOL"] = item["RVOL"]
                            cell["FloatStr"] = float_str
                            cell["ChangeAmt"] = change_amt_str
                            MASTER_BRAIN["details"][sym] = cell

                    count += 1
                    
                    new_sniper = (current_snip_scan + MASTER_BRAIN["sniper"])[:1000]
                    new_live = (current_scan + MASTER_BRAIN["live"])[:1000]
                    
                    MASTER_BRAIN.update({
                        "stocks": temp_stocks, "sniper": new_sniper,
                        "live": new_live, "last_update": current_time_tw, "scan_count": count
                    })
            
            time.sleep(random.uniform(5.0, 10.0))
        except: time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
