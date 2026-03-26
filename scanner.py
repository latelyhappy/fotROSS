import time, threading, requests, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd

import config
from news_engine import fetch_news_bg

# ==========================================
# 網路請求設定 (偽裝成一般瀏覽器)
# ==========================================
scraper = requests.Session()
scraper.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
})

# 存放從 Webull 抓到的熱門代碼名單
current_hot_symbols = []
last_webull_fetch = 0

# ==========================================
# 輔助函式：判斷美國市場狀態 & 取得 Float
# ==========================================
def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    current_time = now_ny.time()
    
    # 美東 04:00 - 09:30 為盤前 (Pre-market)
    if current_time < datetime.strptime("09:30", "%H:%M").time():
        return "2", "盤前時段"
    # 美東 16:00 之後為盤後 (After-hours)
    elif current_time > datetime.strptime("16:00", "%H:%M").time():
        return "1", "盤後時段"
    else:
        return "0", "一般盤中"

def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        config.stock_cache[ticker] = (f, 500000, 1.0)
    except:
        config.stock_cache[ticker] = (1000000, 500000, 1.0)

def get_static(ticker):
    if ticker in config.stock_cache:
        return config.stock_cache[ticker]
    else:
        config.stock_cache[ticker] = (1000000, 500000, 1.0) 
        threading.Thread(target=fetch_static_bg, args=(ticker,), daemon=True).start()
        return (1000000, 500000, 1.0)

def format_vol_km(v_float):
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
    else: return f"{int(v_float)}"

# ==========================================
# ★ 核心模組 1：Webull 地下雷達 (負責找代碼)
# ==========================================
def fetch_webull_gainers():
    global current_hot_symbols, last_webull_fetch
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            # Webull 漲幅榜 API 端點
            webull_url = "https://quoteapi.webullbroker.com/api/market/v1/market/ranking/gainers"
            params = {
                "regionId": "6",       # 美股
                "secType": "12",       # 股票
                "rankType": rank_type, # 2=盤前, 0=盤中
                "pageIndex": "1",
                "pageSize": "30"       # 抓取前 30 名
            }
            
            res = scraper.get(webull_url, params=params, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                symbols = []
                for item in data.get('data', []):
                    # 提取股票代碼
                    sym = item.get('ticker', {}).get('symbol')
                    if sym and '-' not in sym: # 排除奇怪的優先股
                        symbols.append(sym)
                
                if symbols:
                    current_hot_symbols = symbols
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 📡 Webull {market_status} 雷達更新成功！鎖定 {len(symbols)} 檔目標。")
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ⚠️ Webull API 暫時阻擋，使用上一批名單。")
            
        # 雷達每 30 秒掃描一次即可，避免被 Webull 封鎖
        time.sleep(30)

# ==========================================
# ★ 核心模組 2：Yahoo 高頻狙擊鏡 (負責精算價格與量縮)
# ==========================================
def scanner_engine():
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    
    print("🔥 啟動 V4.0 終極引擎 (Webull 雷達 + Yahoo 狙擊)...")
    
    # 啟動 Webull 獨立背景雷達
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            # 如果還沒抓到名單，就稍等
            if not current_hot_symbols:
                time.sleep(2)
                continue
                
            symbols_to_track = list(current_hot_symbols)
            
            # 使用 yfinance 抓取「包含盤前」的最新 1 分鐘 K 線，確保報價 100% 精準！
            data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False, show_errors=False)
            
            extracted_stocks = []
            
            # 解析 Yahoo 回傳的 DataFrame
            if not data_df.empty:
                # 若只有一檔股票，DataFrame 結構會不同
                is_single = len(symbols_to_track) == 1
                
                for sym in symbols_to_track:
                    try:
                        if is_single:
                            latest_row = data_df.iloc[-1]
                        else:
                            # 取得這檔股票最後一分鐘的收盤價與交易量
                            latest_row = data_df.xs(sym, level=1, axis=1).iloc[-1]
                            
                        price = float(latest_row['Close'])
                        vol = float(latest_row['Volume'])
                        
                        # 簡單防呆，如果價格有效才加入運算
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({
                                'sym': sym, 
                                'price': price, 
                                'change_str': "---", # Yahoo 1分K難以算全日漲幅，由前端顯示為主
                                'vol_raw': vol,
                                'rvol_tw': vol / 50000.0 # 粗略量比估算
                            })
                    except:
                        continue

            t_all, c_hod, c_surge, c_grind = [], [], [], []
            current_t = time.time()
            
            # --- 進入您熟悉的微觀運算邏輯 (與之前完全相同，判斷紫燈、量縮) ---
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
                    "up_ticks": 0, 
                    "cum_buy_vol": 0, "cum_sell_vol": 0,
                    "pos_vol_streak": 0, "neg_vol_streak": 0, "is_grinder": False,
                    "recent_high": initial_hod, "is_pullback": False, "sniper_triggered": False,
                    "no_vol_shakeout": False, "bull_trap": False,
                    "grind_1m_start_time": current_t, "grind_1m_start_price": p_num, "grind_1m_count": 0,
                    
                    "surge_start_price": initial_hod, "max_surge_vol": 0, 
                    "pullback_start_time": 0, "pullback_min_vol": 9999999, "is_extended": False,
                    "surge_wave_count": 0, "pullback_low": p_num, "sniper_label": ""
                })
                
                is_hod_break = False
                if p_num > cell["HOD"]: cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                
                gap_p = 0 # 簡化計算
                drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                
                last_price = cell.get("last_price", p_num)
                last_vol = cell.get("last_vol", vol_raw)
                # K線模式：因為每次抓的是當前1分鐘的總量，我們用價格變化來判斷買賣壓
                curr_vol_delta = vol_raw
                
                if curr_vol_delta > 0:
                    if p_num > last_price: 
                        cell["cum_buy_vol"] += curr_vol_delta
                        cell["pos_vol_streak"] += 1     
                        cell["neg_vol_streak"] = 0      
                    elif p_num < last_price: 
                        cell["cum_sell_vol"] += curr_vol_delta
                        cell["neg_vol_streak"] += 1     
                        cell["pos_vol_streak"] = 0      

                net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]

                # --- 短線動能追蹤演算法 ---
                recent_high = cell.get("recent_high", initial_hod)
                surge_start_price = cell.get("surge_start_price", initial_hod)
                max_surge_vol = cell.get("max_surge_vol", 0)
                pullback_start_time = cell.get("pullback_start_time", 0)
                pullback_min_vol = cell.get("pullback_min_vol", 9999999)
                
                is_pullback = cell.get("is_pullback", False)
                sniper_triggered = False
                is_extended = False
                sniper_label = ""
                
                if p_num > recent_high:
                    if is_pullback:
                        swing_size = recent_high - surge_start_price
                        pb_low = cell.get("pullback_low", p_num)
                        retrace_ratio = (recent_high - pb_low) / swing_size if swing_size > 0 else 0
                        pb_duration = current_t - pullback_start_time
                        
                        # V型突破判定
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
                    "Change": "Webull", "Volume": formatted_volume, 
                    "RVOL": f"{rvol:.1f}x", "Gap": f"{gap_p:.1f}%", "Drop": f"{drop_p:.1f}%",
                    "FloatStr": float_str, "Streak": f"x{cell['streak']}", 
                    "gap_num": gap_p, "rvol_num": rvol, "f_num": f,
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
                    cell["NewsList"] = [{"id": "0", "title": "檢索中...", "score": 0, "link": "#", "time": ""}]
                    threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            
            # --- 更新前端顯示名單 ---
            config.MASTER_BRAIN.update({
                "gappers": t_all[:20], 
                "hod": (c_hod + config.MASTER_BRAIN["hod"])[:50],
                "surge": (c_surge + config.MASTER_BRAIN["surge"])[:50],
                "last_update": current_time_tw, "scan_count": count
            })
            
            cost_time = time.time() - loop_start_time
            print(f"[{current_time_tw}] ⏱️ Yahoo 狙擊鏡掃描完成: 追蹤 {len(t_all)} 檔目標，耗時 {cost_time:.2f} 秒")

            # 頻繁戳 Yahoo，大約每 3 秒更新一次 K 線報價
            time.sleep(3.0)
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤：{e}")
            time.sleep(5)
