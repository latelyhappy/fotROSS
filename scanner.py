import time, threading, requests, os, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright
from io import StringIO 

import config
from news_engine import fetch_news_bg

# 系統全自動化，純依靠雷達名單
auto_hot_symbols = [] 

# ==========================================
# 🎯 華爾街催化劑黃金關鍵字庫 (支援中英文)
# ==========================================
CATALYST_KEYWORDS = [
    'FDA', 'MERGER', 'ACQUISITION', 'BUYOUT', 'EARNINGS', 'PATENT', 
    'PHASE', 'AGREEMENT', 'CONTRACT', 'PARTNERSHIP', 'TRIAL', 
    'CLEARANCE', 'APPROVAL', 'REVENUE', 'GUIDANCE',
    '合作', '收購', '財報', '專利', '核准', '臨床', '併購', '合約', '營收'
]

def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    current_time = now_ny.time()
    if current_time < datetime.strptime("09:30", "%H:%M").time(): return "2", "盤前"
    elif current_time > datetime.strptime("16:00", "%H:%M").time(): return "1", "盤後"
    else: return "0", "盤中"

def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        prev = i.get('regularMarketPreviousClose', i.get('previousClose', 1.0))
        if prev == 0: prev = 1.0
        config.stock_cache[ticker] = (f, 500000, prev)
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
# ★ 核心模組 1：隱形瀏覽器 + Webull 條件過濾 API
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ 隱形瀏覽器準備潛入 Webull 篩選器 ({market_status})...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
                page = context.new_page()
                page.goto("https://app.webull.com/screener", timeout=30000)
                time.sleep(4) 
                
                sort_id = "fm_53" if rank_type == "2" else "fm_12"
                
                js_code = f"""
                async () => {{
                    const payload = {{
                        "fetch": 30,
                        "rules": [
                            {{"proId": "fm_13", "rule": "between", "val": ["1", "20"]}},       
                            {{"proId": "fm_43", "rule": "between", "val": ["0", "20000000"]}}, 
                            {{"proId": "fm_14", "rule": "between", "val": ["50000", "999999999"]}}, 
                            {{"proId": "{sort_id}", "rule": "between", "val": ["0.05", "10"]}} 
                        ],
                        "sort": {{"rule": "desc", "proId": "{sort_id}"}}
                    }};
                    const res = await fetch('https://quotes-gw.webullfintech.com/api/wlas/screener/screener', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(payload)
                    }});
                    return await res.json();
                }}
                """
                data = page.evaluate(js_code)
                browser.close()
                
                symbols = []
                for item in data.get('data', []):
                    sym = item.get('ticker', {}).get('symbol')
                    if sym and '-' not in sym: symbols.append(sym)
                
                if symbols:
                    auto_hot_symbols = symbols 
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ✅ Webull Ross策略篩選成功: {symbols[:5]}...")
                else:
                    raise ValueError("Webull 篩選回傳空值")
                    
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 Webull 篩選失敗 ({e})，立刻切換【無敵備用雷達】...")
            try:
                rank_type, _ = get_market_rank_type()
                url = "https://stockanalysis.com/markets/premarket/" if rank_type == "2" else "https://stockanalysis.com/markets/gainers/"
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                
                df_list = pd.read_html(StringIO(res.text))
                if df_list:
                    symbols = df_list[0]['Symbol'].dropna().tolist()
                    symbols = [str(s) for s in symbols if isinstance(s, str) and '-' not in s][:30]
                    if symbols:
                        auto_hot_symbols = symbols
                        print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🛡️ 備用雷達鎖定目標: {symbols[:5]}...")
            except Exception as ex:
                pass
                
        # ⏱️ 隨機延遲保護 (8秒 ± 4秒 = 4 ~ 12 秒)
        delay = random.randint(4, 12)
        print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ⏳ 雷達休眠 {delay} 秒防偵測...")
        time.sleep(delay)

# ==========================================
# ★ 核心模組 2：Yahoo 高頻狙擊鏡
# ==========================================
def scanner_engine():
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動全自動防護版 (動態隨機延遲 + 手動拔除)...")
    
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    wait_count = 0
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            # 純自動化陣列
            symbols_to_track = list(set(auto_hot_symbols))
            
            if not symbols_to_track:
                if wait_count % 5 == 0:
                    print(f"[{current_time_tw}] ⏳ 狙擊鏡待命中...")
                wait_count += 1
                time.sleep(2)
                continue
                
            wait_count = 0
            
            data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False, timeout=5)
            
            extracted_stocks = []
            if not data_df.empty:
                is_single = len(symbols_to_track) == 1
                for sym in symbols_to_track:
                    try:
                        latest_row = data_df.iloc[-1] if is_single else data_df.xs(sym, level=1, axis=1).iloc[-1]
                        price = float(latest_row['Close'])
                        vol = float(latest_row['Volume'])
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({
                                'sym': sym, 'price': price, 'vol_raw': vol, 'rvol_tw': vol / 50000.0
                            })
                    except:
                        continue

            t_all, c_hod, c_surge = [], [], []
            current_t = time.time()
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw']
                
                f, a, prev_close = get_static(sym)
                formatted_volume = format_vol_km(vol_raw)
                
                change_pct = ((p_num - prev_close) / prev_close * 100) if prev_close > 0 else 0
                change_str = f"+{change_pct:.2f}%" if change_pct > 0 else f"{change_pct:.2f}%"
                
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

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
                cell["max_surge_vol"] = max_surge_vol
                cell["pullback_start_time"] = pullback_start_time
                cell["pullback_min_vol"] = pullback_min_vol
                cell["is_pullback"] = is_pullback
                cell["sniper_triggered"] = sniper_triggered
                if sniper_triggered: cell["sniper_label"] = sniper_label
                
                streak_text = f"x{cell['streak']}"
                if is_hod_break: streak_text = f"⭐破高{streak_text}"
                elif sniper_triggered: streak_text = f"{cell['sniper_label']}"

                has_catalyst = False
                for news in cell.get("NewsList", []):
                    title_upper = news.get("title", "").upper()
                    for kw in CATALYST_KEYWORDS:
                        if kw in title_upper:
                            has_catalyst = True
                            cell["max_news_score"] += 10 
                            break
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "Change": change_str, "Volume": formatted_volume, "vol_raw": vol_raw,
                    "RVOL": f"{rvol:.1f}x", "FloatStr": float_str, "Streak": streak_text,
                    "NetVolNum": net_vol, 
                    "NewsScore": cell["max_news_score"],
                    "HasCatalyst": has_catalyst, 
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]),
                    "SellVolStr": format_vol_km(cell["cum_sell_vol"])
                }

                t_all.append(item)
                
                if is_hod_break: c_hod.append(item)
                if sniper_triggered or (cell["streak"] >= 2 and is_hod_break): c_surge.append(item)

                if not cell["NewsList"]: 
                    tw_url = f"https://www.tradingview.com/chart/?symbol={sym}"
                    cell["NewsList"] = [{"id": "0", "title": "🗞️ 點擊前往 TradingView 查看線圖", "score": 0, "link": tw_url, "time": ""}]
                    threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            
            # 千筆大容量與下捲更新
            news_valid = [x for x in t_all if x['NewsScore'] > 0 and x['HasCatalyst']]
            high_vol_sorted = sorted(t_all, key=lambda x: x['vol_raw'], reverse=True)
            net_vol_sorted = sorted(t_all, key=lambda x: x['NetVolNum'], reverse=True)
            grind_sorted = sorted(t_all, key=lambda x: config.MASTER_BRAIN["details"][x["Code"]]["streak"], reverse=True)
            news_sorted = sorted(news_valid, key=lambda x: x['NewsScore'], reverse=True)
            
            config.MASTER_BRAIN.update({
                "gappers": t_all[:1000], 
                "hod": (c_hod + config.MASTER_BRAIN["hod"])[:1000],
                "surge": (c_surge + config.MASTER_BRAIN["surge"])[:1000],
                "high_vol": high_vol_sorted[:1000],       
                "net_vol_leaders": net_vol_sorted[:1000], 
                "grinders": grind_sorted[:1000],          
                "news_leaders": news_sorted[:1000],       
                "last_update": current_time_tw, 
                "scan_count": count
            })
            
            cost_time = time.time() - loop_start_time
            if len(t_all) > 0:
                print(f"[{current_time_tw}] ⏱️ 狙擊完成: 追蹤 {len(t_all)} 檔目標，耗時 {cost_time:.2f} 秒")
            
            # ⏱️ 隨機延遲保護 (8秒 ± 4秒 = 4 ~ 12 秒)
            delay = random.randint(4, 12)
            time.sleep(delay)
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤：{e}")
            time.sleep(5)
