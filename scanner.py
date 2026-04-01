import time, threading, requests, os, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from io import StringIO 
import re
from concurrent.futures import ThreadPoolExecutor

import config

static_task_pool = ThreadPoolExecutor(max_workers=5)  
news_task_pool = ThreadPoolExecutor(max_workers=10)   

yf_lock = threading.Lock()

def log_debug(ticker, msg):
    tz_tw = pytz.timezone('Asia/Taipei')
    time_str = datetime.now(tz_tw).strftime('%H:%M:%S')
    print(f"[{time_str}] 🕵️‍♂️ [DEBUG {ticker}] {msg}", flush=True)

try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    print("🛡️ 已啟動 Cloudscraper 破甲模式！", flush=True)
except ImportError:
    scraper = requests.Session()
    scraper.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"})

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

def translate_to_zh(text):
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "zh-TW", "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            translated_text = "".join([sentence[0] for sentence in res.json()[0]])
            return translated_text
    except Exception as e: pass
    return text 

def fetch_direct_news_bg(ticker, cell):
    try:
        if "raw_news_titles" not in cell: cell["raw_news_titles"] = []
            
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        today_str = now_ny.strftime("%Y-%m-%d")
        
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={ticker}&quotesCount=0&newsCount=5"
        res = scraper.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        
        if res.status_code == 200:
            news_items = res.json().get('news', [])
        else:
            news_items = []
        
        new_articles = []
        for item in news_items:
            raw_title = item.get('title', '').strip()
            raw_link = item.get('link', f"https://finance.yahoo.com/quote/{ticker}/news")
            pub_ts = item.get('providerPublishTime')
            
            if not raw_title or not pub_ts: continue
            if raw_title in cell["raw_news_titles"]: continue
                
            try:
                pub_dt = datetime.fromtimestamp(pub_ts, tz_ny)
                pub_date_only = pub_dt.strftime("%Y-%m-%d")
                pub_time_only = pub_dt.strftime("%H:%M")
                days_diff = (now_ny.date() - pub_dt.date()).days
            except Exception:
                days_diff, pub_date_only, pub_time_only = 0, "", ""
                
            if days_diff > 4: continue 
                
            is_today = (pub_date_only == today_str)
            display_str = f"{pub_time_only}" if is_today else f"{pub_date_only[5:]} {pub_time_only}"
            
            log_debug(ticker, f"✨ 成功攔截瞬時公關稿！啟動翻譯: {pub_date_only} {pub_time_only} | {raw_title[:20]}...")
            translated_title = translate_to_zh(raw_title)
            
            cell["raw_news_titles"].append(raw_title)
            
            new_articles.append({
                "id": str(random.randint(10000, 99999)), "title": translated_title,
                "score": 0, "link": raw_link, "time": display_str, "is_today": is_today, "is_read": False,
                "pub_ts": pub_ts
            })
            
            if len(new_articles) >= 5: break
            
        if new_articles:
            clean_old_list = [n for n in cell.get("NewsList", []) if "🗞️" not in n.get("title", "")]
            cell["NewsList"] = (new_articles + clean_old_list)[:5]
            log_debug(ticker, f"🎉 成功新增並翻譯 {len(new_articles)} 筆突發新聞！")
        elif not cell.get("NewsList") or "🗞️" in cell["NewsList"][0].get("title", ""):
            tw_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            cell["NewsList"] = [{"id": "0", "title": "🗞️ 點擊前往 TradingView (近 4 天無重大新聞)", "score": 0, "link": tw_url, "time": "", "is_today": False}]
            
    except Exception as e:
        tw_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
        cell["NewsList"] = [{"id": "0", "title": f"🗞️ 新聞直連失敗，點此看線圖", "score": 0, "link": tw_url, "time": "", "is_today": False}]

def get_market_rank_type():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    current_time = now_ny.time()
    if current_time < datetime.strptime("09:30", "%H:%M").time(): return "2", "盤前"
    elif current_time > datetime.strptime("16:00", "%H:%M").time(): return "1", "盤後"
    else: return "0", "盤中"

def fetch_static_bg(ticker):
    try:
        with yf_lock:
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
        static_task_pool.submit(fetch_static_bg, ticker)
        return (1000000, 500000, 1.0)

def parse_vol_to_float(v):
    try:
        if isinstance(v, str):
            v = v.replace(',', '').upper().strip()
            if 'M' in v: return float(v.replace('M', '')) * 1_000_000
            if 'K' in v: return float(v.replace('K', '')) * 1_000
            return float(v)
        return float(v)
    except:
        return 0.0

def format_vol_km(v_float):
    try:
        v_float = parse_vol_to_float(v_float)
        if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
        elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
        else: return f"{int(v_float)}"
    except:
        return "0K"

def update_or_add_gapper(new_entry):
    global feed_gappers
    for i, entry in enumerate(feed_gappers):
        if entry['Code'] == new_entry['Code']:
            if entry['Price'] != new_entry['Price'] or entry['Volume'] != new_entry['Volume']:
                feed_gappers.pop(i)
                feed_gappers.insert(0, new_entry)
            return
    feed_gappers.insert(0, new_entry)

def fetch_tv_gainers():
    global auto_hot_symbols, feed_gappers
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ TradingView API 掃描 ({market_status})...", flush=True)
            
            sort_field = "premarket_change" if rank_type == "2" else "change"
            
            payload = {
                "filter": [
                    {"left": "close", "operation": "in_range", "right": [0.5, 50]},
                    {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
                ],
                "options": {"lang": "en"},
                "markets": ["america"],
                "symbols": {"query": {"types": []}, "tickers": []},
                "columns": ["name", "close", "change", "volume", "premarket_close", "premarket_change", "premarket_volume"],
                "sort": {"sortBy": sort_field, "sortOrder": "desc"},
                "range": [0, 30]
            }
            
            res = scraper.post("https://scanner.tradingview.com/america/scan", json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                new_found = []
                
                for item in reversed(data.get("data", [])):
                    cols = item.get("d", [])
                    if not cols or len(cols) < 7: continue
                    
                    sym_raw = str(cols[0])
                    sym = sym_raw.split(':')[-1] if ':' in sym_raw else sym_raw
                    
                    if '-' in sym or len(sym) > 4: continue
                        
                    if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                    new_found.append(sym)
                    
                    f, avg_vol, prev_close = get_static(sym)
                    float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                    
                    if rank_type == "2":
                        p_val_float = float(cols[4]) if cols[4] is not None else float(cols[1])
                        c_val_float = float(cols[5]) if cols[5] is not None else float(cols[2])
                        v_float = float(cols[6]) if cols[6] is not None else float(cols[3])
                    else:
                        p_val_float = float(cols[1]) if cols[1] is not None else 0.0
                        c_val_float = float(cols[2]) if cols[2] is not None else 0.0
                        v_float = float(cols[3]) if cols[3] is not None else 0.0
                    
                    c_amt_float = p_val_float - prev_close if prev_close > 0 else 0.0
                    chg_str = f"+{c_val_float:.2f}%" if c_val_float > 0 else f"{c_val_float:.2f}%"
                    chg_amt_str = f"+${c_amt_float:.2f}" if c_amt_float > 0 else f"-${abs(c_amt_float):.2f}"
                    rvol_val = (v_float / avg_vol) if avg_vol > 0 else 0.0
                    
                    new_entry = {
                        "Time": datetime.now(tz_tw).strftime('%H:%M:%S'), "Code": sym,
                        "Price": f"${p_val_float:.2f}",
                        "ChangeAmt": chg_amt_str, "Change": chg_str, 
                        "Volume": format_vol_km(v_float), "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "0.0x",
                        "FloatStr": float_str, "discovery_time": time.time()
                    }
                    update_or_add_gapper(new_entry)
                
                if new_found:
                    feed_gappers = feed_gappers[:1000]
                    auto_hot_symbols = auto_hot_symbols[:100] 
            else:
                pass
        except Exception as e:
            pass
        time.sleep(random.randint(3, 5))

# ==========================================
# ★ 主控引擎 (V16.2 雙鎖超時版)
# ==========================================
def scanner_engine():
    global feed_gappers, feed_hod, feed_surge
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    tz_ny = pytz.timezone('America/New_York')
    print("🔥 啟動 V16.2 流動性守護者版 (180秒超時註銷 + 300K/1.2x 雙鎖)...", flush=True)
    
    threading.Thread(target=fetch_tv_gainers, daemon=True).start()
    
    wait_count = 0
    while True:
        try:
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            now_ny_ts = datetime.now(tz_ny).timestamp()
            
            for gap_entry in feed_gappers:
                if "FloatStr" not in gap_entry or "ChangeAmt" not in gap_entry:
                    f, _, _ = get_static(gap_entry['Code'])
                    gap_entry['FloatStr'] = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                    if "ChangeAmt" not in gap_entry: gap_entry['ChangeAmt'] = "$0.00"

            symbols_to_track = list(set(auto_hot_symbols[:100]))
            
            if not symbols_to_track:
                if wait_count % 5 == 0: print(f"[{current_time_tw}] ⏳ 暫無足夠動能之股票，雷達待命中...", flush=True)
                wait_count += 1
                config.MASTER_BRAIN.update({"gappers": feed_gappers, "hod": feed_hod, "surge": feed_surge, "high_vol": [], "net_vol_leaders": [], "grinders": [], "news_leaders": [], "last_update": current_time_tw, "scan_count": count})
                count += 1
                time.sleep(2)
                continue
                
            wait_count = 0
            rank_type, market_status = get_market_rank_type()
            surge_vol_threshold = 2000 if rank_type == "2" else 10000
            
            with yf_lock:
                data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False, timeout=10, group_by='ticker', threads=10)
            
            extracted_stocks = []
            if not data_df.empty:
                for sym in symbols_to_track:
                    try:
                        if isinstance(data_df.columns, pd.MultiIndex):
                            if sym in data_df.columns.get_level_values(0):
                                close_series = data_df[sym]['Close'].dropna()
                                vol_series = data_df[sym]['Volume'].dropna()
                            elif 'Close' in data_df.columns.get_level_values(0) and sym in data_df['Close'].columns:
                                close_series = data_df['Close'][sym].dropna()
                                vol_series = data_df['Volume'][sym].dropna()
                        else:
                            if len(symbols_to_track) == 1 and 'Close' in data_df.columns:
                                close_series = data_df['Close'].dropna()
                                vol_series = data_df['Volume'].dropna()
                        
                        if not close_series.empty:
                            p_num = float(close_series.iloc[-1])
                            vol = float(vol_series.iloc[-1])
                            
                            ema49_val = 0.0
                            dist_3_ago = 999.0
                            ema49_is_uptrend = False
                            
                            if len(close_series) >= 10:
                                ema49_series = close_series.ewm(span=49, adjust=False).mean()
                                ema49_val = float(ema49_series.iloc[-1])
                                if len(ema49_series) >= 2:
                                    ema49_prev = float(ema49_series.iloc[-2])
                                    if ema49_val > ema49_prev:
                                        ema49_is_uptrend = True
                                
                                if len(close_series) >= 4:
                                    dist_3_ago = abs(float(close_series.iloc[-4]) - float(ema49_series.iloc[-4]))
                                
                            extracted_stocks.append({
                                'sym': sym, 'price': p_num, 'vol_raw': vol, 'rvol_tw': vol / 50000.0,
                                'ema49': ema49_val, 'dist_3_ago': dist_3_ago, 'ema49_is_uptrend': ema49_is_uptrend
                            })
                    except:
                        continue

            t_all = []
            active_grinders = []
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw']
                ema49 = data['ema49']
                dist_3_ago = data['dist_3_ago']
                ema49_is_uptrend = data['ema49_is_uptrend']
                
                f, a, prev_close = get_static(sym)
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                
                change_pct = ((p_num - prev_close) / prev_close * 100) if prev_close > 0 else 0
                change_str = f"+{change_pct:.2f}%" if change_pct > 0 else f"{change_pct:.2f}%"
                chg_amt = p_num - prev_close
                chg_amt_str = f"+${chg_amt:.2f}" if chg_amt > 0 else f"-${abs(chg_amt):.2f}"
                rvol_calc = (vol_raw / a) if a > 0 else 0.0
                
                for gap_entry in feed_gappers:
                    if gap_entry['Code'] == sym:
                        if "獲取中" in gap_entry['Price'] or "$0" in gap_entry['Price']: gap_entry['Price'] = f"${p_num:.2f}"
                        if gap_entry['Volume'] == "0K" or gap_entry['Volume'] == "0": gap_entry['Volume'] = format_vol_km(vol_raw)
                        if "雷達" in gap_entry['RVOL'] or "計算中" in gap_entry['RVOL'] or gap_entry['RVOL'] == "0.0x": gap_entry['RVOL'] = f"{rvol_calc:.1f}x"
                        if "0%" in gap_entry['Change'] or gap_entry['Change'] == "0": gap_entry['Change'] = change_str
                        if "$0.00" in gap_entry.get('ChangeAmt', '$0.00'): gap_entry['ChangeAmt'] = chg_amt_str
                        gap_entry['FloatStr'] = float_str
                
                is_new_stock = sym not in config.MASTER_BRAIN["details"]
                initial_hod = (p_num * 0.98) if is_new_stock else p_num
                
                cell = config.MASTER_BRAIN["details"].get(sym, {})
                cell.setdefault("HOD", initial_hod)
                cell.setdefault("NewsList", [])
                cell.setdefault("max_news_score", 0)
                cell.setdefault("streak", 0)
                cell.setdefault("last_price", p_num)
                cell.setdefault("cum_buy_vol", 0)
                cell.setdefault("cum_sell_vol", 0)
                cell.setdefault("is_grinder", False)
                cell.setdefault("recent_high", initial_hod)
                cell.setdefault("is_pullback", False)
                
                # 🚨 V16.2 Timeout 屬性初始化
                cell.setdefault("sniper_start_time", 0)
                cell.setdefault("sniper_label_last", "")
                
                cell.setdefault("surge_start_price", initial_hod)
                cell.setdefault("max_surge_vol", 0)
                cell.setdefault("pullback_low", p_num)
                cell.setdefault("pos_vol_streak", 0)
                cell.setdefault("neg_vol_streak", 0)
                cell.setdefault("GrindCount", 0)
                
                has_fresh_news = False
                for news in cell.get("NewsList", []):
                    pub_ts = news.get("pub_ts", 0)
                    if pub_ts > 0 and (now_ny_ts - pub_ts) <= 600:
                        has_fresh_news = True
                        break

                is_hod_break = False
                if p_num > cell["HOD"]: 
                    cell["HOD"] = p_num
                    cell["streak"] += 1
                    is_hod_break = True
                
                last_price = cell["last_price"]
                curr_vol_delta = vol_raw
                
                if curr_vol_delta > 0:
                    if p_num > last_price:
                        cell["cum_buy_vol"] += curr_vol_delta
                        cell["pos_vol_streak"] += 1
                        cell["neg_vol_streak"] = 0
                        cell["GrindCount"] += 1
                    elif p_num < last_price:
                        cell["cum_sell_vol"] += curr_vol_delta
                        cell["neg_vol_streak"] += 1
                        cell["pos_vol_streak"] = 0
                        cell["GrindCount"] -= 1
                net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]

                if cell["GrindCount"] >= 3 and cell["pos_vol_streak"] >= 3 and vol_raw < 500000:
                    cell["is_grinder"] = True
                    active_grinders.append({"Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}", "Streak": f"🔥無量緩推(連{cell['pos_vol_streak']}分)", "ChangeAmt": chg_amt_str, "Change": change_str, "GrindCount": cell["GrindCount"]})
                elif cell["GrindCount"] <= -2:
                    cell["is_grinder"] = False

                recent_high = cell["recent_high"]
                surge_start_price = cell["surge_start_price"]
                is_pullback = cell["is_pullback"]
                max_surge_vol = cell["max_surge_vol"]
                
                # 🚨 V16.2 條件判定區
                sniper_triggered_this_tick = False
                sniper_label_this_tick = ""
                
                dist_to_hod = (cell["HOD"] - p_num) / p_num if p_num > 0 else 1
                if 0 < dist_to_hod <= 0.015 and vol_raw >= surge_vol_threshold * 0.5:
                    sniper_triggered_this_tick = True
                    sniper_label_this_tick = "⏳準備突破"
                
                # 🚨 V16.2 終極流動性雙重鎖 (總量 > 30萬 且 RVOL > 1.2x)
                if ema49 > 0 and ema49_is_uptrend and vol_raw >= 300000 and rvol_calc >= 1.2:
                    dist_now = abs(p_num - ema49)
                    if 0.1 <= dist_now <= 0.3 and dist_3_ago > dist_now * 2:
                        sniper_triggered_this_tick = True
                        sniper_label_this_tick = "🧲EMA多頭(帶量)"
                
                if p_num > recent_high:
                    if is_pullback:
                        if p_num > cell["pullback_low"] * 1.01: 
                            sniper_triggered_this_tick = True
                            sniper_label_this_tick = "🎯精準回調"
                        is_pullback = False
                        surge_start_price = p_num
                        max_surge_vol = curr_vol_delta
                    else: max_surge_vol = max(max_surge_vol, curr_vol_delta)
                    recent_high = p_num
                    
                    if is_hod_break:
                        if curr_vol_delta > max_surge_vol * 1.5 and max_surge_vol > 0: 
                            sniper_triggered_this_tick = True
                            sniper_label_this_tick = "⚠️爆量突破"
                        elif curr_vol_delta > 0 and curr_vol_delta < 5000: 
                            sniper_triggered_this_tick = True
                            sniper_label_this_tick = "⚠️虛漲(無量誘多)"
                            
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    if retrace_ratio <= 0.50:
                        if not is_pullback: 
                            is_pullback = True
                            cell["pullback_low"] = p_num
                        else: cell["pullback_low"] = min(cell["pullback_low"], p_num)
                    else: is_pullback = False 

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
                cell["is_pullback"] = is_pullback
                cell["max_surge_vol"] = max_surge_vol
                
                # 🚨 V16.2 超時 (Timeout) 判斷機制：超過 180 秒自動註銷
                if sniper_triggered_this_tick:
                    if cell.get("sniper_label_last") != sniper_label_this_tick:
                        cell["sniper_start_time"] = time.time()
                        cell["sniper_label_last"] = sniper_label_this_tick
                    
                    if time.time() - cell.get("sniper_start_time", time.time()) > 180:
                        sniper_triggered_this_tick = False # 已超時，消滅燈號
                        sniper_label_this_tick = ""
                else:
                    cell["sniper_start_time"] = 0
                    cell["sniper_label_last"] = ""
                
                # 更新最終狀態
                cell["sniper_triggered"] = sniper_triggered_this_tick
                cell["sniper_label"] = sniper_label_this_tick
                
                streak_text = f"x{cell['streak']}"
                if is_hod_break: streak_text = f"⭐破高+{cell['sniper_label']}" if sniper_triggered_this_tick else f"⭐破高{streak_text}"
                elif sniper_triggered_this_tick: streak_text = f"{cell['sniper_label']}"

                has_catalyst = False
                for news in cell["NewsList"]:
                    for kw in CATALYST_KEYWORDS:
                        if kw in news.get("title", "").upper(): has_catalyst = True; cell["max_news_score"] += 10; break
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "ChangeAmt": chg_amt_str, "Change": change_str, 
                    "Volume": format_vol_km(vol_raw), "vol_raw": vol_raw,
                    "RVOL": f"{rvol_calc:.1f}x", "FloatStr": float_str, "Streak": streak_text,
                    "NetVolNum": net_vol, "NewsScore": cell["max_news_score"], "HasCatalyst": has_catalyst, 
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]), "SellVolStr": format_vol_km(cell["cum_sell_vol"]),
                    "HasFreshNews": has_fresh_news, "FloatNum": f, "RvolNum": rvol_calc
                }

                t_all.append(item)
                if is_hod_break: feed_hod.insert(0, item)
                
                # 送入短線動能追蹤表
                if sniper_triggered_this_tick or (cell["streak"] >= 2 and is_hod_break and curr_vol_delta > surge_vol_threshold):
                    if not sniper_triggered_this_tick: item["Streak"] = "⚡極速(9EMA)"
                    feed_surge.insert(0, item)

                if count % 30 == 0 or not cell["NewsList"]: 
                    if not cell["NewsList"]: cell["NewsList"] = [{"id": "0", "title": "🗞️ 正在直連華爾街公關專線擷取新聞...", "score": 0, "link": f"https://www.tradingview.com/chart/?symbol={sym}", "time": "", "is_today": False}]
                    news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"
                cell["last_price"] = p_num
                cell["RVOL"] = item["RVOL"]
                cell["FloatStr"] = float_str
                
                config.MASTER_BRAIN["details"][sym] = cell

            count += 1
            feed_hod = feed_hod[:1000]
            feed_surge = feed_surge[:1000]
            
            gappers_sorted = sorted(feed_gappers, key=lambda x: x.get("discovery_time", 0), reverse=True)
            news_valid = [x for x in t_all if x['NewsScore'] > 0 and x['HasCatalyst']]
            high_vol_sorted = sorted(t_all, key=lambda x: x['vol_raw'], reverse=True)
            net_vol_sorted = sorted(t_all, key=lambda x: x['NetVolNum'], reverse=True)
            grind_sorted = sorted(active_grinders, key=lambda x: x.get("GrindCount", 0), reverse=True)
            news_sorted = sorted(news_valid, key=lambda x: x['NewsScore'], reverse=True)
            
            config.MASTER_BRAIN.update({
                "gappers": gappers_sorted[:1000],                 
                "hod": feed_hod,                         
                "surge": feed_surge,                       
                "high_vol": high_vol_sorted[:1000],       
                "net_vol_leaders": net_vol_sorted[:1000], 
                "grinders": grind_sorted[:1000],          
                "news_leaders": news_sorted[:1000],       
                "last_update": current_time_tw, 
                "scan_count": count
            })
            
            time.sleep(3)
            
        except Exception as e:
            if "database is locked" not in str(e) and "NoneType" not in str(e): print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 引擎錯誤 (已防護): {e}", flush=True)
            time.sleep(5)
