import os, time, threading, requests, random, warnings, yfinance as yf, traceback
from datetime import datetime, timedelta
import pytz
import json
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

warnings.filterwarnings('ignore')
app = Flask(__name__)
CORS(app)

MASTER_BRAIN = {
    "gappers": [], "high_vol": [], "ipos": [],       
    "hod": [], "surge": [], "news_leaders": [], "grinders": [], 
    "details": {}, "last_update": "N/A", "scan_count": 0
}
stock_cache = {} 
translator = GoogleTranslator(source='auto', target='zh-TW')

STEALTH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

# 🔑 請在這裡貼上您的 Finnhub API Key
FINNHUB_API_KEY = "d2nua3hr01qsrqkq5ff0d2nua3hr01qsrqkq5ffg"

# --- [ 1. 終極 UI 介面 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>ROSS Sniper V215.4.1 - X光除錯版</title>
    <style>
        body { margin: 0; background: #050811; color: #c9d1d9; font-family: sans-serif; overflow: hidden; transform-origin: top left; }
        .window { position: absolute; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; box-shadow: 0 5px 15px rgba(0,0,0,0.8); display: flex; flex-direction: column; overflow: hidden; z-index: 1; }
        .title-bar { background: #0d1f3d !important; color: #ffffff !important; padding: 5px 10px; font-size: 11px; font-weight: bold; cursor: grab; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; }
        .bg-blue, .bg-green, .bg-gold, .bg-red, .bg-purple, .bg-dark { background: transparent; }
        .content { flex: 1; padding: 4px; overflow-y: auto; font-size: 10.5px; }
        .resize-handle { width: 12px; height: 12px; background: linear-gradient(135deg, transparent 50%, #8b949e 50%); position: absolute; right: 0; bottom: 0; cursor: se-resize; z-index: 100;}
        .grid-row { display: grid; align-items: center; border-bottom: 1px solid #21262d; padding: 5px 0; cursor: pointer; transition: background 0.1s; }
        .grid-row:hover { background: #161b22; }
        .grid-th { font-weight: bold; color: #8b949e; border-bottom: 2px solid #30363d; position: sticky; top: 0; background: #0d1117; z-index: 10; padding-bottom: 5px; }
        .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #ff7b72; font-weight: bold; } .text-blue { color: #58a6ff; font-weight: bold; }
        .text-gold { color: #f2cc60; font-weight: bold; } .text-orange { color: #ff9900; font-weight: bold; } .text-purple { color: #d500f9; font-weight: bold; }
        .score-tag-high { background:#6e40c9; color:#fff; padding:1px 4px; border-radius:3px; font-size:9px; margin-right:4px; font-weight:bold;}
        .score-tag-pos { background:#238636; color:#fff; padding:1px 4px; border-radius:3px; font-size:9px; margin-right:4px; font-weight:bold;}
        .score-tag-neg { background:#da3633; color:#fff; padding:1px 4px; border-radius:3px; font-size:9px; margin-right:4px; font-weight:bold;}
        .bg-cell-purple { background: #6e40c9; color: #ffffff !important; font-weight: bold; padding: 2px 4px; border-radius: 3px; display: inline-block; }
        .row-extreme-vol { background-color: rgba(204, 173, 51, 0.2); border-left: 2px solid #ccad33; } .row-extreme-vol:hover { background-color: rgba(204, 173, 51, 0.3); }
        .row-micro-float { background-color: rgba(138, 43, 226, 0.15); border-left: 2px solid #8a2be2; } .row-micro-float:hover { background-color: rgba(138, 43, 226, 0.25); }
        .row-news { background-color: rgba(56, 117, 191, 0.15); border-left: 2px solid #3875bf; } .row-news:hover { background-color: rgba(56, 117, 191, 0.25); }
        .row-grinder { background-color: rgba(56, 139, 253, 0.1); border-left: 2px solid #388bfd; } .row-grinder:hover { background-color: rgba(56, 139, 253, 0.2); }
        .p-box { background: #161b22; border: 1px solid #30363d; padding: 6px; border-radius: 4px; text-align: center; } .p-val { font-size: 14px; font-weight: bold; color: #fff; margin-top: 2px; font-family: 'Consolas'; }
        #sys-status { position: fixed; bottom: 10px; left: 10px; color: #8b949e; font-size: 10px; background: rgba(13,17,23,0.9); padding: 4px 8px; border: 1px solid #30363d; border-radius: 4px; z-index: 1000; }
        #zoom-controls { position: fixed; top: 10px; right: 10px; background: rgba(13,17,23,0.9); padding: 5px; border: 1px solid #30363d; border-radius: 4px; z-index: 2000; }
        #zoom-controls button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; cursor: pointer; padding: 4px 8px; border-radius: 3px; font-weight: bold; margin-left: 2px; } #zoom-controls button:hover { background: #30363d; }
        @keyframes flashGreen { 0% { background-color: rgba(63, 185, 80, 0.4); } 100% { background-color: transparent; } } @keyframes flashRed { 0% { background-color: rgba(255, 123, 114, 0.4); } 100% { background-color: transparent; } } @keyframes flashYellow { 0% { background-color: rgba(210, 153, 34, 0.4); } 100% { background-color: transparent; } } @keyframes flashOrange { 0% { background-color: rgba(255, 123, 0, 0.4); } 100% { background-color: transparent; } }
        .flash-green { animation: flashGreen 1.5s ease-out; border-left: 2px solid #3fb950; } .flash-red { animation: flashRed 1.5s ease-out; border-left: 2px solid #ff7b72; } .flash-yellow { animation: flashYellow 1.5s ease-out; border-left: 2px solid #d29922; } .flash-orange { animation: flashOrange 1.5s ease-out; border-left: 2px solid #ff7b00; }
        .news-header { margin-top:5px; border-bottom:1px solid #30363d; padding-bottom:3px; font-size: 12px; color: #fff; }
        .news-item-container { border-left: 2px solid #8b949e; padding-left: 6px; margin-bottom: 8px; line-height: 1.3; }
        .news-date-tag { font-size: 10px; font-weight: bold; margin-bottom: 2px; display: inline-block; color:#8b949e;}
        .news-title-link { font-size: 12px; font-weight: bold; color: #c9d1d9; text-decoration: none; display: inline-block; transition: color 0.2s;} .news-title-link:hover { color: #58a6ff; text-decoration: underline; }
        .pause-btn { background: #f85149; border: 1px solid #fff; color: white; border-radius: 3px; cursor: pointer; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: 10px;}
    </style>
</head>
<body>
    <div id="zoom-controls"><button onclick="changeZoom(0.1)">🔍 +</button><button onclick="changeZoom(-0.1)">🔍 -</button><button onclick="resetZoom()">🔄 重置</button><button id="lock-btn" onclick="toggleGlobalLock()">🔓 視窗解鎖</button><button id="engine-btn" onclick="toggleEngineRun()">⏹️ 停止掃描</button></div>
    <div class="window" id="win-gap" style="top:10px; left:10px; width:400px; height:280px;"><div class="title-bar bg-blue">1. 盤前跳空漲幅榜</div><div class="content" id="gap-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-vol" style="top:300px; left:10px; width:400px; height:280px;"><div class="title-bar bg-gold">3. 異常爆量上漲</div><div class="content" id="vol-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-ipo" style="top:590px; left:10px; width:400px; height:280px;"><div class="title-bar bg-purple">7. 極低流通與新股</div><div class="content" id="ipo-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-hod" style="top:10px; left:420px; width:500px; height:430px;"><div class="title-bar bg-green">2. 突破今日新高 <button id="pause-btn" class="pause-btn" onclick="togglePause(event)">⏸️ 暫停滾動</button></div><div class="content" id="hod-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-surge" style="top:450px; left:420px; width:500px; height:420px;"><div class="title-bar bg-green">4. 短線動能追蹤</div><div class="content" id="surge-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-news-score" style="top:10px; left:930px; width:440px; height:280px;"><div class="title-bar bg-purple">6. 催化劑新聞評分榜</div><div class="content" id="news-score-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-grind" style="top:300px; left:930px; width:440px; height:280px;"><div class="title-bar bg-blue">5. 主力無量緩漲</div><div class="content" id="grind-list"></div><div class="resize-handle"></div></div>
    <div class="window" id="win-detail" style="top:590px; left:930px; width:440px; height:280px;"><div class="title-bar bg-dark">📊 戰情與新聞分析</div><div class="content" id="detail-list"><div style="padding:10px; color:#8b949e;">請點擊任何股票代碼以載入戰情報告...</div></div><div class="resize-handle"></div></div>
    <div id="sys-status">🔄 掃描引擎連線中...</div>

    <script>
        let currentZoom = parseFloat(localStorage.getItem('ross_zoom')) || 1.0; document.body.style.zoom = currentZoom; 
        let isWindowLocked = false; let isEngineRunning = true;
        let readNewsMap = JSON.parse(localStorage.getItem('ross_news_read') || '{}'); let starNewsMap = JSON.parse(localStorage.getItem('ross_news_star') || '{}');

        window.markRead = function(id, url) { readNewsMap[id] = true; localStorage.setItem('ross_news_read', JSON.stringify(readNewsMap)); let linkEl = document.getElementById('news-link-' + id); if(linkEl) linkEl.style.color = '#6e7681'; if(url !== '#') window.open(url, '_blank'); refresh(); };
        window.toggleStar = function(id, event) { event.stopPropagation(); if(starNewsMap[id]) delete starNewsMap[id]; else starNewsMap[id] = true; localStorage.setItem('ross_news_star', JSON.stringify(starNewsMap)); let starEl = document.getElementById('star-icon-' + id); if(starEl) starEl.innerText = starNewsMap[id] ? '⭐' : '☆'; };
        function toggleGlobalLock() { isWindowLocked = !isWindowLocked; const btn = document.getElementById('lock-btn'); if(isWindowLocked) { btn.innerText = '🔒 視窗鎖定'; btn.style.background = '#a50e0e'; } else { btn.innerText = '🔓 視窗解鎖'; btn.style.background = '#21262d'; } }
        function toggleEngineRun() { isEngineRunning = !isEngineRunning; const btn = document.getElementById('engine-btn'); if(!isEngineRunning) { btn.innerText = '▶️ 啟動掃描'; btn.style.background = '#137333'; document.getElementById('sys-status').innerText = '⏸️ 系統已完全暫停'; } else { btn.innerText = '⏹️ 停止掃描'; btn.style.background = '#21262d'; } }
        function saveLayout() { const layout = {}; document.querySelectorAll('.window').forEach(win => { layout[win.id] = { top: win.style.top, left: win.style.left, width: win.style.width, height: win.style.height }; }); localStorage.setItem('ross_layout', JSON.stringify(layout)); }
        function changeZoom(delta) { currentZoom = Math.max(0.5, Math.min(2.0, currentZoom + delta)); document.body.style.zoom = currentZoom; localStorage.setItem('ross_zoom', currentZoom); }
        function resetZoom() { currentZoom = 1.0; document.body.style.zoom = currentZoom; localStorage.removeItem('ross_zoom'); localStorage.removeItem('ross_layout'); location.reload(); }

        window.addEventListener('DOMContentLoaded', () => { const saved = JSON.parse(localStorage.getItem('ross_layout')); if(saved) { for(const id in saved) { const win = document.getElementById(id); if(win && saved[id]) { win.style.top = saved[id].top; win.style.left = saved[id].left; win.style.width = saved[id].width; win.style.height = saved[id].height; } } } });
        document.querySelectorAll('.window').forEach(win => { const title = win.querySelector('.title-bar'); const handle = win.querySelector('.resize-handle'); title.onmousedown = (e) => { if(isWindowLocked || e.target.tagName === 'BUTTON') return; let startX = e.clientX, startY = e.clientY; let startTop = win.offsetTop, startLeft = win.offsetLeft; document.onmousemove = (ev) => { win.style.top = (startTop + (ev.clientY - startY) / currentZoom) + "px"; win.style.left = (startLeft + (ev.clientX - startX) / currentZoom) + "px"; }; document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; saveLayout(); }; }; handle.onmousedown = (e) => { if(isWindowLocked) return; let startW = win.offsetWidth, startH = win.offsetHeight; let startX = e.clientX, startY = e.clientY; document.onmousemove = (ev) => { win.style.width = (startW + (ev.clientX - startX) / currentZoom) + 'px'; win.style.height = (startH + (ev.clientY - startY) / currentZoom) + 'px'; }; document.onmouseup = () => { document.onmousemove = null; document.onmouseup = null; saveLayout(); }; }; });

        let isLivePaused = false;
        function togglePause(e) { e.stopPropagation(); isLivePaused = !isLivePaused; const btn = document.getElementById('pause-btn'); if(isLivePaused) { btn.innerText = '▶️ 恢復滾動'; btn.style.background = '#137333'; } else { btn.innerText = '⏸️ 暫停滾動'; btn.style.background = '#a50e0e'; } }
        function openTW(sym) { window.open(`https://tw.tradingview.com/chart/?symbol=${sym}`, '_blank'); }

        function buildTable(dataArray, detailsData, cols, colTemplate, showTime=false, baseFlashClass="flash-green", rowType="normal") {
            let html = `<div class="grid-row grid-th" style="grid-template-columns: ${colTemplate};">`;
            cols.forEach(c => html += `<div>${c}</div>`); html += '</div>';
            dataArray.forEach(item => {
                let fVal = parseFloat((item.FloatStr || "0").replace('M','').replace('K',''));
                let isMicroFloat = ((item.FloatStr || "").includes('K') || ((item.FloatStr || "").includes('M') && fVal <= 5.0));
                let rVal = parseFloat((item.RVOL || "0").replace('x','').replace('N/A','0'));
                let isExtremeVol = (rVal >= 5.0);
                let hasNews = false, isNewsRead = false;
                let dNews = detailsData[item.Code] ? detailsData[item.Code].NewsList : [];
                if(dNews && dNews.length > 0 && dNews[0].id && dNews[0].id !== "0") { hasNews = true; isNewsRead = dNews.some(n => readNewsMap[n.id]); }

                let rowClass = "grid-row";
                if (rowType === "grinder") rowClass += " row-grinder"; else if (isExtremeVol) rowClass += " row-extreme-vol"; else if (isMicroFloat) rowClass += " row-micro-float"; else if (hasNews) rowClass += " row-news";
                let newsIcon = ''; if(hasNews) { newsIcon = isNewsRead ? ' <span title="新聞已讀" style="font-size:10px; opacity:0.6;">📰✔️</span>' : ' <span title="今日有新聞" style="font-size:10px;">📰</span>'; }
                let currentFlash = baseFlashClass; if (item.Streak && rowType !== "grinder") { if (item.Streak.includes('💥')) currentFlash = "flash-yellow"; else if (item.Streak.includes('🚀')) currentFlash = "flash-orange"; }
                if (showTime && item.Time === detailsData.last_update) rowClass += " " + currentFlash;
                
                html += `<div class="${rowClass}" style="grid-template-columns: ${colTemplate};" onclick="loadDetail('${item.Code}')" ondblclick="openTW('${item.Code}')">`;
                cols.forEach(c => {
                    if(c === '時間') html += `<div>${item.Time}</div>`; else if(c === '代碼') html += `<div class="text-blue">${item.Code}${newsIcon}</div>`;
                    else if(c === '價格') html += `<div>${item.Price}</div>`; else if(c === '漲幅%') html += `<div class="text-green">${item.Change}</div>`;
                    else if(c === '跳空%') html += `<div class="text-green">${item.Gap}</div>`; else if(c === '交易量') html += `<div class="text-gold">${item.Volume}</div>`; 
                    else if(c === '浮動股') { let fClass = "text-blue"; if (isMicroFloat) fClass = "text-purple"; else if ((item.FloatStr || "").includes('M') && fVal <= 20.0) fClass = "text-orange"; html += `<div class="${fClass}">${item.FloatStr}</div>`; }
                    else if(c === '量比') html += `<div class="text-gold">${item.RVOL}</div>`; 
                    else if(c === '評分') { let score = item.NewsScore || 0; if(score >= 10) html += `<div><span class="bg-cell-purple">🔥+${score}</span></div>`; else if(score > 0) html += `<div><span class="text-green">+${score}</span></div>`; else if(score < 0) html += `<div><span class="text-red">☠️${score}</span></div>`; else html += `<div><span class="text-blue">-</span></div>`; }
                    else if(c === '動能指標') { let txtColor = "text-green"; if (item.Streak) { if(item.Streak.includes('💥')) txtColor = "text-gold"; else if(item.Streak.includes('🚀')) txtColor = "text-orange"; else if(item.Streak.includes('🐢') || item.Streak.includes('🔥')) txtColor = "text-blue"; } html += `<div class="${txtColor}">${item.Streak || ""}</div>`; }
                }); html += '</div>';
            }); return html;
        }

        async function refresh() {
            if(!isEngineRunning) return; 
            try {
                const res = await fetch('/data?t=' + Date.now()); const data = await res.json(); data.details.last_update = data.last_update;
                document.getElementById('sys-status').innerText = '✅ 更新時間(TW): ' + data.last_update + ' | 總掃描: ' + data.scan_count;
                document.getElementById('gap-list').innerHTML = buildTable(data.gappers, data.details, ['代碼','價格','跳空%','交易量','浮動股','量比'], '0.8fr 1fr 1fr 1.2fr 1fr 0.8fr');
                document.getElementById('vol-list').innerHTML = buildTable(data.high_vol, data.details, ['代碼','價格','漲幅%','量比','交易量','浮動股'], '0.8fr 1fr 1fr 1fr 1.2fr 1fr');
                document.getElementById('ipo-list').innerHTML = buildTable(data.ipos, data.details, ['代碼','價格','浮動股','交易量','漲幅%','量比'], '0.8fr 1fr 1fr 1.2fr 1fr 0.8fr');
                if (!isLivePaused) { document.getElementById('hod-list').innerHTML = buildTable(data.hod, data.details, ['時間','代碼','價格','漲幅%','交易量','量比','浮動股'], '1fr 0.8fr 1fr 1fr 1.2fr 0.8fr 1fr', true, 'flash-green'); }
                document.getElementById('surge-list').innerHTML = buildTable(data.surge, data.details, ['時間','代碼','價格','動能指標','交易量','量比'], '1fr 0.8fr 1fr 1.2fr 1.2fr 0.8fr', true, 'flash-green');
                document.getElementById('news-score-list').innerHTML = buildTable(data.news_leaders, data.details, ['代碼','價格','漲幅%','評分','交易量','浮動股'], '0.8fr 1fr 1fr 0.8fr 1.2fr 1fr');
                document.getElementById('grind-list').innerHTML = buildTable(data.grinders, data.details, ['時間','代碼','價格','動能指標','交易量','量比'], '1fr 0.8fr 1fr 1.2fr 1.2fr 0.8fr', true, 'flash-green', "grinder");
            } catch(e) {}
        }

        async function loadDetail(sym) {
            const res = await fetch('/data?t=' + Date.now()); const data = await res.json(); const d = data.details[sym]; if(!d) return;
            let newsHTML = '<h3 class="news-header">📰 今日 Finnhub 催化劑解析與評分</h3>';
            if (d.NewsList && d.NewsList.length > 0) {
                d.NewsList.forEach(n => {
                    if(n.link === '#') { newsHTML += `<div style="color:#8b949e; font-size:10px;">${n.title}</div>`; } 
                    else {
                        let isRead = readNewsMap[n.id]; let isStarred = starNewsMap[n.id]; let titleColor = isRead ? '#6e7681' : '#c9d1d9'; let starSymbol = isStarred ? '⭐' : '☆';
                        let scoreTag = ''; if(n.score >= 10) scoreTag = `<span class="score-tag-high">🔥 +${n.score}</span>`; else if(n.score > 0) scoreTag = `<span class="score-tag-pos">🔥 +${n.score}</span>`; else if(n.score < 0) scoreTag = `<span class="score-tag-neg">☠️ ${n.score}</span>`;
                        newsHTML += `<div class="news-item-container"><span class="news-date-tag">${n.time}</span><span id="star-icon-${n.id}" style="cursor:pointer; float:right; color:#f2cc60;" onclick="toggleStar('${n.id}', event)">${starSymbol}</span><br>${scoreTag}<a id="news-link-${n.id}" href="javascript:void(0)" onclick="markRead('${n.id}', '${n.link}')" class="news-title-link" style="color:${titleColor};">${n.title}</a></div>`;
                    }
                });
            } else { newsHTML += '<div style="color:#8b949e; font-size:10px;">今日無重大公關新聞</div>'; }
            document.getElementById('detail-list').innerHTML = `<div id="hud-ticker" style="font-size: 36px; font-weight: 900; color: #58a6ff; text-align: center; margin-bottom: 8px; cursor: pointer; letter-spacing: 2px; text-shadow: 0 0 10px rgba(88, 166, 255, 0.3);" ondblclick="openTW('${sym}')" title="雙擊開啟 TradingView">${sym}</div><div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:4px; margin-bottom:5px;"><div class="p-box">今日最高<div class="p-val">${d.HOD}</div></div><div class="p-box">量比<div class="p-val">${d.RVOL}</div></div><div class="p-box">浮動股<div class="p-val" style="color:#58a6ff;">${d.FloatStr}</div></div></div>${newsHTML}`;
        }
        setInterval(refresh, 2000);
    </script>
</body>
</html>
"""

# --- [ 2. 核心情報引擎 ] ---
def calculate_news_score(headline):
    headline_lower = headline.lower()
    score = 0
    strong_bull = ['fda', 'phase', 'approval', 'clearance', 'merger', 'acquisition', 'buyout', 'patent', 'breakthrough', 'fast track', 'orphan', 'pivotal']
    bull = ['earnings', 'guidance', 'upgrade', 'contract', 'partnership', 'agreement', 'raised', 'beat', 'profit', 'revenue', 'dividend', 'milestone', 'positive']
    bear = ['offering', 'pricing', 'lawsuit', 'investigation', 'delisting', 'downgrade', 'bankruptcy', 'missed', 'loss', 'warning', 'sec', 'subpoena', 'reverse split', 'default']
    
    for word in strong_bull:
        if word in headline_lower: score += 10
    for word in bull:
        if word in headline_lower: score += 5
    for word in bear:
        if word in headline_lower: score -= 10
    return score

def fetch_news_bg(ticker, cell):
    try:
        if FINNHUB_API_KEY == "請填入您的KEY" or not FINNHUB_API_KEY:
            cell["NewsList"] = [{"id": "0", "title": "⚠️ 請填寫 Finnhub API Key", "score": 0, "link": "#", "time": "", "category": "none"}]
            cell["max_news_score"] = 0
            return

        tz_us = pytz.timezone('US/Eastern')
        now_us = datetime.now(tz_us)
        target_date = now_us.strftime('%Y-%m-%d')
        
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={target_date}&to={target_date}&token={FINNHUB_API_KEY}"
        r = requests.get(url, timeout=5)
        data = r.json()
        
        news = []
        max_score = 0
        if data and isinstance(data, list):
            for item in data[:4]: 
                headline_en = item.get('headline', '')
                if not headline_en: continue
                score = calculate_news_score(headline_en)
                if score > max_score: max_score = score
                elif score < 0 and max_score == 0: max_score = score 
                
                try: title_zh = translator.translate(headline_en)
                except: title_zh = headline_en
                    
                news_time = datetime.fromtimestamp(item.get('datetime', 0) or 0, pytz.timezone('Asia/Taipei')).strftime('%m/%d %H:%M')
                news_id = str(item.get('id', random.randint(1000, 999999)))
                news.append({'id': news_id, 'title': title_zh, 'score': score, 'link': item.get('url', '#'), 'time': news_time})
        
        if not news: news = [{"id": "0", "title": "今日無重大公關新聞", "score": 0, "link": "#", "time": ""}]
        cell["NewsList"] = news
        cell["max_news_score"] = max_score
    except:
        cell["NewsList"] = [{"id": "0", "title": "Finnhub 連線異常", "score": 0, "link": "#", "time": ""}]
        cell["max_news_score"] = 0

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
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
    else: return f"{int(v_float)}"

def parse_vol(v_str):
    v_str = v_str.upper().replace(',', '').strip()
    try:
        if 'M' in v_str: return float(v_str.replace('M', '')) * 1e6
        if 'K' in v_str: return float(v_str.replace('K', '')) * 1e3
        return float(v_str)
    except: return 0.0

# --- [ 3. 中央引擎：X光透視除錯模式 ] ---
def scanner_engine():
    global MASTER_BRAIN
    count = 0
    print("🔥 啟動七星陣列掃描引擎 (V215.4.1 X光除錯版)...")
    
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

            print(f"\n[{current_time_tw}] 📡 正在請求: {url}")
            r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            print(f"[{current_time_tw}] ✅ 伺服器狀態碼: {r.status_code}")
            
            if r.status_code == 404:
                url = "https://stockanalysis.com/markets/premarket/gainers/"
                r = requests.get(url, headers=STEALTH_HEADERS, timeout=8)
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                table = soup.find('table')
                
                # ★ X光除錯核心段落：檢查表格內容
                if not table:
                    print(f"[{current_time_tw}] ❌ 警告：沒有找到任何表格 (<table>)！網站可能改成 JS 動態載入了！")
                else:
                    rows = table.find_all('tr')
                    print(f"[{current_time_tw}] 📊 表格解析：共找到 {len(rows)} 列 (包含標題列)")
                    
                    if len(rows) <= 1:
                        print(f"[{current_time_tw}] ❌ 警告：表格只有標題，沒有任何股票資料！")
                    else:
                        # 印出第一筆實際股票的內容，讓我們看看欄位有沒有被改變
                        sample_tds = rows[1].find_all('td')
                        print(f"[{current_time_tw}] 🔍 第一筆股票資料測試：總共有 {len(sample_tds)} 個欄位 (td)")
                        if len(sample_tds) >= 5:
                            for i, td in enumerate(sample_tds[:6]):
                                print(f"   欄位 [{i}]: {td.text.strip()}")
                        else:
                            print(f"[{current_time_tw}] ❌ 警告：欄位數量不足 5 格，解析被迫跳過！")

                    t_all, c_hod, c_surge, c_grind = [], [], [], []
                    
                    for tr in rows[1:100]: 
                        tds = tr.find_all('td')
                        if len(tds) < 5: continue
                        
                        sym = tds[1].text.strip()
                        raw_price = tds[4].text.strip() # 先取出文字
                        
                        try: 
                            p_num = float(raw_price.replace('$','').replace(',',''))
                        except Exception as e:
                            # 如果價格轉換失敗，印出來警告
                            print(f"[{current_time_tw}] ⚠️ 無法轉換價格，過濾掉股票 [{sym}]。原始字串: {raw_price}")
                            continue
                        
                        if 0.5 <= p_num <= 50.0:
                            f, a, prev = get_static(sym)
                            
                            raw_vol_str = tds[5].text.strip()
                            vol_raw = parse_vol(raw_vol_str)
                            formatted_volume = format_vol_km(vol_raw)
                            
                            is_new_stock = sym not in MASTER_BRAIN["details"]
                            initial_hod = (p_num * 0.98) if is_new_stock else p_num
                            
                            cell = MASTER_BRAIN["details"].get(sym, {
                                "HOD": initial_hod, "NewsList": [], "max_news_score": 0, "streak": 0, "last_act": "",
                                "last_price": p_num, "last_vol": vol_raw, "last_vol_delta": 0,
                                "up_ticks": 0, "last_grind_tick": 0, "last_long_grind_tick": 0 
                            })
                            
                            is_hod_break = False
                            if p_num > cell["HOD"]: 
                                cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                            
                            gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                            rvol = vol_raw / a if a > 0 else 1.0
                            drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            
                            item = {
                                "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                                "Change": tds[3].text.strip(), "Volume": formatted_volume, 
                                "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%", "Drop": f"{drop_p:.1f}%",
                                "FloatStr": float_str, "Streak": f"x{cell['streak']}", 
                                "gap_num": gap_p, "rvol_num": rvol, "f_num": f
                            }
                            t_all.append(item)
                            
                            cell["latest_item"] = item
                            cell["last_seen"] = current_time_tw

                            last_price = cell.get("last_price", p_num)
                            last_vol = cell.get("last_vol", vol_raw)
                            last_vol_delta = cell.get("last_vol_delta", 0)
                            up_ticks = cell.get("up_ticks", 0) 
                            curr_vol_delta = vol_raw - last_vol 
                            
                            if p_num > last_price:
                                up_ticks += 1
                                tick_jump_pct = ((p_num - last_price) / last_price) * 100
                            elif p_num < last_price:
                                up_ticks = 0; tick_jump_pct = 0; cell["last_grind_tick"] = 0; cell["last_long_grind_tick"] = 0 
                            else: tick_jump_pct = 0

                            if is_hod_break and (rvol > 0.2 or vol_raw > 50000):
                                c_hod.append(item); cell["last_act"] = "hod"

                            is_velocity_spike = tick_jump_pct >= 2.0
                            is_steady_grind = (up_ticks >= 3 and up_ticks % 3 == 0 and cell.get("last_grind_tick") != up_ticks)
                            is_vol_spike = (curr_vol_delta > last_vol_delta * 3) and (curr_vol_delta > 20000) and (p_num >= last_price)
                            is_long_grinder = (up_ticks >= 6 and tick_jump_pct < 3.0 and drop_p > -5.0 and p_num >= 1.0)
                            
                            if (cell["streak"] >= 2 and is_hod_break) or is_velocity_spike or is_steady_grind or is_vol_spike:
                                item_surge = item.copy()
                                if is_velocity_spike: item_surge["Streak"] = f"🚀急噴+{tick_jump_pct:.1f}%"
                                elif is_vol_spike: item_surge["Streak"] = f"💥爆量+{format_vol_km(curr_vol_delta)}"
                                elif is_steady_grind: item_surge["Streak"] = f"🔥連漲x{up_ticks}"; cell["last_grind_tick"] = up_ticks 
                                else: item_surge["Streak"] = f"⭐破高x{cell['streak']}"
                                c_surge.append(item_surge); cell["last_act"] = "surge"
                                
                            if is_long_grinder and cell.get("last_long_grind_tick") != up_ticks:
                                item_grind = item.copy()
                                item_grind["Streak"] = f"🐢緩漲x{up_ticks}"
                                c_grind.append(item_grind); cell["last_long_grind_tick"] = up_ticks

                            if not cell["NewsList"]: 
                                threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                                
                            cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                            cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                            cell["up_ticks"] = up_ticks 
                            MASTER_BRAIN["details"][sym] = cell

                    count += 1
                    
                    news_list_temp = []
                    for k_sym, k_cell in MASTER_BRAIN["details"].items():
                        score = k_cell.get("max_news_score", 0)
                        if score != 0 and "latest_item" in k_cell and k_cell.get("last_seen") == current_time_tw:
                            i_copy = k_cell["latest_item"].copy()
                            i_copy["NewsScore"] = score
                            news_list_temp.append(i_copy)
                            
                    news_leaders = sorted(news_list_temp, key=lambda x: x["NewsScore"], reverse=True)[:20]

                    gappers = sorted(t_all, key=lambda x: x["gap_num"], reverse=True)[:20]
                    high_vol = sorted(t_all, key=lambda x: x["rvol_num"], reverse=True)[:20]
                    ipos = sorted([x for x in t_all if x["f_num"] < 10000000], key=lambda x: x["gap_num"], reverse=True)[:20]
                    
                    MASTER_BRAIN.update({
                        "gappers": gappers, "high_vol": high_vol, "ipos": ipos,
                        "hod": (c_hod + MASTER_BRAIN["hod"])[:1000],
                        "surge": (c_surge + MASTER_BRAIN["surge"])[:1000],
                        "news_leaders": news_leaders, 
                        "grinders": (c_grind + MASTER_BRAIN.get("grinders", []))[:1000],
                        "last_update": current_time_tw, "scan_count": count
                    })
            
            time.sleep(random.uniform(5.0, 10.0))
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生錯誤：")
            traceback.print_exc()
            time.sleep(10)

@app.route('/data')
def get_data(): return jsonify(MASTER_BRAIN)
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
