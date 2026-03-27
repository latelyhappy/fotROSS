import time, threading, requests, os, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright
from io import StringIO 

import config
from news_engine import fetch_news_bg

auto_hot_symbols = []       
feed_gappers = []           
feed_hod = []               
feed_surge = []             

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
        a = i.get('averageVolume', 500000)
        prev = i.get('regularMarketPreviousClose', i.get('previousClose', 1.0))
        if prev == 0: prev = 1.0
        config.stock_cache[ticker] = (f, a, prev)
    except:
        config.stock_cache[ticker] = (1000000, 500000, 1.0)

def get_static(ticker):
    if ticker in config.stock_cache: return config.stock_cache[ticker]
    else:
        config.stock_cache[ticker] = (1000000, 500000, 1.0) 
        threading.Thread(target=fetch_static_bg, args=(ticker,), daemon=True).start()
        return (1000000, 500000, 1.0)

def format_vol_km(v_float):
    try:
        v_float = float(v_float)
        if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
        elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
        else: return f"{int(v_float)}"
    except:
        return "0K"

def update_or_add_gapper(new_entry):
    global feed_gappers
    # ✨ 核心修復：尋找表格中是否已有此股票，若有則更新數據並移到最上方（下捲）
    for i, entry in enumerate(feed_gappers):
        if entry['Code'] == new_entry['Code']:
            # 如果數據真的有變動，才推到最上方
            if entry['Price'] != new_entry['Price'] or entry['Volume'] != new_entry['Volume']:
                feed_gappers.pop(i)
                feed_gappers.insert(0, new_entry)
            return
    # 如果是全新的股票，直接加在最上方
    feed_gappers.insert(0, new_entry)

# ==========================================
# ★ 核心模組 1：Webull 主引擎 & 萬能備用雷達
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols, feed_gappers
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ Webull 主引擎掃描中 ({market_status})...")
            
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
                            {{"proId": "fm_14", "rule": "between", "val": ["50000", "999999999"]}}
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
                
                new_found = []
                for item in data.get('data', []):
                    sym = item.get('ticker', {}).get('symbol')
                    if sym and '-' not in sym:
                        if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                        new_found.append(sym)
                        
                        f, avg_vol, prev_close = get_static(sym)
                        float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                        
                        price_raw = item.get('price') or item.get('pPrice') or item.get('close') or '0'
                        changeRatio = item.get('changeRatio') or item.get('pChangeRatio') or '0'
                        vol = item.get('volume') or item.get('pVolume') or '0'
                        
                        try: vol_float = float(vol)
                        except: vol_float = 0.0
                        
                        try: chg_float = float(changeRatio) * 100
                        except: chg_float = 0.0
                        chg_str = f"+{chg_float:.2f}%" if chg_float > 0 else f"{chg_float:.2f}%"
                        
                        rvol_val = (vol_float / 50000.0) if avg_vol == 500000 else (vol_float / avg_vol)
                        
                        new_entry = {
                            "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                            "Code": sym,
                            "Price": f"${float(price_raw):.2f}" if float(price_raw) > 0 else "獲取中",
                            "Change": chg_str,
                            "Volume": format_vol_km(vol_float),
                            "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "計算中",
                            "FloatStr": float_str,
                            "discovery_time": time.time()
                        }
                        update_or_add_gapper(new_entry)
                
                if new_found:
                    feed_gappers = feed_gappers[:1000]
                    auto_hot_symbols = auto_hot_symbols[:200] 
                    print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ✅ Webull 擷取完畢")
                elif not data.get('data', []):
                    raise ValueError("Webull 篩選回傳空值")
                    
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 Webull 失敗 ({e})，啟動備用雷達...")
            try:
                rank_type, _ = get_market_rank_type()
                if rank_type == "2": url = "https://stockanalysis.com/markets/premarket/"
                elif rank_type == "1": url = "https://stockanalysis.com/markets/after-hours/"
                else: url = "https://stockanalysis.com/markets/gainers/"
                    
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                df_list = pd.read_html(StringIO(res.text))
                
                if df_list:
                    df = df_list[0]
                    price_col = next((c for c in df.columns if 'price' in c.lower() or 'last' in c.lower()), None)
                    change_col = next((c for c in df.columns if '%' in c or 'change' in c.lower()), None)
                    vol_col = next((c for c in df.columns if 'vol' in c.lower()), None)
                    
                    new_found = []
                    for idx, row in df.iterrows():
                        if idx > 29: break
                        sym = str(row.get('Symbol', ''))
                        if sym and '-' not in sym:
                            if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                            new_found.append(sym)
                            
                            f, avg_vol, prev_close = get_static(sym)
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            
                            p_val = str(row[price_col]) if price_col and pd.notna(row[price_col]) else '0'
                            c_val = str(row[change_col]) if change_col and pd.notna(row[change_col]) else '0%'
                            
                            # 處理交易量字串（將逗號清除）
                            v_val_str = str(row[vol_col]).replace(',', '') if vol_col and pd.notna(row[vol_col]) else '0'
                            
                            new_entry = {
                                "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                                "Code": sym,
                                "Price": f"${p_val}" if not p_val.startswith('$') else p_val,
                                "Change": c_val if '%' in c_val else f"{c_val}%",
                                "Volume": format_vol_km(v_val_str),
                                "RVOL": "補齊中...",
                                "FloatStr": float_str,
                                "discovery_time": time.time()
                            }
                            update_or_add_gapper(new_entry)
                            
                    if new_found:
                        feed_gappers = feed_gappers[:1000]
                        auto_hot_symbols = auto_hot_symbols[:200]
                        print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🛡️ 備用雷達擷取完畢")
            except Exception as ex:
                pass
                
        delay = random.randint(4, 12)
        print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] ⏳ 雷達休眠 {delay} 秒...")
        time.sleep(delay)

# ==========================================
# ★ 核心模組 2：Yahoo 副引擎 (精算與回補)
# ==========================================
def scanner_engine():
    global feed_gappers, feed_hod, feed_surge
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動 V8.5 動態更新與精準欄位版...")
    
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    wait_count = 0
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            symbols_to_track = list(set(auto_hot_symbols[:200]))
            
            if not symbols_to_track:
                if wait_count % 5 == 0:
                    print(f"[{current_time_tw}] ⏳ 狙擊鏡待命中...")
                wait_count += 1
                time.sleep(2)
                continue
                
            wait_count = 0
            
            data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False, timeout=10)
            
            extracted_stocks = []
            if not data_df.empty:
                for sym in symbols_to_track:
                    try:
                        price, vol = 0.0, 0.0
                        if isinstance(data_df.columns, pd.MultiIndex):
                            if 'Close' in data_df.columns.get_level_values(0) and sym in data_df['Close'].columns:
                                price = float(data_df['Close'][sym].dropna().iloc[-1])
                                vol = float(data_df['Volume'][sym].dropna().iloc[-1])
                            elif sym in data_df.columns.get_level_values(0):
                                price = float(data_df[sym]['Close'].dropna().iloc[-1])
                                vol = float(data_df[sym]['Volume'].dropna().iloc[-1])
                        else:
                            if 'Close' in data_df.columns:
                                price = float(data_df['Close'].dropna().iloc[-1])
                                vol = float(data_df['Volume'].dropna().iloc[-1])
                                
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({'sym': sym, 'price': price, 'vol_raw': vol, 'rvol_tw': vol / 50000.0})
                    except:
                        continue

            t_all = []
            current_t = time.time()
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw']
                
                f, a, prev_close = get_static(sym)
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                
                # ✨ 雙重核對回補：只要漏掉，Yahoo 立刻精準補上
                for gap_entry in feed_gappers:
                    if gap_entry['Code'] == sym:
                        if "獲取中" in gap_entry['Price'] or "$0" in gap_entry['Price']:
                            gap_entry['Price'] = f"${p_num:.2f}"
                        if gap_entry['Volume'] == "0K" or gap_entry['Volume'] == "0":
                            gap_entry['Volume'] = format_vol_km(vol_raw)
                        if "雷達" in gap_entry['RVOL'] or "補齊" in gap_entry['RVOL']:
                            gap_entry['RVOL'] = f"{rvol:.1f}x"
                        if "0%" in gap_entry['Change'] or gap_entry['Change'] == "0":
                            chg = ((p_num - prev_close) / prev_close * 100) if prev_close > 0 else 0
                            gap_entry['Change'] = f"+{chg:.2f}%" if chg > 0 else f"{chg:.2f}%"
                        if "FloatStr" not in gap_entry:
                            gap_entry['FloatStr'] = float_str
                
                is_new_stock = sym not in config.MASTER_BRAIN["details"]
                initial_hod = (p_num * 0.98) if is_new_stock else p_num
                
                cell = config.MASTER_BRAIN["details"].get(sym, {
                    "HOD": initial_hod, "NewsList": [], "max_news_score": 0, "streak": 0, 
                    "last_price": p_num, "cum_buy_vol": 0, "cum_sell_vol": 0, "is_grinder": False,
                    "recent_high": initial_hod, "is_pullback": False, "sniper_triggered": False,
                    "surge_start_price": initial_hod, "max_surge_vol": 0, "pullback_low": p_num, "sniper_label": ""
                })
                
                is_hod_break = False
                if p_num > cell["HOD"]: cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                
                last_price = cell.get("last_price", p_num)
                curr_vol_delta = vol_raw
                
                if curr_vol_delta > 0:
                    if p_num > last_price: cell["cum_buy_vol"] += curr_vol_delta
                    elif p_num < last_price: cell["cum_sell_vol"] += curr_vol_delta
                net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]

                recent_high = cell.get("recent_high", initial_hod)
                surge_start_price = cell.get("surge_start_price", initial_hod)
                is_pullback = cell.get("is_pullback", False)
                sniper_triggered = False
                sniper_label = ""
                
                if p_num > recent_high:
                    if is_pullback:
                        swing_size = recent_high - surge_start_price
                        pb_low = cell.get("pullback_low", p_num)
                        if p_num > pb_low * 1.01: 
                            sniper_triggered = True
                            sniper_label = "⚡極速(9EMA)"
                        is_pullback = False
                        surge_start_price = p_num 
                    recent_high = p_num
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    if retrace_ratio <= 0.50:
                        if not is_pullback:
                            is_pullback = True
                            cell["pullback_low"] = p_num
                        else:
                            cell["pullback_low"] = min(cell.get("pullback_low", p_num), p_num)
                    else:
                        is_pullback = False 

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
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
                    "Change": "Yahoo", "Volume": format_vol_km(vol_raw), "vol_raw": vol_raw,
                    "RVOL": f"{rvol:.1f}x", "FloatStr": float_str, "Streak": streak_text,
                    "NetVolNum": net_vol, 
                    "NewsScore": cell["max_news_score"],
                    "HasCatalyst": has_catalyst, 
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]),
                    "SellVolStr": format_vol_km(cell["cum_sell_vol"])
                }

                t_all.append(item)
                
                if is_hod_break: feed_hod.insert(0, item)
                if sniper_triggered or (cell["streak"] >= 2 and is_hod_break): feed_surge.insert(0, item)

                if not cell["NewsList"]: 
                    tw_url = f"https://www.tradingview.com/chart/?symbol={sym}"
                    cell["NewsList"] = [{"id": "0", "title": "🗞️ 點擊前往 TradingView 查看線圖", "score": 0, "link": tw_url, "time": ""}]
                    threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            
            feed_hod = feed_hod[:1000]
            feed_surge = feed_surge[:1000]
            
            news_valid = [x for x in t_all if x['NewsScore'] > 0 and x['HasCatalyst']]
            high_vol_sorted = sorted(t_all, key=lambda x: x['vol_raw'], reverse=True)
            net_vol_sorted = sorted(t_all, key=lambda x: x['NetVolNum'], reverse=True)
            grind_sorted = sorted(t_all, key=lambda x: config.MASTER_BRAIN["details"][x["Code"]]["streak"], reverse=True)
            news_sorted = sorted(news_valid, key=lambda x: x['NewsScore'], reverse=True)
            
            config.MASTER_BRAIN.update({
                "gappers": feed_gappers,                 
                "hod": feed_hod,                         
                "surge": feed_surge,                       
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
            
            time.sleep(random.randint(4, 12))
            
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤：{e}")
            time.sleep(5)
