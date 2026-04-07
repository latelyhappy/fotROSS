import time, threading, requests, os, random
from datetime import datetime, time as dt_time
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

import config

# 配置執行緒池
static_task_pool = ThreadPoolExecutor(max_workers=3) # 降低並發以防被鎖
news_task_pool = ThreadPoolExecutor(max_workers=5)
yf_lock = threading.Lock()

# 🛡️ 增強型抓取器
def get_scraper():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return s

scraper = get_scraper()

def translate_to_zh(text):
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "zh-TW", "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200: return "".join([sentence[0] for sentence in res.json()[0]])
    except: pass
    return text

def fetch_direct_news_bg(ticker, cell):
    try:
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        # 更新新聞 Endpoint
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={ticker}&quotesCount=0&newsCount=5"
        res = scraper.get(url, timeout=5)
        if res.status_code != 200: return
        news_items = res.json().get('news', [])
        new_articles = []
        for item in news_items:
            raw_title = item.get('title', '').strip()
            pub_ts = item.get('providerPublishTime')
            if not raw_title or not pub_ts: continue
            pub_dt = datetime.fromtimestamp(pub_ts, tz_ny)
            if (now_ny.date() - pub_dt.date()).days > 4: continue
            is_today = (pub_dt.date() == now_ny.date())
            time_str = pub_dt.strftime("%H:%M") if is_today else pub_dt.strftime("%m-%d %H:%M")
            new_articles.append({"id": str(random.randint(10000, 99999)), "title": translate_to_zh(raw_title), "link": item.get('link', ''), "time": time_str, "is_today": is_today, "pub_ts": pub_ts})
        if new_articles: cell["NewsList"] = new_articles
    except: pass

def fetch_static_bg(ticker):
    try:
        # 🛡️ 偽裝型請求
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=defaultKeyStatistics,summaryDetail,price"
        res = scraper.get(url, timeout=7)
        if res.status_code == 200:
            res_data = res.json()['quoteSummary']['result'][0]
            f = res_data.get('defaultKeyStatistics', {}).get('floatShares', {}).get('raw', 0) or res_data.get('defaultKeyStatistics', {}).get('sharesOutstanding', {}).get('raw', 1000000)
            a = res_data.get('summaryDetail', {}).get('averageVolume', {}).get('raw', 0) or 500000
            prev = res_data.get('price', {}).get('regularMarketPreviousClose', {}).get('raw', 1.0)
            with yf_lock: config.stock_cache[ticker] = (f, a, prev)
            return
    except: pass
    time.sleep(random.uniform(0.5, 1.5)) # 隨機延遲防鎖

def get_static(ticker):
    if ticker in config.stock_cache and config.stock_cache[ticker][0] > 0: return config.stock_cache[ticker]
    config.stock_cache[ticker] = (1, 1, 1.0) # 預設最小數值防止除以零
    static_task_pool.submit(fetch_static_bg, ticker)
    return config.stock_cache[ticker]

# 跳空榜數據
auto_hot_symbols = []
feed_gappers = []
feed_surge = []

def fetch_tv_gainers():
    global auto_hot_symbols, feed_gappers
    while True:
        try:
            rank_type = "2" if datetime.now(pytz.timezone('America/New_York')).time() < dt_time(9, 30) else "0"
            sort_f = "premarket_change" if rank_type == "2" else "change"
            payload = {"filter": [{"left": "close", "operation": "in_range", "right": [0.5, 50]}, {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}], "options": {"lang": "en"}, "markets": ["america"], "columns": ["name", "close", "change", "volume", "premarket_close", "premarket_change", "premarket_volume"], "sort": {"sortBy": sort_f, "sortOrder": "desc"}, "range": [0, 40]}
            res = requests.post("https://scanner.tradingview.com/america/scan", json=payload, timeout=10)
            if res.status_code == 200:
                for item in reversed(res.json().get("data", [])):
                    cols = item.get("d", [])
                    sym = str(cols[0]).split(':')[-1]
                    if '-' in sym or len(sym) > 4: continue
                    if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                    f, avg_v, prev_c = get_static(sym)
                    p = float(cols[4] if rank_type == "2" else cols[1])
                    v = float(cols[6] if rank_type == "2" else cols[3])
                    for i, e in enumerate(feed_gappers):
                        if e['Code'] == sym: feed_gappers.pop(i); break
                    feed_gappers.insert(0, {"Code": sym, "Price": f"${p:.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%", "Volume": str(int(v)), "vol_raw_daily": v, "RVOL": f"{v/avg_v:.1f}x" if avg_v > 0 else "計算中", "FloatStr": f"{f/1e6:.1f}M", "discovery_time": time.time()})
        except: pass
        time.sleep(10)

def scanner_engine():
    global feed_surge
    tz_ny = pytz.timezone('America/New_York')
    print("🚀 V18.1 緊急修復：加強型數據源連線中...", flush=True)
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    count = 0
    while True:
        try:
            symbols = list(set(auto_hot_symbols[:80])) # 降低單次數量
            if not symbols: time.sleep(2); continue
            df = yf.download(symbols, period='1d', interval='1m', prepost=True, progress=False, timeout=15, threads=5)
            
            t_all = []
            for sym in symbols:
                try:
                    s_df = df[sym].dropna() if isinstance(df.columns, pd.MultiIndex) else df.dropna()
                    if len(s_df) < 5: continue
                    p = float(s_df['Close'].iloc[-1])
                    v_1m = float(s_df['Volume'].iloc[-1])
                    
                    f, a, prev_c = get_static(sym)
                    daily_v = float(s_df['Volume'].sum())
                    
                    cell = config.MASTER_BRAIN["details"].setdefault(sym, {"HOD": p, "NewsList": [], "in_pb": False, "s_time": 0})
                    
                    # 判斷邏輯保持 V18.0 核心 (點火, 轉折, 乖離)
                    label_list = []
                    trigger = False
                    
                    if p * v_1m > 50000: # 5萬美金門檻
                        if v_1m > s_df['Volume'].iloc[-5:-1].mean() * 3: label_list.append("🔥火星塞點火"); trigger = True
                        if p > cell["HOD"]: cell["HOD"] = p; label_list.append("⭐破高"); trigger = True
                    
                    if trigger: feed_surge.insert(0, {"Time": datetime.now(tz_ny).strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}", "Volume": str(int(daily_v)), "RVOL": f"{daily_v/a:.1f}x" if a > 0 else "...", "FloatStr": f"{f/1e6:.1f}M", "Streak": " + ".join(label_list)})
                    
                    if count % 20 == 0: news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                except: pass
            count += 1
            config.MASTER_BRAIN.update({"gappers": feed_gappers[:30], "surge": feed_surge[:50], "last_update": datetime.now(tz_ny).strftime('%H:%M:%S')})
            time.sleep(5)
        except: time.sleep(5)
