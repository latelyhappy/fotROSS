import time, threading, requests, os, random
from datetime import datetime, time as dt_time
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

import config

# 配置執行緒池與鎖
static_task_pool = ThreadPoolExecutor(max_workers=3)
news_task_pool = ThreadPoolExecutor(max_workers=5)
yf_lock = threading.Lock()

# 🛡️ 加強型代理 Session
def get_safe_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://finance.yahoo.com",
        "Referer": "https://finance.yahoo.com/"
    })
    return s

safe_session = get_safe_session()

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
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={ticker}&quotesCount=0&newsCount=5"
        res = safe_session.get(url, timeout=7)
        if res.status_code != 200: return
        items = res.json().get('news', [])
        articles = []
        for item in items:
            raw_t = item.get('title', '').strip()
            ts = item.get('providerPublishTime')
            if not raw_t or not ts: continue
            dt = datetime.fromtimestamp(ts, tz_ny)
            if (now_ny.date() - dt.date()).days > 4: continue
            is_today = (dt.date() == now_ny.date())
            t_str = dt.strftime("%H:%M") if is_today else dt.strftime("%m-%d %H:%M")
            articles.append({"id": str(random.randint(1,9999)), "title": translate_to_zh(raw_t), "link": item.get('link', ''), "time": t_str, "is_today": is_today, "pub_ts": ts})
        if articles: cell["NewsList"] = articles
    except: pass

def fetch_static_bg(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=defaultKeyStatistics,summaryDetail,price"
        res = safe_session.get(url, timeout=8)
        if res.status_code == 200:
            res_data = res.json()['quoteSummary']['result'][0]
            f = res_data.get('defaultKeyStatistics', {}).get('floatShares', {}).get('raw', 0) or res_data.get('defaultKeyStatistics', {}).get('sharesOutstanding', {}).get('raw', 1000000)
            a = res_data.get('summaryDetail', {}).get('averageVolume', {}).get('raw', 0) or 500000
            prev = res_data.get('price', {}).get('regularMarketPreviousClose', {}).get('raw', 1.0)
            with yf_lock: config.stock_cache[ticker] = (f, a, prev)
            return
    except: pass

def get_static(ticker):
    if ticker in config.stock_cache and config.stock_cache[ticker][0] > 1: return config.stock_cache[ticker]
    config.stock_cache[ticker] = (1, 1, 1.0) # 標記為獲取中
    static_task_pool.submit(fetch_static_bg, ticker)
    return (1, 1, 1.0)

def format_vol_km(v):
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.1f}K"
    return str(int(v))

auto_hot_symbols = []
feed_gappers = []
feed_surge = []

def fetch_tv_gainers():
    global auto_hot_symbols, feed_gappers
    while True:
        try:
            tz_ny = pytz.timezone('America/New_York')
            rank_type = "2" if datetime.now(tz_ny).time() < dt_time(9, 30) else "0"
            sort_f = "premarket_change" if rank_type == "2" else "change"
            payload = {"filter": [{"left": "close", "operation": "in_range", "right": [0.5, 50]}, {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}], "options": {"lang": "en"}, "markets": ["america"], "columns": ["name", "close", "change", "volume", "premarket_close", "premarket_change", "premarket_volume"], "sort": {"sortBy": sort_f, "sortOrder": "desc"}, "range": [0, 40]}
            res = requests.post("https://scanner.tradingview.com/america/scan", json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json().get("data", [])
                for item in reversed(data):
                    cols = item.get("d", [])
                    sym = str(cols[0]).split(':')[-1]
                    if '-' in sym or len(sym) > 4: continue
                    if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                    f, avg_v, prev_c = get_static(sym)
                    p = float(cols[4] if rank_type == "2" else cols[1])
                    v = float(cols[6] if rank_type == "2" else cols[3])
                    update_entry = {"Code": sym, "Price": f"${p:.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%", "Volume": format_vol_km(v), "vol_raw_daily": v, "RVOL": f"{v/avg_v:.1f}x" if avg_v > 1 else "計算中", "FloatStr": f"{f/1e6:.1f}M" if f > 1 else "計算中", "discovery_time": time.time()}
                    for i, e in enumerate(feed_gappers):
                        if e['Code'] == sym: feed_gappers.pop(i); break
                    feed_gappers.insert(0, update_entry)
            auto_hot_symbols = auto_hot_symbols[:80]
        except: pass
        time.sleep(10)

def scanner_engine():
    global feed_surge
    tz_ny = pytz.timezone('America/New_York')
    print("💎 V18.5 Sniper Pro 大滿貫版已啟動...", flush=True)
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    count = 0
    while True:
        try:
            symbols = list(set(auto_hot_symbols[:80]))
            if not symbols: time.sleep(2); continue
            df = yf.download(symbols, period='1d', interval='1m', prepost=True, progress=False, timeout=15)
            
            t_all = []
            now_ts = time.time()
            for sym in symbols:
                try:
                    s_df = df[sym].dropna() if isinstance(df.columns, pd.MultiIndex) else df.dropna()
                    if len(s_df) < 15: continue
                    p = float(s_df['Close'].iloc[-1])
                    v_1m = float(s_df['Volume'].iloc[-1])
                    h_1m = float(s_df['High'].iloc[-1])
                    l_1m = float(s_df['Low'].iloc[-1])
                    
                    f, a, prev_c = get_static(sym)
                    daily_v = float(s_df['Volume'].sum())
                    
                    # 均線與 VWAP
                    e9_ser = s_df['Close'].ewm(span=9, adjust=False).mean()
                    e20_ser = s_df['Close'].ewm(span=20, adjust=False).mean()
                    e9, e20 = e9_ser.iloc[-1], e20_ser.iloc[-1]
                    
                    open_mask = s_df.index >= s_df.index[0].replace(hour=9, minute=30, second=0)
                    open_df = s_df[open_mask]
                    vwap = (open_df['Close'] * open_df['Volume']).cumsum() / open_df['Volume'].cumsum() if not open_df.empty else pd.Series([0])
                    curr_vwap = float(vwap.iloc[-1])
                    
                    pm_df = s_df[s_df.index < s_df.index[0].replace(hour=9, minute=30, second=0)]
                    pmh = float(pm_df['High'].max()) if not pm_df.empty else 0
                    
                    cell = config.MASTER_BRAIN["details"].setdefault(sym, {"HOD": p, "NewsList": [], "in_pb": False, "s_time": 0, "l_label": "", "tr_hist": [], "comp_count": 0, "peak": h_1m})
                    
                    # ATR 計算
                    tr = max(h_1m - l_1m, abs(h_1m - s_df['Close'].iloc[-2]), abs(l_1m - s_df['Close'].iloc[-2]))
                    cell["tr_hist"].append(tr)
                    if len(cell["tr_hist"]) > 14: cell["tr_hist"].pop(0)
                    atr = sum(cell["tr_hist"]) / len(cell["tr_hist"])
                    
                    label_list = []
                    trigger = False
                    
                    # 1. 流動性過濾
                    dollar_vol = p * v_1m
                    if dollar_vol >= 50000:
                        # 2. 脈衝與突破
                        avg_v_5m = s_df['Volume'].iloc[-6:-1].mean()
                        if v_1m > avg_v_5m * 3: 
                            label_list.append("🔥強力點火" if dollar_vol > 200000 else "🔥火星塞點火")
                            trigger = True
                        
                        # 3. Ross 均線策略
                        if p > curr_vwap and e9 > e20:
                            # 壓縮偵測
                            if (abs(e9 - e20) / e20) < 0.005: cell["comp_count"] += 1
                            else: cell["comp_count"] = 0
                            
                            # EMA 買區
                            if e20 < p < (e9 + 0.1): label_list.append("🚀EMA買區"); trigger = True; cell["in_pb"] = True
                            
                            # 🎯 第一根 K 新高
                            if cell["in_pb"] and h_1m > s_df['High'].iloc[-2]:
                                label_list.append("🎯關鍵轉折"); trigger = True; cell["in_pb"] = False
                        
                        # 4. ATR 乖離
                        dist = p - e9
                        if dist > 2.5 * atr: label_list.append("🔴超買禁逃"); trigger = True
                        elif dist > 1.5 * atr: label_list.append("🟡乖離警戒"); trigger = True
                        
                        # 5. PMH 與 HOD
                        if pmh > 0 and 0 < (pmh - p) < p * 0.005: label_list.append("⛔PMH壓"); trigger = True
                        if p > cell["HOD"]: cell["HOD"] = p; label_list.append("⭐破高"); trigger = True
                        
                        # 6. 停損與動能停滯
                        if p < e20 and s_df['Close'].iloc[-2] >= e20_ser.iloc[-2]: label_list.append("🚨趨勢終結"); trigger = True
                        
                        # 180s 處決邏輯
                        if trigger:
                            if cell["l_label"] != " ".join(label_list):
                                cell["s_time"], cell["l_label"], cell["peak"] = now_ts, " ".join(label_list), h_1m
                            cell["peak"] = max(cell["peak"], h_1m)
                            if (now_ts - cell["s_time"]) > 180 and h_1m <= cell["peak"]:
                                label_list.append("⏱️動能停滯")

                    if trigger:
                        item = {"Time": datetime.now(tz_ny).strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%" if prev_c>0 else "0.00%", "Volume": format_vol_km(daily_v), "RVOL": f"{daily_v/a:.1f}x" if a > 1 else "計算中", "FloatStr": f"{f/1e6:.1f}M" if f > 1 else "計算中", "FloatNum": f, "Streak": " + ".join(label_list), "HasFreshNews": any(n.get("pub_ts",0) > (now_ts-600) for n in cell["NewsList"])}
                        feed_surge.insert(0, item)
                    
                    if count % 25 == 0: news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                except: pass
            
            feed_surge = feed_surge[:100]
            config.MASTER_BRAIN.update({"gappers": feed_gappers[:40], "surge": feed_surge, "last_update": datetime.now(tz_ny).strftime('%H:%M:%S')})
            count += 1
            time.sleep(4)
        except: time.sleep(5)
