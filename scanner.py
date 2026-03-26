import time, threading, requests, os
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright

import config
from news_engine import fetch_news_bg

WATCHLIST_FILE = "watchlist.txt"

# ⚠️ [除錯特製]：強制塞入預設名單，確保系統一定有東西可以算！
auto_hot_symbols = ["TSLA", "NVDA"] 

if not os.path.exists(WATCHLIST_FILE):
    with open(WATCHLIST_FILE, "w") as f:
        f.write("")

def get_manual_symbols():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return [line.strip().upper() for line in f.readlines() if line.strip()]
    except:
        return []

def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    if now_ny.time() < datetime.strptime("09:30", "%H:%M").time(): return "2", "盤前"
    elif now_ny.time() > datetime.strptime("16:00", "%H:%M").time(): return "1", "盤後"
    else: return "0", "盤中"

def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        config.stock_cache[ticker] = (f, 500000, 1.0)
    except:
        config.stock_cache[ticker] = (1000000, 500000, 1.0)

def get_static(ticker):
    if ticker in config.stock_cache: return config.stock_cache[ticker]
    else:
        config.stock_cache[ticker] = (1000000, 500000, 1.0) 
        threading.Thread(target=fetch_static_bg, args=(ticker,), daemon=True).start()
        return (1000000, 500000, 1.0)

def format_vol_km(v_float):
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
    else: return f"{int(v_float)}"

# ==========================================
# ★ 核心模組 1：隱形瀏覽器
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols
    tz_tw = pytz.timezone('Asia/Taipei')
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ 嘗試潛入 Webull...")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
                page = context.new_page()
                page.goto("https://app.webull.com/", timeout=30000)
                time.sleep(3) 
                api_url = f"https://quoteapi.webullfinance.com/api/market/v1/market/ranking/gainers?regionId=6&secType=12&rankType={rank_type}&pageIndex=1&pageSize=30"
                js_code = f"async () => {{ const response = await fetch('{api_url}'); return await response.json(); }}"
                data = page.evaluate(js_code)
                browser.close()
                
                symbols = [item.get('ticker', {}).get('symbol') for item in data.get('data', [])]
                symbols = [s for s in symbols if s and '-' not in s]
                
                if symbols:
                    auto_hot_symbols = symbols # 覆蓋掉預設的 TSLA, NVDA
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ✅ Webull 攔截成功: {symbols[:5]}...")
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 Webull 潛入失敗: {e} (繼續使用預設/手動名單)")
        time.sleep(30)

# ==========================================
# ★ 核心模組 2：高頻狙擊鏡 (除錯廣播版)
# ==========================================
def scanner_engine():
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動高頻狙擊鏡 (除錯廣播模式)...")
    
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            combined_symbols = list(set(auto_hot_symbols + get_manual_symbols()))
            
            if not combined_symbols:
                print(f"[{current_time_tw}] ⏳ 無代碼可追蹤。")
                time.sleep(2)
                continue
                
            print(f"[{current_time_tw}] 🔍 正在向 Yahoo 索取 {len(combined_symbols)} 檔股票 K 線: {combined_symbols[:5]}...")
            data_df = yf.download(combined_symbols, period='1d', interval='1m', prepost=True, progress=False)
            
            extracted_stocks = []
            if not data_df.empty:
                is_single = len(combined_symbols) == 1
                for sym in combined_symbols:
                    try:
                        latest_row = data_df.iloc[-1] if is_single else data_df.xs(sym, level=1, axis=1).iloc[-1]
                        price = float(latest_row['Close'])
                        vol = float(latest_row['Volume'])
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({
                                'sym': sym, 'price': price, 'change_str': "運算中", 
                                'vol_raw': vol, 'rvol_tw': vol / 50000.0
                            })
                    except:
                        continue

            t_all, c_hod, c_surge = [], [], []
            current_t = time.time()
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                vol_raw = data['vol_raw']
                
                f, a, prev = get_static(sym)
                is_new = sym not in config.MASTER_BRAIN["details"]
                initial_hod = (p_num * 0.98) if is_new else p_num
                
                cell = config.MASTER_BRAIN["details"].get(sym, {
                    "HOD": initial_hod, "NewsList": [], "streak": 0, "last_price": p_num, 
                    "cum_buy_vol": 0, "cum_sell_vol": 0, "recent_high": initial_hod, 
                    "surge_start_price": initial_hod, "pullback_low": p_num
                })
                
                is_hod_break = False
                if p_num > cell["HOD"]: cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                
                curr_vol_delta = vol_raw
                if p_num > cell["last_price"]: cell["cum_buy_vol"] += curr_vol_delta
                elif p_num < cell["last_price"]: cell["cum_sell_vol"] += curr_vol_delta
                net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]

                # 簡化版燈號判斷
                streak_label = f"x{cell['streak']}"
                if cell["streak"] >= 2: streak_label = "⭐破高"
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "Change": "0.0%", "Volume": format_vol_km(vol_raw), 
                    "RVOL": f"{data['rvol_tw']:.1f}x", "Gap": "0.0%", "Drop": "0.0%",
                    "FloatStr": f"{f/1e6:.1f}M", "Streak": streak_label, 
                    "NetVolNum": net_vol,
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]),
                    "SellVolStr": format_vol_km(cell["cum_sell_vol"])
                }

                t_all.append(item)
                cell["last_price"] = p_num
                config.MASTER_BRAIN["details"][sym] = cell
                
                if is_hod_break: c_hod.append(item)
                if cell["streak"] >= 2: c_surge.append(item)

            count += 1
            
            # 確保所有前端需要的欄位都有給予空陣列防呆
            config.MASTER_BRAIN.update({
                "gappers": t_all[:20], 
                "hod": c_hod[:50],
                "surge": c_surge[:50],
                "high_vol": [], "news_leaders": [], "grinders": [], "net_vol_leaders": [],
                "last_update": current_time_tw, "scan_count": count
            })
            
            print(f"[{current_time_tw}] 📤 準備打包送往前端的資料: 雷達區 {len(t_all)} 筆 | 破高區 {len(c_hod)} 筆")
            time.sleep(2.0)
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤：{e}")
            time.sleep(5)