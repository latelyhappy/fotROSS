import time, threading, requests, os, random
from datetime import datetime, time as dt_time
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

import config

# 配置
static_task_pool = ThreadPoolExecutor(max_workers=5)
yf_lock = threading.Lock()

try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
except ImportError:
    scraper = requests.Session()

auto_hot_symbols = []
feed_gappers = []
feed_surge = []

def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    if now_ny.time() < dt_time(9, 30): return "2", "盤前"
    elif now_ny.time() > dt_time(16, 0): return "1", "盤後"
    else: return "0", "盤中"

def fetch_static_bg(ticker):
    try:
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=defaultKeyStatistics,summaryDetail,price"
        res = scraper.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()['quoteSummary']['result'][0]
            f = data.get('defaultKeyStatistics', {}).get('floatShares', {}).get('raw', 0) or data.get('defaultKeyStatistics', {}).get('sharesOutstanding', {}).get('raw', 0)
            a = data.get('summaryDetail', {}).get('averageVolume', {}).get('raw', 0) or 500000
            prev = data.get('price', {}).get('regularMarketPreviousClose', {}).get('raw', 1.0)
            with yf_lock: config.stock_cache[ticker] = (f, a, prev)
    except: pass

def get_static(ticker):
    if ticker in config.stock_cache and config.stock_cache[ticker][0] > 0: return config.stock_cache[ticker]
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
            rank_type, _ = get_market_rank_type()
            sort_f = "premarket_change" if rank_type == "2" else "change"
            payload = {"filter": [{"left": "close", "operation": "in_range", "right": [0.5, 50]}, {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}], "options": {"lang": "en"}, "markets": ["america"], "columns": ["name", "close", "change", "volume", "premarket_close", "premarket_change", "premarket_volume"], "sort": {"sortBy": sort_f, "sortOrder": "desc"}, "range": [0, 40]}
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
                    rvol = f"{v / avg_v:.1f}x" if avg_v > 0 else "計算中"
                    f_str = f"{f/1e6:.1f}M" if f > 0 else "計算中"
                    for i, e in enumerate(feed_gappers):
                        if e['Code'] == sym: feed_gappers.pop(i); break
                    feed_gappers.insert(0, {"Code": sym, "Price": f"${p:.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%", "Volume": format_vol_km(v), "vol_raw_daily": v, "RVOL": rvol, "FloatStr": f_str, "discovery_time": time.time()})
        except: pass
        time.sleep(5)

# ==========================================
# ★ V18.0 Sniper Ultra 核心引擎
# ==========================================
def scanner_engine():
    global feed_surge
    tz_ny = pytz.timezone('America/New_York')
    print("🔥 啟動 V18.0 Sniper Ultra (ATR自適應 + 流動心地雷 + 時間處決)...", flush=True)
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    count = 0
    while True:
        try:
            now_ny = datetime.now(tz_ny)
            symbols = list(set(auto_hot_symbols[:100]))
            if not symbols: time.sleep(2); continue
            with yf_lock:
                df = yf.download(symbols, period='1d', interval='1m', prepost=True, progress=False, timeout=10, group_by='ticker', threads=10)
            
            t_all = []
            for sym in symbols:
                try:
                    s_df = df[sym].dropna()
                    if len(s_df) < 15: continue
                    
                    p = float(s_df['Close'].iloc[-1])
                    v_1m = float(s_df['Volume'].iloc[-1])
                    h_1m = float(s_df['High'].iloc[-1])
                    l_1m = float(s_df['Low'].iloc[-1])
                    prev_c_1m = float(s_df['Close'].iloc[-2])
                    
                    # 1. 計算 ATR (14分鐘)
                    high_low = h_1m - l_1m
                    high_prev_close = abs(h_1m - prev_c_1m)
                    low_prev_close = abs(l_1m - prev_c_1m)
                    tr = max(high_low, high_prev_close, low_prev_close)
                    
                    cell = config.MASTER_BRAIN["details"].setdefault(sym, {"HOD": p, "in_pb": False, "comp_count": 0, "s_time": 0, "l_label": "", "tr_history": [], "atr": 0.1, "peak_since_trigger": 0})
                    cell["tr_history"].append(tr)
                    if len(cell["tr_history"]) > 14: cell["tr_history"].pop(0)
                    cell["atr"] = sum(cell["tr_history"]) / len(cell["tr_history"])
                    
                    # 2. 均線與 VWAP
                    ema9_ser = s_df['Close'].ewm(span=9, adjust=False).mean()
                    ema20_ser = s_df['Close'].ewm(span=20, adjust=False).mean()
                    e9, e20 = ema9_ser.iloc[-1], ema20_ser.iloc[-1]
                    
                    # 3. 流動性過濾 (金額門檻)
                    dollar_vol = p * v_1m
                    if dollar_vol < 50000: continue # 🛑 低於 5 萬美金直接攔截無視
                    
                    # 4. 物理特徵 (Float, RVOL)
                    f, a, prev_c = get_static(sym)
                    daily_v = max(float(s_df['Volume'].sum()), next((g['vol_raw_daily'] for g in feed_gappers if g['Code']==sym), 0))
                    rvol_n = daily_v / a if a > 0 else 0
                    
                    # 5. 戰術判斷
                    label_list = []
                    trigger = False
                    
                    # 🔥 強力/一般點火
                    avg_v_5m = s_df['Volume'].iloc[-6:-1].mean()
                    rms = v_1m / avg_v_5m if avg_v_5m > 0 else 0
                    if rms > 3.0 and p > e9:
                        label_list.append("🔥強力點火" if dollar_vol > 200000 else "🔥火星塞點火")
                        trigger = True
                    
                    # 🌊 ATR 自適應乖離偵測
                    dist_from_e9 = p - e9
                    if dist_from_e9 > 2.5 * cell["atr"]: label_list.append("🔴超買禁逃"); trigger = True
                    elif dist_from_e9 > 1.5 * cell["atr"]: label_list.append("🟡乖離警戒"); trigger = True
                    
                    # 🎯 關鍵轉折 (第一根新高)
                    if p < e9: cell["in_pb"] = True
                    if cell["in_pb"] and h_1m > s_df['High'].iloc[-2] and p > e9:
                        label_list.append("🎯關鍵轉折"); trigger = True; cell["in_pb"] = False
                    
                    # 🚨 趨勢與 HOD
                    if p < e20 and s_df['Close'].iloc[-2] >= ema20_ser.iloc[-2]: label_list.append("🚨趨勢終結"); trigger = True
                    if p > cell["HOD"]: cell["HOD"] = p; label_list.append("⭐破高"); trigger = True

                    # ⏳ 180 秒動能停滯監控
                    if trigger:
                        if cell["l_label"] != " ".join(label_list):
                            cell["s_time"] = time.time()
                            cell["peak_since_trigger"] = h_1m
                            cell["l_label"] = " ".join(label_list)
                        
                        # 如果 3 分鐘內沒過剛才的高點
                        cell["peak_since_trigger"] = max(cell["peak_since_trigger"], h_1m)
                        if time.time() - cell["s_time"] > 180:
                            if h_1m <= cell["peak_since_trigger"]:
                                label_list.append("⏱️動能停滯")
                                cell["s_time"] = time.time() # 重新計時
                    
                    label = " + ".join(label_list)
                    item = {"Time": now_ny.strftime('%H:%M:%S'), "Code": sym, "Price": f"${p:.2f}", "Change": f"{(p-prev_c)/prev_c*100:+.2f}%", "Volume": format_vol_km(daily_v), "vol_raw": daily_v, "RVOL": f"{rvol_n:.1f}x", "FloatStr": f"{f/1e6:.1f}M" if f>0 else "計算中", "Streak": label, "HasFreshNews": any(n.get("pub_ts",0) > (now_ts-600) for n in cell.get("NewsList",[]))}
                    t_all.append(item)
                    if trigger: feed_surge.insert(0, item)
                    
                    if count % 30 == 0: news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                except: pass
            
            config.MASTER_BRAIN.update({"gappers": feed_gappers[:50], "surge": feed_surge[:50], "high_vol": sorted(t_all, key=lambda x: x['vol_raw'], reverse=True), "last_update": now_ny.strftime('%H:%M:%S'), "scan_count": count})
            count += 1
            time.sleep(3)
        except: time.sleep(5)
