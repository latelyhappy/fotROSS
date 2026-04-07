import time, threading, random
from datetime import datetime, time as dt_time
import pytz
import yfinance as yf
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor

import config

static_task_pool = ThreadPoolExecutor(max_workers=3)
news_task_pool = ThreadPoolExecutor(max_workers=5)
yf_lock = threading.Lock()

auto_hot_symbols = []
feed_gappers = []
feed_surge = []
feed_hod = []

# 新聞關鍵字濾網
CATALYST_KEYWORDS = ['FDA', 'MERGER', 'ACQUISITION', 'BUYOUT', 'EARNINGS', 'PATENT', 'PHASE', 'AGREEMENT', 'CONTRACT', 'PARTNERSHIP', 'TRIAL', 'CLEARANCE', 'APPROVAL', 'REVENUE', 'GUIDANCE', '收購', '財報', '臨床']

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
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            articles = []
            for item in root.findall('./channel/item')[:5]:
                raw_t = item.find('title').text
                link = item.find('link').text
                pubDate = item.find('pubDate').text
                
                dt = parsedate_to_datetime(pubDate).astimezone(tz_ny)
                if (now_ny.date() - dt.date()).days > 4: continue
                is_today = (dt.date() == now_ny.date())
                t_str = dt.strftime("%H:%M") if is_today else dt.strftime("%m-%d %H:%M")
                
                articles.append({
                    "id": str(random.randint(1,9999)), 
                    "title": translate_to_zh(raw_t), 
                    "link": link, "time": t_str, 
                    "is_today": is_today, "pub_ts": dt.timestamp(),
                    "raw_title": raw_t # 保留原文比對關鍵字
                })
            if articles: cell["NewsList"] = articles
    except: pass

def fetch_static_bg(ticker):
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        f = info.get('floatShares') or info.get('sharesOutstanding') or 0
        a = info.get('averageVolume') or info.get('averageDailyVolume10Day') or 500000
        prev = info.get('regularMarketPreviousClose') or info.get('previousClose') or 1.0
        with yf_lock: config.stock_cache[ticker] = (f, a, prev)
    except: pass

def get_static(ticker):
    if ticker in config.stock_cache and config.stock_cache[ticker][0] > 1: return config.stock_cache[ticker]
    config.stock_cache[ticker] = (0, 0, 1.0)
    static_task_pool.submit(fetch_static_bg, ticker)
    return (0, 0, 1.0)

def format_vol_km(v):
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.1f}K"
    return str(int(v))

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
    global feed_surge, feed_hod
    tz_ny = pytz.timezone('America/New_York')
    print("💎 V18.8 啟動 (新增新聞排行榜與 📰 圖示)...", flush=True)
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    count = 0
    while True:
        try:
            symbols = list(set(auto_hot_symbols[:80]))
            if not symbols: time.sleep(2); continue
            
            df = yf.download(symbols, period='1d', interval='1m', prepost=True, progress=False, timeout=15, group_by='ticker')
            
            now_ts = time.time()
            t_news_rank = [] # 用來存新聞排行榜的陣列
            
            for sym in symbols:
                try:
                    if len(symbols) == 1: s_df = df.dropna()
                    else:
                        try: s_df = df[sym].dropna()
                        except: continue
                        
                    if len(s_df) < 15: continue
                    p = float(s_df['Close'].iloc[-1])
                    v_1m = float(s_df['Volume'].iloc[-1])
                    h_1m = float(s_df['High'].iloc[-1])
                    l_1m = float(s_df['Low'].iloc[-1])
                    
                    f, a, prev_c = get_static(sym)
                    daily_v = float(s_df['Volume'].sum())
                    
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
                    
                    tr = max(h_1m - l_1m, abs(h_1m - s_df['Close'].iloc[-2]), abs(l_1m - s_df['Close'].iloc[-2]))
                    cell["tr_hist"].append(tr)
                    if len(cell["tr_hist"]) > 14: cell["tr_hist"].pop(0)
                    atr = sum(cell["tr_hist"]) / len(cell["tr_hist"])
                    
                    label_list = []
                    trigger = False
                    is_hod = False
                    
                    dollar_vol = p * v_1m
                    avg_v_5m = s_df['Volume'].iloc[-6:-1].mean()
                    
                    if v_1m > avg_v_5m * 3 and dollar_vol >= 50000: 
                        label_list.append("🔥強力點火" if dollar_vol > 200000 else "🔥火星塞點火")
                        trigger = True
                    
                    if p > curr_vwap and e9 > e20:
                        if (abs(e9 - e20) / e20) < 0.005: cell["comp_count"] += 1
                        else: cell["comp_count"] = 0
                        if e20 < p < (e9 + 0.1): label_list.append("🚀EMA買區"); trigger = True; cell["in_pb"] = True
                        if cell["in_pb"] and h_1m > s_df['High'].iloc[-2]:
                            label_list.append("🎯關鍵轉折"); trigger = True; cell["in_pb"] = False
                    
                    dist = p - e9
                    if dist > 2.5 * atr: label_list.append("🔴超買禁逃"); trigger = True
                    elif dist > 1.5 * atr: label_list.append("🟡乖離警戒"); trigger = True
                    
                    if pmh > 0 and 0 < (pmh - p) < p * 0.005: label_list.append("⛔PMH壓"); trigger = True
                    
                    if p > cell["HOD"]: 
                        cell["HOD"] = p
                        label_list.append("⭐破高")
                        trigger = True
                        is_hod = True 
                    
                    if p < e20 and s_df['Close'].iloc[-2] >= e20_ser.iloc[-2]: label_list.append("🚨趨勢終結"); trigger = True
                    
                    if trigger:
                        if cell["l_label"] != " ".join(label_list):
                            cell["s_time"], cell["l_label"], cell["peak"] = now_ts, " ".join(label_list), h_1m
                        cell["peak"] = max(cell["peak"], h_1m)
                        if (now_ts - cell["s_time"]) > 180 and h_1m <= cell["peak"]:
                            label_list.append("⏱️動能停滯")

                    # 🚨 新聞圖示與排行榜邏輯
                    has_fresh_news = any(n.get("pub_ts",0) > (now_ts-600) for n in cell["NewsList"])
                    has_catalyst = any(any(kw in n.get("raw_title", "").upper() for kw in CATALYST_KEYWORDS) for n in cell["NewsList"])
                    news_score = sum(1 for n in cell["NewsList"] if n.get("is_today")) * 10 + (50 if has_catalyst else 0)

                    item = {
                        "Time": datetime.now(tz_ny).strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}", 
                        "Change": f"{(p-prev_c)/prev_c*100:+.2f}%" if prev_c>0 else "0.00%", 
                        "Volume": format_vol_km(daily_v), "RVOL": f"{daily_v/a:.1f}x" if a > 1 else "計算中", 
                        "FloatStr": f"{f/1e6:.1f}M" if f > 1 else "計算中", "Streak": " + ".join(label_list), 
                        "HasFreshNews": has_fresh_news, "HasCatalyst": has_catalyst, "NewsScore": news_score
                    }
                    
                    if trigger: feed_surge.insert(0, item)
                    if is_hod: feed_hod.insert(0, item) 
                    if news_score > 0: t_news_rank.append(item) # 有新聞就加入排行榜
                    
                    if count % 25 == 0: news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                except Exception as e: pass
            
            feed_surge = feed_surge[:100]
            feed_hod = feed_hod[:50]
            t_news_rank = sorted(t_news_rank, key=lambda x: x["NewsScore"], reverse=True)[:30] # 依熱度排序
            
            config.MASTER_BRAIN.update({"gappers": feed_gappers[:40], "surge": feed_surge, "hod": feed_hod, "news_rank": t_news_rank, "last_update": datetime.now(tz_ny).strftime('%H:%M:%S')})
            count += 1
            time.sleep(4)
        except: time.sleep(5)
