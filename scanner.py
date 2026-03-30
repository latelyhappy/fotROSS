import time, threading, requests, os, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright
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

# ==========================================
# 🌐 Google 神經網路翻譯引擎
# ==========================================
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

# ==========================================
# 📰 華爾街直連公關專線 (已修復 JSON 當機 Bug)
# ==========================================
def fetch_direct_news_bg(ticker, cell):
    try:
        # 🚨 關鍵修復：把 set() 換成 list []，防止 jsonify 傳輸時當機！
        if "raw_news_titles" not in cell: cell["raw_news_titles"] = []
            
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        today_str = now_ny.strftime("%Y-%m-%d")
        
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        res = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        xml_text = res.text
        
        titles = re.findall(r'<title>(.*?)</title>', xml_text)
        links = re.findall(r'<link>(.*?)</link>', xml_text)
        dates = re.findall(r'<pubDate>(.*?)</pubDate>', xml_text)
        
        if titles and "Yahoo! Finance" in titles[0]:
            titles = titles[1:]
            links = links[1:]
            
        new_articles = []
        for i in range(min(len(titles), len(dates))):
            raw_title = titles[i].replace("<![CDATA[", "").replace("]]>", "").strip()
            raw_link = links[i] if i < len(links) else f"https://finance.yahoo.com/quote/{ticker}/news"
            pub_date_str = dates[i].strip()
            
            if not raw_title: continue
            
            # 陣列搜尋法
            if raw_title in cell["raw_news_titles"]: continue
                
            try:
                clean_str = pub_date_str[:-6].strip() 
                pub_dt = datetime.strptime(clean_str, "%a, %d %b %Y %H:%M:%S")
                pub_date_only = pub_dt.strftime("%Y-%m-%d")
                pub_time_only = pub_dt.strftime("%H:%M")
                days_diff = (now_ny.date() - pub_dt.date()).days
            except Exception as e:
                days_diff, pub_date_only, pub_time_only = 0, "", ""
                
            if days_diff > 4: break 
                
            is_today = (pub_date_only == today_str)
            display_str = f"{pub_time_only}" if is_today else f"{pub_date_only[5:]} {pub_time_only}"
            
            log_debug(ticker, f"✨ 發現新公關稿！啟動翻譯: {pub_date_only} {pub_time_only} | {raw_title[:20]}...")
            translated_title = translate_to_zh(raw_title)
            
            # 存入陣列中
            cell["raw_news_titles"].append(raw_title)
            
            new_articles.append({
                "id": str(random.randint(10000, 99999)), "title": translated_title,
                "score": 0, "link": raw_link, "time": display_str, "is_today": is_today, "is_read": False
            })
            if len(new_articles) >= 5: break
            
        if new_articles:
            clean_old_list = [n for n in cell.get("NewsList", []) if "🗞️" not in n.get("title", "")]
            cell["NewsList"] = (new_articles + clean_old_list)[:5]
            log_debug(ticker, f"🎉 成功新增並翻譯 {len(new_articles)} 筆突發新聞！")
        elif not cell.get("NewsList") or "🗞️" in cell["NewsList"][0].get("title", ""):
            tw_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            cell["NewsList"] = [{"id": "0", "title": "🗞️ 點擊前往 TradingView (近4天無新聞)", "score": 0, "link": tw_url, "time": "", "is_today": False}]
            
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

# ==========================================
# ★ 混血先鋒飆股雷達 (微牛為主，StockAnalysis 備用)
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols, feed_gappers
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ Webull 排行榜掃描 ({market_status})...", flush=True)
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                context = browser.new_context(user_agent="Mozilla/5.0")
                page = context.new_page()
                page.goto("https://app.webull.com/screener", timeout=30000)
                time.sleep(3) 
                
                sort_id = "fm_53" if rank_type == "2" else "fm_12"
                
                js_code = f"""
                async () => {{
                    const payload = {{
                        "fetch": 30,
                        "rules": [
                            {{"proId": "fm_13", "rule": "between", "val": ["0.5", "50"]}},
                            {{"proId": "fm_43", "rule": "between", "val": ["0", "999999999"]}},
                            {{"proId": "fm_14", "rule": "between", "val": ["100", "999999999"]}}
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
                for item in reversed(data.get('data', [])):
                    sym = item.get('ticker', {}).get('symbol')
                    if sym and '-' not in sym:
                        if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                        new_found.append(sym)
                        
                        f, avg_vol, prev_close = get_static(sym)
                        float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                        
                        price_raw = item.get('price') or item.get('pPrice') or item.get('close') or '0'
                        changeRatio = item.get('changeRatio') or item.get('pChangeRatio') or '0'
                        changeAmt_raw = item.get('change') or item.get('pChange') or '0'
                        vol = item.get('volume') or item.get('pVolume') or '0'
                        
                        try: vol_float = float(vol)
                        except: vol_float = 0.0
                        
                        try: chg_float = float(changeRatio) * 100
                        except: chg_float = 0.0
                        chg_str = f"+{chg_float:.2f}%" if chg_float > 0 else f"{chg_float:.2f}%"
                        
                        try: chg_amt_float = float(changeAmt_raw)
                        except: chg_amt_float = 0.0
                        chg_amt_str = f"+${chg_amt_float:.2f}" if chg_amt_float > 0 else f"-${abs(chg_amt_float):.2f}"
                        
                        rvol_val = (vol_float / 50000.0) if avg_vol == 500000 else (vol_float / avg_vol)
                        
                        new_entry = {
                            "Time": datetime.now(tz_tw).strftime('%H:%M:%S'), "Code": sym,
                            "Price": f"${float(price_raw):.2f}" if float(price_raw) > 0 else "獲取中",
                            "ChangeAmt": chg_amt_str, "Change": chg_str, "Volume": format_vol_km(vol_float),
                            "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "0.0x", "FloatStr": float_str,
                            "discovery_time": time.time()
                        }
                        update_or_add_gapper(new_entry)
                
                if new_found:
                    feed_gappers = feed_gappers[:1000]
                    auto_hot_symbols = auto_hot_symbols[:200] 
                elif not data.get('data', []):
                    raise ValueError("API回傳空名單")
                    
        except Exception as e:
            # 🚨 無縫切換：當微牛給空資料時，瞬間啟動 StockAnalysis 極限早鳥備用雷達！
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 微牛尚無資料，啟動 StockAnalysis 備用雷達...", flush=True)
            try:
                rank_type, _ = get_market_rank_type()
                url = "https://stockanalysis.com/markets/premarket/" if rank_type == "2" else "https://stockanalysis.com/markets/gainers/"
                
                res = scraper.get(url, timeout=15)
                df_list = pd.read_html(StringIO(res.text))
                
                if df_list:
                    df = df_list[0]
                    price_col = next((c for c in df.columns if 'price' in c.lower() or 'last' in c.lower()), None)
                    change_col = next((c for c in df.columns if '%' in c or 'change' in c.lower()), None)
                    change_amt_col = next((c for c in df.columns if 'change' in c.lower() and '%' not in c), None)
                    vol_col = next((c for c in df.columns if 'vol' in c.lower()), None)
                    
                    new_found = []
                    for idx, row in df.iloc[::-1].iterrows():
                        sym = str(row.get('Symbol', ''))
                        if sym and '-' not in sym:
                            p_val_str = str(row[price_col]).replace('$', '') if price_col and pd.notna(row[price_col]) else '0'
                            
                            try: p_val_float = float(p_val_str)
                            except: p_val_float = 0.0
                            
                            # 🎯 嚴格遵守 ROSS 紀律：備用雷達也要過濾 0.5 ~ 50 塊！
                            if p_val_float < 0.5 or p_val_float > 50:
                                continue
                                
                            if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                            new_found.append(sym)
                            f, avg_vol, prev_close = get_static(sym)
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            c_val = str(row[change_col]) if change_col and pd.notna(row[change_col]) else '0%'
                            c_amt_val = str(row[change_amt_col]).replace('+', '').replace('$', '') if change_amt_col and pd.notna(row[change_amt_col]) else '0'
                            v_float = parse_vol_to_float(row[vol_col]) if vol_col and pd.notna(row[vol_col]) else 0.0
                            try: c_amt_float = float(c_amt_val)
                            except: c_amt_float = 0.0
                            chg_amt_str = f"+${c_amt_float:.2f}" if c_amt_float > 0 else f"-${abs(c_amt_float):.2f}"
                            rvol_val = (v_float / 50000.0) if avg_vol == 500000 else (v_float / avg_vol)
                            
                            new_entry = {
                                "Time": datetime.now(tz_tw).strftime('%H:%M:%S'), "Code": sym,
                                "Price": f"${p_val_float:.2f}",
                                "ChangeAmt": chg_amt_str, "Change": c_val if '%' in c_val else f"{c_val}%",
                                "Volume": format_vol_km(v_float), "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "0.0x",
                                "FloatStr": float_str, "discovery_time": time.time()
                            }
                            update_or_add_gapper(new_entry)
                            
                            if len(new_found) >= 30: break # 最多只抓 30 檔
                            
                    if new_found:
                        feed_gappers = feed_gappers[:1000]
                        auto_hot_symbols = auto_hot_symbols[:200]
            except Exception as ex:
                pass
                
        time.sleep(random.randint(4, 12))

# ==========================================
# ★ 主控引擎
# ==========================================
def scanner_engine():
    global feed_gappers, feed_hod, feed_surge
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動 V13.1 (修復 JSON 當機 Bug 穩定版)...", flush=True)
    
    threading.Thread(target=fetch_webull_gainers, daemon=True).start()
    
    wait_count = 0
    while True:
        try:
            loop_start_time = time.time()
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            
            for gap_entry in feed_gappers:
                if "FloatStr" not in gap_entry or "ChangeAmt" not in gap_entry:
                    f, _, _ = get_static(gap_entry['Code'])
                    gap_entry['FloatStr'] = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                    if "ChangeAmt" not in gap_entry: gap_entry['ChangeAmt'] = "$0.00"

            symbols_to_track = list(set(auto_hot_symbols[:200]))
            
            if not symbols_to_track:
                if wait_count % 5 == 0: print(f"[{current_time_tw}] ⏳ 無足夠交易量，雷達待命中...", flush=True)
                wait_count += 1
                config.MASTER_BRAIN.update({
                    "gappers": feed_gappers, "hod": feed_hod, "surge": feed_surge,
                    "high_vol": [], "net_vol_leaders": [], "grinders": [], "news_leaders": [],
                    "last_update": current_time_tw, "scan_count": count
                })
                count += 1
                time.sleep(2)
                continue
                
            wait_count = 0
            
            with yf_lock:
                data_df = yf.download(symbols_to_track, period='1d', interval='1m', prepost=True, progress=False, timeout=10, group_by='ticker')
            
            extracted_stocks = []
            if not data_df.empty:
                for sym in symbols_to_track:
                    try:
                        price, vol = 0.0, 0.0
                        if isinstance(data_df.columns, pd.MultiIndex):
                            if sym in data_df.columns.get_level_values(0):
                                price = float(data_df[sym]['Close'].dropna().iloc[-1])
                                vol = float(data_df[sym]['Volume'].dropna().iloc[-1])
                            elif 'Close' in data_df.columns.get_level_values(0) and sym in data_df['Close'].columns:
                                price = float(data_df['Close'][sym].dropna().iloc[-1])
                                vol = float(data_df['Volume'][sym].dropna().iloc[-1])
                        else:
                            if len(symbols_to_track) == 1 and 'Close' in data_df.columns:
                                price = float(data_df['Close'].dropna().iloc[-1])
                                vol = float(data_df['Volume'].dropna().iloc[-1])
                                
                        if pd.notna(price) and price > 0:
                            extracted_stocks.append({'sym': sym, 'price': price, 'vol_raw': vol, 'rvol_tw': vol / 50000.0})
                    except:
                        continue

            t_all = []
            current_t = time.time()
            active_grinders = []
            
            for data in extracted_stocks:
                sym = data['sym']
                p_num = data['price']
                vol_raw = data['vol_raw']
                rvol = data['rvol_tw']
                
                f, a, prev_close = get_static(sym)
                float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                
                change_pct = ((p_num - prev_close) / prev_close * 100) if prev_close > 0 else 0
                change_str = f"+{change_pct:.2f}%" if change_pct > 0 else f"{change_pct:.2f}%"
                chg_amt = p_num - prev_close
                chg_amt_str = f"+${chg_amt:.2f}" if chg_amt > 0 else f"-${abs(chg_amt):.2f}"
                
                for gap_entry in feed_gappers:
                    if gap_entry['Code'] == sym:
                        if "獲取中" in gap_entry['Price'] or "$0" in gap_entry['Price']: gap_entry['Price'] = f"${p_num:.2f}"
                        if gap_entry['Volume'] == "0K" or gap_entry['Volume'] == "0": gap_entry['Volume'] = format_vol_km(vol_raw)
                        if "雷達" in gap_entry['RVOL'] or "計算中" in gap_entry['RVOL'] or gap_entry['RVOL'] == "0.0x": gap_entry['RVOL'] = f"{rvol:.1f}x"
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
                cell.setdefault("sniper_triggered", False)
                cell.setdefault("surge_start_price", initial_hod)
                cell.setdefault("max_surge_vol", 0)
                cell.setdefault("pullback_low", p_num)
                cell.setdefault("sniper_label", "")
                cell.setdefault("pos_vol_streak", 0)
                cell.setdefault("neg_vol_streak", 0)
                cell.setdefault("GrindCount", 0)
                
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
                sniper_triggered = False
                sniper_label = ""
                
                if p_num > recent_high:
                    if is_pullback:
                        if p_num > cell["pullback_low"] * 1.01: sniper_triggered = True; sniper_label = "🎯精準回調"
                        is_pullback = False
                        surge_start_price = p_num
                        max_surge_vol = curr_vol_delta
                    else: max_surge_vol = max(max_surge_vol, curr_vol_delta)
                    recent_high = p_num
                    if is_hod_break:
                        if curr_vol_delta > max_surge_vol * 1.5 and max_surge_vol > 0: sniper_triggered = True; sniper_label = "⚠️爆量(短線留意)"
                        elif curr_vol_delta > 0 and curr_vol_delta < 5000: sniper_triggered = True; sniper_label = "⚠️虛漲(無量誘多)"
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    if retrace_ratio <= 0.50:
                        if not is_pullback: is_pullback = True; cell["pullback_low"] = p_num
                        else: cell["pullback_low"] = min(cell["pullback_low"], p_num)
                    else: is_pullback = False 

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
                cell["is_pullback"] = is_pullback
                cell["max_surge_vol"] = max_surge_vol
                cell["sniper_triggered"] = sniper_triggered
                if sniper_triggered: cell["sniper_label"] = sniper_label
                
                streak_text = f"x{cell['streak']}"
                if is_hod_break: streak_text = f"⭐破高+{cell['sniper_label']}" if sniper_triggered else f"⭐破高{streak_text}"
                elif sniper_triggered: streak_text = f"{cell['sniper_label']}"

                has_catalyst = False
                for news in cell["NewsList"]:
                    for kw in CATALYST_KEYWORDS:
                        if kw in news.get("title", "").upper(): has_catalyst = True; cell["max_news_score"] += 10; break
                
                item = {
                    "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                    "ChangeAmt": chg_amt_str, "Change": change_str, 
                    "Volume": format_vol_km(vol_raw), "vol_raw": vol_raw,
                    "RVOL": f"{rvol:.1f}x", "FloatStr": float_str, "Streak": streak_text,
                    "NetVolNum": net_vol, "NewsScore": cell["max_news_score"], "HasCatalyst": has_catalyst, 
                    "NetVolStr": f"+{format_vol_km(net_vol)}" if net_vol > 0 else f"-{format_vol_km(abs(net_vol))}",
                    "BuyVolStr": format_vol_km(cell["cum_buy_vol"]), "SellVolStr": format_vol_km(cell["cum_sell_vol"])
                }

                t_all.append(item)
                if is_hod_break: feed_hod.insert(0, item)
                if sniper_triggered or (cell["streak"] >= 2 and is_hod_break and curr_vol_delta > 10000):
                    if not sniper_triggered: item["Streak"] = "⚡極速(9EMA)"
                    feed_surge.insert(0, item)

                if count % 30 == 0 or not cell["NewsList"]: 
                    if not cell["NewsList"]: cell["NewsList"] = [{"id": "0", "title": "🗞️ 正在直連華爾街公關專線擷取新聞...", "score": 0, "link": f"https://www.tradingview.com/chart/?symbol={sym}", "time": "", "is_today": False}]
                    news_task_pool.submit(fetch_direct_news_bg, sym, cell)
                    
                cell["HOD_str"] = f"${cell['HOD']:.2f}"
                cell["last_price"] = p_num
                cell["RVOL"] = f"{rvol:.1f}x"
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
            
            time.sleep(random.randint(4, 12))
            
        except Exception as e:
            if "database is locked" not in str(e) and "NoneType" not in str(e): print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 引擎錯誤 (已防護): {e}", flush=True)
            time.sleep(5)
