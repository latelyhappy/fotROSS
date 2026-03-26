import time, threading, requests, os
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright

import config
from news_engine import fetch_news_bg

WATCHLIST_FILE = "watchlist.txt"
auto_hot_symbols = [] # 存放隱形瀏覽器抓來的名單

# 確保手動監聽檔案存在
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
    current_time = now_ny.time()
    
    if current_time < datetime.strptime("09:30", "%H:%M").time(): return "2", "盤前時段"
    elif current_time > datetime.strptime("16:00", "%H:%M").time(): return "1", "盤後時段"
    else: return "0", "一般盤中"

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
# ★ 核心模組 1：隱形瀏覽器潛入系統 (Playwright)
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ 啟動隱形瀏覽器潛入 Webull ({market_status})...")
            
            with sync_playwright() as p:
                # 啟動隱形 Chrome，--no-sandbox 是雲端主機必備參數
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                
                # 1. 戰術欺敵：前往首頁獲取通行證
                page.goto("https://app.webull.com/", timeout=30000)
                time.sleep(3) 
                
                # 2. 鎖定地下 API
                api_url = f"https://quoteapi.webullfinance.com/api/market/v1/market/ranking/gainers?regionId=6&secType=12&rankType={rank_type}&pageIndex=1&pageSize=30"
                
                # 3. 攔截數據
                js_code = f"""
                async () => {{
                    const response = await fetch('{api_url}');
                    return await response.json();
                }}
                """
                data = page.evaluate(js_code)
                browser.close()
                
                symbols = []
                for item in data.get('data', []):
                    sym = item.get('ticker', {}).get('symbol')
                    if sym and '-' not in sym: 
                        symbols.append(sym)
                
                if symbols:
                    auto_hot_symbols = symbols
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ✅ 隱形瀏覽器攔截成功！鎖定目標: {symbols[:5]}...")
                else:
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ⚠️ 攔截成功，但目前無波動名單。")
                    
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 隱形瀏覽器遭遇阻礙: {e}")
            
        time.sleep(30)

# ==========================================
# ★ 核心模組 2：Yahoo 高頻狙擊鏡 (融合名單)
# ==========================================
def scanner_engine():
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動 V5.0 隱形戰艦版 (Playwright 自動雷達 + 手動狙擊)...")
    
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    wait_count = 0
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            manual_symbols = get_manual_symbols()
            combined_symbols = list(set(auto_hot_symbols + manual_symbols))
            
            if not combined_symbols:
                if wait_count % 5 == 0:
                    print(f"[{current_time_tw}] ⏳ 狙擊鏡待命中，等待隱形瀏覽器回傳目標...")
                wait_count += 1
                time.sleep(2)
                continue
                
            wait_count = 0
            symbols_to_track = combined_symbols
            
            # 使用 yfinance 抓取 1 分鐘 K 線 (已移除 show_errors=False 避免報錯)
            data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False)
            
            extracted_stocks = []
            if not data_df.empty:
                is_single = len(symbols_to_track) == 1
                for sym in symbols_to_track:
                    try:
                        if is_single:
                            latest_row = data_df.iloc[-1]
                        else:
                            latest_row = data_df.xs(sym, level=1, axis=1).iloc[-1]
                            
                        price = float(latest_row['Close'])
                        vol = float(latest_row['Volume'])
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({
                                'sym': sym, 'price': price, 'change_str': "自動/手動", 
                                'vol_raw': vol, 'rvol_tw': vol / 50000.0
                            })
                    except:
                        continue

            t_all, c_hod, c_surge, c_grind = [], [], [], []
            current_t = time.time()
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                change_str = data['change_str']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw']
                
                f, a, prev = get_static(sym)
                formatted_volume = format_vol_km(vol_raw)
                
                is_new_stock = sym not in config.MASTER_BRAIN["details"]
                initial_hod = (p_num * 0.98) if is_new_stock else p_num
                
                cell = config.MASTER_BRAIN["details"].get(sym, {
                    "HOD": initial_hod, "NewsList": [], "max_news_score": 0, "streak": 0, "last_act": "",
                    "last_price": p_num, "last_vol": vol_raw, "last_vol_delta": 0,
                    "up_ticks": 0, "cum_buy_vol": 0, "cum_sell_vol": 0,
                    "pos_vol_streak": 0, "neg_vol_streak": 0, "is_grinder": False,
                    "recent_high": initial_hod, "is_pullback": False, "sniper_triggered": False,
                    "surge_start_price": initial_hod, "max_surge_vol": 0, 
                    "pullback_start_time": 0, "pullback_min_vol": 9999999,
                    "surge_wave_count": 0, "pullback_low": p_num, "sniper_label": ""
                })
                
                is_hod_break = False
                if p_num > cell["HOD"]: cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                last_price = cell.get("last_price", p_num)
                curr_vol_delta = vol_raw
                
                if curr_vol_delta > 0:
                    if p_num > last_price: cell["cum_buy_vol"] += curr_vol_delta
                    elif p_num < last_price: cell["cum_sell_vol"] += curr_vol_delta
                net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]

                recent_high = cell.get("recent_high", initial_hod)
                surge_start_price = cell.get("surge_start_price", initial_hod)
                max_surge_vol = cell.get("max_surge_vol", 0)
                pullback_start_time = cell.get("pullback_start_time", 0)
                pullback_min_vol = cell.get("pullback_min_vol", 9999999)
                is_pullback = cell.get("is_pullback", False)
                sniper_triggered = False
                sniper_label = ""
                
                if p_num > recent_high:
                    if is_pullback:
                        swing_size = recent_high - surge_start_price
                        pb_low = cell.get("pullback_low", p_num)
                        if p_num > pb_low * 1.01: 
                            sniper_triggered = True
                            cell["surge_wave_count"] = cell.get("surge_wave_count", 0) + 1
                            sniper_label = "⚡極速(9EMA)"
                        is_pullback = False
                        surge_start_price = p_num 
                        max_surge_vol = curr_vol_delta 
                    else:
                        max_surge_vol = max(max_surge_vol, curr_vol_delta)
                    recent_high = p_num
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    if retrace_ratio <= 0.50:
                        if not is_pullback:
                            is_pullback = True
                            pullback_start_time = current_t
                            pullback_min_vol = curr_vol_delta
                            cell["pullback_low"] = p_num
                        else:
                            pullback_min_vol = min(pullback_min_vol, curr_vol_delta)
                            cell["pullback_low"] = min(cell.get("pullback_low", p_num), p_num)
                    else:
                        is_pullback = False 

                bull_trap = False
                if is_hod_break and net_vol < 0: bull_trap = True

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
                cell["max_surge_vol"] = max_surge_vol
                cell["pullback_start_time"] = pullback_start_time
                cell["pullback_min_vol"] = pullback_min_vol
                cell["is_pullback"] = is_pullback
                cell["sniper_triggered"] = sniper_triggered
                if sniper_triggered: cell["sniper_label"] = sniper_label
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "Change": change_str, "Volume": formatted_volume, 
                    "RVOL": f"{rvol:.1f}x", "Gap": "0.0%", "Drop": f"{((p_num - cell['HOD'])/cell['HOD']*100):.1f}%" if cell['HOD']>0 else "0.0%",
                    "FloatStr": float_str, "Streak": f"x{cell['streak']}", 
                    "gap_num": 0, "rvol_num": rvol, "f_num": f,
                    "NetVolNum": net_vol,
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]),
                    "SellVolStr": format_vol_km(cell["cum_sell_vol"])
                }

                t_all.append(item)
                cell["latest_item"] = item
                cell["last_seen"] = current_time_tw
                    
                if is_hod_break: 
                    item_hod = item.copy()
                    item_hod["Streak"] = f"⭐破高x{cell['streak']}"
                    c_hod.append(item_hod)

                if sniper_triggered or (cell["streak"] >= 2 and is_hod_break):
                    item_surge = item.copy()
                    if sniper_triggered:
                        wave = cell.get("surge_wave_count", 1)
                        label = cell.get("sniper_label", "🎯精準狙擊")
                        item_surge["Streak"] = f"{label} (第{wave}波)"
                    else: 
                        item_surge["Streak"] = f"⭐破高x{cell['streak']}"
                    c_surge.append(item_surge)

                if not cell["NewsList"]: 
                    cell["NewsList"] = [{"id": "0", "title": "...", "score": 0, "link": "#", "time": ""}]
                    threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            config.MASTER_BRAIN.update({
                "gappers": t_all[:20], 
                "hod": (c_hod + config.MASTER_BRAIN["hod"])[:50],
                "surge": (c_surge + config.MASTER_BRAIN["surge"])[:50],
                "last_update": current_time_tw, "scan_count": count
            })
            
            cost_time = time.time() - loop_start_time
            if len(t_all) > 0:
                print(f"[{current_time_tw}] ⏱️ 狙擊完成: 追蹤 {len(t_all)} 檔目標，耗時 {cost_time:.2f} 秒")
            
            time.sleep(2.0)
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤：{e}")
            time.sleep(5)