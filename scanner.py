import time, threading, requests, os, random
from datetime import datetime, time as dt_time
import pytz
import yfinance as yf
import pandas as pd
from io import StringIO 
import re
from concurrent.futures import ThreadPoolExecutor

import config

# 🌟 執行緒池配置
static_task_pool = ThreadPoolExecutor(max_workers=5)  
news_task_pool = ThreadPoolExecutor(max_workers=10)   

yf_lock = threading.Lock()

def log_debug(ticker, msg):
    tz_tw = pytz.timezone('Asia/Taipei')
    time_str = datetime.now(tz_tw).strftime('%H:%M:%S')
    print(f"[{time_str}] 🕵️‍♂️ [DEBUG {ticker}] {msg}", flush=True)

# 🛡️ 破甲模式
try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
except ImportError:
    scraper = requests.Session()
    scraper.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"})

auto_hot_symbols = []       
feed_gappers = []           
feed_hod = []               
feed_surge = []             

CATALYST_KEYWORDS = ['FDA', 'MERGER', 'ACQUISITION', 'BUYOUT', 'EARNINGS', 'PATENT', 'PHASE', 'AGREEMENT', 'CONTRACT', 'PARTNERSHIP', 'TRIAL', 'CLEARANCE', 'APPROVAL', 'REVENUE', 'GUIDANCE', '收購', '財報', '臨床']

def translate_to_zh(text):
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "zh-TW", "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            return "".join([sentence[0] for sentence in res.json()[0]])
    except: pass
    return text 

def fetch_direct_news_bg(ticker, cell):
    try:
        if "raw_news_titles" not in cell: cell["raw_news_titles"] = []
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={ticker}&quotesCount=0&newsCount=5"
        res = scraper.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code != 200: return
        news_items = res.json().get('news', [])
        new_articles = []
        for item in news_items:
            raw_title = item.get('title', '').strip()
            pub_ts = item.get('providerPublishTime')
            if not raw_title or not pub_ts or raw_title in cell["raw_news_titles"]: continue
            pub_dt = datetime.fromtimestamp(pub_ts, tz_ny)
            if (now_ny.date() - pub_dt.date()).days > 4: continue 
            translated_title = translate_to_zh(raw_title)
            cell["raw_news_titles"].append(raw_title)
            new_articles.append({"id": str(random.randint(10000, 99999)), "title": translated_title, "score": 0, "link": item.get('link', ''), "time": pub_dt.strftime("%H:%M"), "is_today": (pub_dt.date() == now_ny.date()), "is_read": False, "pub_ts": pub_ts})
        if new_articles:
            clean_old_list = [n for n in cell.get("NewsList", []) if "🗞️" not in n.get("title", "")]
            cell["NewsList"] = (new_articles + clean_old_list)[:5]
    except: pass

def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    if now_ny.time() < dt_time(9, 30): return "2", "盤前"
    elif now_ny.time() > dt_time(16, 0): return "1", "盤後"
    else: return "0", "盤中"

def fetch_static_bg(ticker):
    try:
        with yf_lock:
            i = yf.Ticker(ticker).info
            f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
            a = i.get('averageVolume', 500000)
            prev = i.get('regularMarketPreviousClose', i.get('previousClose', 1.0))
        config.stock_cache[ticker] = (f, a, prev or 1.0)
    except: config.stock_cache[ticker] = (1000000, 500000, 1.0)

def get_static(ticker):
    if ticker in config.stock_cache: return config.stock_cache[ticker]
    config.stock_cache[ticker] = (1000000, 500000, 1.0) 
    static_task_pool.submit(fetch_static_bg, ticker)
    return (1000000, 500000, 1.0)

def format_vol_km(v):
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.1f}K"
    return str(int(v))

def update_or_add_gapper(entry):
    global feed_gappers
    for i, e in enumerate(feed_gappers):
        if e['Code'] == entry['Code']: feed_gappers.pop(i); break
    feed_gappers.insert(0, entry)

def fetch_tv_gainers():
    global auto_hot_symbols, feed_gappers
    while True:
        try:
            rank_type, _ = get_market_rank_type()
            sort_f = "premarket_change" if rank_type == "2" else "change"
            payload = {"filter": [{"left": "close", "operation": "in_range", "right": [0.5, 50]}, {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}], "options": {"lang": "en"}, "markets": ["america"], "columns": ["name", "close", "change", "volume", "premarket_close", "premarket_change", "premarket_volume"], "sort": {"sortBy": sort_f, "sortOrder": "desc"}, "range": [0, 30]}
            res = scraper.post("https://scanner.tradingview.com/america/scan", json=payload, timeout=10)
            if res.status_code == 200:
                for item in reversed(res.json().get("data", [])):
                    cols = item.get("d", [])
                    sym = str(cols[0]).split(':')[-1]
                    if '-' in sym or len(sym) > 4: continue
                    if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                    f, avg_v, prev_c = get_static(sym)
                    p = float(cols[4] if rank_type == "2" else cols[1])
                    v = float(cols[6] if rank_type == "2" else cols[3])
                    rvol = v / avg_v if avg_v > 0 else 0
                    update_or_add_gapper({"Time": datetime.now().strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}", "ChangeAmt": f"{p-prev_c:+.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%", "Volume": format_vol_km(v), "vol_raw_daily": v, "RVOL": f"{rvol:.1f}x", "FloatStr": f"{f/1e6:.1f}M", "discovery_time": time.time()})
            auto_hot_symbols = auto_hot_symbols[:100]
        except: pass
        time.sleep(5)

# ==========================================
# ★ V16.4 Ross Pro 核心引擎
# ==========================================
def scanner_engine():
    global feed_gappers, feed_hod, feed_surge
    tz_ny = pytz.timezone('America/New_York')
    print("🔥 啟動 V16.4 Ross Pro 完全體 (EMA 9/20 + VWAP + PMH + 轉折偵測)...", flush=True)
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    count = 0
    while True:
        try:
            now_ny = datetime.now(tz_ny)
            now_ts = now_ny.timestamp()
            symbols = list(set(auto_hot_symbols[:100]))
            if not symbols: time.sleep(2); continue

            with yf_lock:
                df = yf.download(symbols, period='1d', interval='1m', prepost=True, progress=False, timeout=10, group_by='ticker', threads=10)

            t_all = []
            for sym in symbols:
                try:
                    s_df = df[sym].dropna() if isinstance(df.columns, pd.MultiIndex) else df.dropna()
                    if s_df.empty: continue
                    
                    # 1. 基礎數據
                    p = float(s_df['Close'].iloc[-1])
                    v_1m = float(s_df['Volume'].iloc[-1])
                    h_1m = float(s_df['High'].iloc[-1])
                    
                    # 2. VWAP 計算 (從美東 09:30 開始累積)
                    mkt_open_mask = s_df.index >= s_df.index[0].replace(hour=9, minute=30, second=0)
                    open_df = s_df[mkt_open_mask]
                    curr_vwap = 0
                    if not open_df.empty:
                        vwap_series = (open_df['Close'] * open_df['Volume']).cumsum() / open_df['Volume'].cumsum()
                        curr_vwap = float(vwap_series.iloc[-1])
                    
                    # 3. EMA 9 & EMA 20 (Ross 核心雙線)
                    ema9 = s_df['Close'].ewm(span=9, adjust=False).mean()
                    ema20 = s_df['Close'].ewm(span=20, adjust=False).mean()
                    e9, e20 = float(ema9.iloc[-1]), float(ema20.iloc[-1])
                    e9_prev, e20_prev = float(ema9.iloc[-2]), float(ema20.iloc[-2])
                    
                    # 4. PMH (盤前高點)
                    pm_df = s_df[s_df.index < s_df.index[0].replace(hour=9, minute=30, second=0)]
                    pmh = float(pm_df['High'].max()) if not pm_df.empty else 0
                    
                    # 5. 數據對接
                    daily_v_num, daily_v_str, rvol_s, rvol_n, f_str, f_num = 0, "0K", "0.0x", 0, "0M", 0
                    for g in feed_gappers:
                        if g['Code'] == sym:
                            daily_v_num, daily_v_str, rvol_s = g['vol_raw_daily'], g['Volume'], g['RVOL']
                            rvol_n = float(rvol_s.replace('x',''))
                            f_str = g['FloatStr']
                            f_num = float(f_str.replace('M','')) * 1e6
                            break

                    # 🚨 Ross Pro 判斷邏輯
                    cell = config.MASTER_BRAIN["details"].setdefault(sym, {"HOD": p, "NewsList": [], "last_p": p, "last_h": h_1m, "in_pb": False, "s_time": 0, "l_label": ""})
                    
                    label, trigger = "", False
                    
                    # (A) 瞬間成交量脈衝 (1分鐘量 > 前3分鐘平均 3 倍)
                    if len(s_df) >= 4:
                        avg_v_prev = s_df['Volume'].iloc[-4:-1].mean()
                        if v_1m > avg_v_prev * 3 and v_1m > 10000: label, trigger = "⚡資金爆發", True
                    
                    # (B) EMA 9/20 買入區間 + VWAP 多頭濾網
                    if p > curr_vwap and e9 > e9_prev and e20 > e20_prev:
                        # 價格進入 EMA 9 與 20 之間的黃金緩衝區
                        if e20 < p < (e9 + 0.1) and daily_v_num > 300000:
                            label, trigger = "🚀EMA 9/20買區", True
                            cell["in_pb"] = True
                            
                        # (C) 第一根 K 線新高 (回踩後的轉折點)
                        if cell["in_pb"] and h_1m > s_df['High'].iloc[-2] and p > e9:
                            label, trigger = "🎯第一根K新高", True
                            cell["in_pb"] = False
                    
                    # (D) PMH 壓力偵測
                    if pmh > 0 and 0 < (pmh - p) < p * 0.005: label, trigger = "⛔PMH壓力近", True

                    # (E) HOD 突破
                    if p > cell["HOD"]: 
                        cell["HOD"] = p
                        label, trigger = "⚠️爆量突破" if v_1m > surge_vol_threshold else "⭐破高", True

                    # 🚨 180秒超時註銷機制
                    if trigger:
                        if cell["l_label"] != label:
                            cell["s_time"], cell["l_label"] = time.time(), label
                        if time.time() - cell["s_time"] > 180:
                            trigger, label = False, ""
                    else:
                        cell["s_time"], cell["l_label"] = 0, ""

                    has_news = any(n.get("pub_ts", 0) > (now_ts - 600) for n in cell["NewsList"])
                    has_catalyst = any(kw in str(cell["NewsList"]).upper() for kw in CATALYST_KEYWORDS)

                    item = {
                        "Time": now_ny.strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}",
                        "Change": f"{(p-get_static(sym)[2])/get_static(sym)[2]*100:+.2f}%",
                        "Volume": daily_v_str, "vol_raw": daily_v_num, "RVOL": rvol_s, "RvolNum": rvol_n,
                        "FloatStr": f_str, "FloatNum": f_num, "Streak": label,
                        "HasFreshNews": has_news, "HasCatalyst": has_catalyst, "NewsScore": len(cell["NewsList"])*10
                    }
                    t_all.append(item)
                    if "破高" in label or "突破" in label: feed_hod.insert(0, item)
                    if trigger: feed_surge.insert(0, item)
                    
                    if count % 30 == 0 or not cell["NewsList"]: news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                    cell["last_p"], cell["last_h"] = p, h_1m
                except: pass

            config.MASTER_BRAIN.update({
                "gappers": sorted(feed_gappers, key=lambda x: x['discovery_time'], reverse=True)[:100],
                "hod": feed_hod[:100], "surge": feed_surge[:100],
                "high_vol": sorted(t_all, key=lambda x: x['vol_raw'], reverse=True),
                "last_update": now_ny.strftime('%H:%M:%S'), "scan_count": count
            })
            count += 1
            time.sleep(3)
        except Exception as e: time.sleep(5)
