import time, threading, requests, traceback, random, json
from datetime import datetime
import pytz
import yfinance as yf

import config
from news_engine import fetch_news_bg

# 建立隱形連線 session (偽裝成一般瀏覽器)
scraper = requests.Session()
scraper.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Origin': 'https://www.tradingview.com',
    'Referer': 'https://www.tradingview.com/'
})

# ==========================================
# 靜態資料背景抓取 (交給 Yahoo)
# ==========================================
def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        # 抓取浮動股數 (Float) 與平均交易量
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000)
        p = i.get('previousClose', 1.0)
        config.stock_cache[ticker] = (f, a, p)
    except:
        config.stock_cache[ticker] = (1000000, 500000, 1.0)

def get_static(ticker):
    if ticker in config.stock_cache:
        return config.stock_cache[ticker]
    else:
        config.stock_cache[ticker] = (1000000, 500000, 1.0) 
        # 背景啟動 Yahoo 抓取，不卡主程式
        threading.Thread(target=fetch_static_bg, args=(ticker,), daemon=True).start()
        return (1000000, 500000, 1.0)

# ==========================================
# 輔助格式化函式
# ==========================================
def format_vol_km(v_float):
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
    else: return f"{int(v_float)}"

# ==========================================
# ★ 核心引擎：TW API 直連與微觀運算
# ==========================================
def scanner_engine():
    count = 0
    print("🔥 啟動 TW 內部 API 直連引擎 (零延遲混血版)...")
    tz_tw = pytz.timezone('Asia/Taipei')
    
# 這是我們要傳給 TW 伺服器的「地下指令」
    tw_url = "https://scanner.tradingview.com/america/scan"
    tw_payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [0.5, 50]},
            {"left": "type", "operation": "in_range", "right": ["stock", "dr"]}
        ],
        "options": {"lang": "en"},
        "markets": ["america"],
        "symbols": {"query": {"types": []}, "tickers": []},
        # ★ 修正此處：改用 TW 官方認可的相對成交量欄位名稱 relative_volume_10d_calc
        "columns": ["name", "close", "change", "volume", "relative_volume_10d_calc"],
        "sort": {"sortBy": "change", "sortOrder": "desc"},
        "range": [0, 100]
    }

    while True:
        try:
            loop_start_time = time.time() 
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            # 1. 呼叫 TW 內部 API 抓取零延遲資料
            response = scraper.post(tw_url, json=tw_payload, timeout=10)
            extracted_stocks = []
            
            if response.status_code == 200:
                tw_data = response.json()
                for item in tw_data.get('data', []):
                    # TW 格式: {"d": ["NASDAQ:AAPL", 150.0, 2.5, 50000000, 1.2]}
                    cols = item.get('d', [])
                    if len(cols) >= 5:
                        raw_sym = cols[0]
                        sym = raw_sym.split(':')[1] if ':' in raw_sym else raw_sym # 去除交易所前綴
                        price = float(cols[1])
                        change_pct = float(cols[2])
                        vol = float(cols[3])
                        rvol_tw = float(cols[4]) if cols[4] is not None else 1.0
                        
                        extracted_stocks.append({
                            'sym': sym, 
                            'price': price, 
                            'change_str': f"{change_pct:.2f}%", 
                            'vol_raw': vol,
                            'rvol_tw': rvol_tw
                        })
            else:
                print(f"[{current_time_tw}] ⚠️ TW API 回應錯誤狀態碼: {response.status_code}")

            t_all, c_hod, c_surge, c_grind = [], [], [], []
            current_t = time.time()
            
            # 2. 進入微觀運算邏輯 (與 V215.9 相同)
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                change_str = data['change_str']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw'] # 直接使用 TW 算好的即時量比
                
                # 向 Yahoo 提取背景已準備好的浮動股數
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
                
                gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                drop_p = ((p_num - cell['HOD']) / cell['HOD'] * 100) if cell['HOD'] > 0 else 0
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                
                last_price = cell.get("last_price", p_num)
                last_vol = cell.get("last_vol", vol_raw)
                curr_vol_delta = vol_raw - last_vol 
                
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

                if current_t - cell.get("grind_1m_start_time", current_t) >= 60.0:
                    start_p = cell.get("grind_1m_start_price", p_num)
                    if p_num > start_p:
                        cell["grind_1m_count"] = cell.get("grind_1m_count", 0) + 1
                    elif p_num < start_p:
                        cell["grind_1m_count"] = 0 
                    cell["grind_1m_start_time"] = current_t
                    cell["grind_1m_start_price"] = p_num

                if cell["grind_1m_count"] >= 2: cell["is_grinder"] = True
                elif cell["grind_1m_count"] == 0: cell["is_grinder"] = False

                recent_high = cell.get("recent_high", initial_hod)
                surge_start_price = cell.get("surge_start_price", initial_hod)
                max_surge_vol = cell.get("max_surge_vol", 0)
                pullback_start_time = cell.get("pullback_start_time", 0)
                pullback_min_vol = cell.get("pullback_min_vol", 9999999)
                
                is_pullback = cell.get("is_pullback", False)
                sniper_triggered = False
                is_extended = False
                sniper_label = ""
                
                if surge_start_price > 0 and (p_num - surge_start_price) / surge_start_price > 0.25 and rvol > 3.0:
                    is_extended = True
                    
                if p_num > recent_high:
                    if is_pullback:
                        swing_size = recent_high - surge_start_price
                        pb_low = cell.get("pullback_low", p_num)
                        retrace_ratio = (recent_high - pb_low) / swing_size if swing_size > 0 else 0
                        pb_duration = current_t - pullback_start_time
                        
                        if curr_vol_delta > pullback_min_vol * 1.2: 
                            sniper_triggered = True
                            cell["surge_wave_count"] = cell.get("surge_wave_count", 0) + 1
                            
                            if retrace_ratio <= 0.35 and pb_duration <= 180:
                                sniper_label = "⚡極速(9EMA)"
                            elif retrace_ratio <= 0.55 and pb_duration <= 600:
                                sniper_label = "🎯標準(20EMA)"
                            else:
                                sniper_label = "🎯強勢突破"
                        
                        is_pullback = False
                        surge_start_price = p_num 
                        max_surge_vol = curr_vol_delta 
                    else:
                        max_surge_vol = max(max_surge_vol, curr_vol_delta)
                    recent_high = p_num
                    
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    is_vol_contracted = (curr_vol_delta <= max_surge_vol * 0.4) if max_surge_vol > 0 else True
                    
                    if retrace_ratio <= 0.50 and net_vol > 0 and is_vol_contracted:
                        if not is_pullback:
                            is_pullback = True
                            pullback_start_time = current_t
                            pullback_min_vol = curr_vol_delta
                            cell["pullback_low"] = p_num
                        else:
                            pullback_min_vol = min(pullback_min_vol, curr_vol_delta)
                            cell["pullback_low"] = min(cell.get("pullback_low", p_num), p_num)
                    else:
                        if retrace_ratio > 0.50 or curr_vol_delta > max_surge_vol * 0.6:
                            is_pullback = False 

                if is_pullback and (current_t - pullback_start_time > 900):
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
                cell["bull_trap"] = bull_trap
                cell["is_extended"] = is_extended
                if sniper_triggered: cell["sniper_label"] = sniper_label
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "Change": change_str, "Volume": formatted_volume, 
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

                last_vol_delta = cell.get("last_vol_delta", 0)
                up_ticks = cell.get("up_ticks", 0) 
                if p_num > last_price: up_ticks += 1
                elif p_num < last_price: up_ticks = 0
                    
                if is_hod_break and (rvol > 0.2 or vol_raw > 50000): 
                    item_hod = item.copy()
                    if bull_trap: item_hod["Streak"] = "⚠️虛漲倒貨"
                    else: item_hod["Streak"] = f"⭐破高x{cell['streak']}"
                    c_hod.append(item_hod)
                    cell["last_act"] = "hod"

                is_vol_spike = (curr_vol_delta > last_vol_delta * 3) and (curr_vol_delta > 20000) and (p_num >= last_price)
                
                if sniper_triggered or (cell["streak"] >= 2 and is_hod_break) or is_vol_spike or is_extended:
                    item_surge = item.copy()
                    
                    if sniper_triggered:
                        wave = cell.get("surge_wave_count", 1)
                        label = cell.get("sniper_label", "🎯精準狙擊")
                        item_surge["Streak"] = f"{label} (第{wave}波)"
                    elif bull_trap and is_hod_break: 
                        item_surge["Streak"] = "⚠️虛漲倒貨"
                    elif is_extended: 
                        item_surge["Streak"] = "🔥極度拉伸 (防追高)"
                    elif is_vol_spike: 
                        item_surge["Streak"] = f"💥爆量+{format_vol_km(curr_vol_delta)}"
                    else: 
                        item_surge["Streak"] = f"⭐破高x{cell['streak']}"
                        
                    c_surge.append(item_surge)
                    cell["last_act"] = "surge"

                if not cell["NewsList"]: 
                    cell["NewsList"] = [{"id": "0", "title": "檢索中...", "score": 0, "link": "#", "time": ""}]
                    threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                cell["up_ticks"] = up_ticks 
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            news_list_temp, net_vol_temp, active_grinders = [], [], []
            
            for k_sym, k_cell in config.MASTER_BRAIN["details"].items():
                if "latest_item" in k_cell and k_cell.get("last_seen") == current_time_tw:
                    score = k_cell.get("max_news_score", 0)
                    if score != 0:
                        i_copy = k_cell["latest_item"].copy()
                        i_copy["NewsScore"] = score
                        news_list_temp.append(i_copy)
                    
                    if k_cell["cum_buy_vol"] > 0 or k_cell["cum_sell_vol"] > 0:
                        net_vol_temp.append(k_cell["latest_item"].copy())
                        
                    if k_cell.get("is_grinder", False):
                        item_grind = k_cell["latest_item"].copy()
                        is_pb = k_cell.get("is_pullback", False)
                        no_vol = k_cell.get("no_vol_shakeout", False)
                        sniped = k_cell.get("sniper_triggered", False)
                        g_count = k_cell.get("grind_1m_count", 0)
                        
                        item_grind["GrindCount"] = g_count 
                        if no_vol: is_pb = True 
                        
                        if sniped: item_grind["Streak"] = f"{k_cell.get('sniper_label', '🎯狙擊')} (第{k_cell.get('surge_wave_count', 1)}波)"
                        elif is_pb: item_grind["Streak"] = "👀回調盯盤"
                        else: item_grind["Streak"] = f"📈EMA60持續上漲x{g_count}"
                            
                        active_grinders.append(item_grind)
                    
            news_leaders = sorted(news_list_temp, key=lambda x: x["NewsScore"], reverse=True)[:20]
            net_vol_leaders = sorted(net_vol_temp, key=lambda x: abs(x.get("NetVolNum", 0)), reverse=True)[:20]
            gappers = sorted(t_all, key=lambda x: x["gap_num"], reverse=True)[:20]
            high_vol = sorted(t_all, key=lambda x: x["rvol_num"], reverse=True)[:20]
            active_grinders = sorted(active_grinders, key=lambda x: x.get("GrindCount", 0), reverse=True)[:20]

            config.MASTER_BRAIN.update({
                "gappers": gappers, "high_vol": high_vol,
                "hod": (c_hod + config.MASTER_BRAIN["hod"])[:50],
                "surge": (c_surge + config.MASTER_BRAIN["surge"])[:50],
                "news_leaders": news_leaders, 
                "net_vol_leaders": net_vol_leaders, 
                "grinders": active_grinders, 
                "last_update": current_time_tw, "scan_count": count
            })
            
            cost_time = time.time() - loop_start_time
            if len(t_all) == 0:
                print(f"[{current_time_tw}] ❌ 解析失敗或目前盤中無符合資料")
            else:
                print(f"[{current_time_tw}] ⏱️ TW 掃描完成: 找到 {len(t_all)} 檔目標，耗時 {cost_time:.2f} 秒")

            # ==========================================
            # ★ 絕佳的反爬蟲機制：8秒 ± 4秒隨機延遲 (4.0 ~ 12.0 秒)
            # ==========================================
            delay = random.uniform(4.0, 12.0)
            time.sleep(delay)
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤，重啟迴圈：")
            traceback.print_exc()
            time.sleep(5)
