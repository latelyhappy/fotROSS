import time, threading, requests, os, random
from datetime import datetime
import pytz
import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright
from io import StringIO 
import re, json
from concurrent.futures import ThreadPoolExecutor

import config

# 🌟 全域背景執行緒池
bg_task_pool = ThreadPoolExecutor(max_workers=10)

# 🌟 Yahoo 資料庫紅綠燈
yf_lock = threading.Lock()

# 🛡️ Cloudscraper 破甲防護模組 & 自訂 User-Agent
try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    print("🛡️ 已啟動 Cloudscraper 破甲模式！")
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
# 🔍 核心武器：遞迴 JSON 拆解器 (不漏接任何新聞)
# ==========================================
def find_news_in_json(obj, results=None):
    if results is None:
        results = []
    if isinstance(obj, dict):
        # 只要字典裡同時包含這三個關鍵字，就判定為新聞物件！
        if "title" in obj and "newsTime" in obj and "newsUrl" in obj:
            if len(obj["title"]) > 10 and "Webull" not in obj["title"]:
                results.append({
                    "title": obj["title"],
                    "newsTime": obj["newsTime"],
                    "newsUrl": obj["newsUrl"],
                    "id": obj.get("id", str(random.randint(1000, 99999)))
                })
        for key, value in obj.items():
            find_news_in_json(value, results)
    elif isinstance(obj, list):
        for item in obj:
            find_news_in_json(item, results)
    return results

# ==========================================
# 📰 微牛 (Webull) 公開網頁暴力爬蟲引擎
# ==========================================
def fetch_webull_news_bg(ticker, cell):
    try:
        # 🛡️ 隨機秒數等待 (0.5 ~ 2秒)，打破機械化節奏
        time.sleep(random.uniform(0.5, 2.0))
        
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        today_str = now_ny.strftime("%Y-%m-%d")
        
        search_url = f"https://quotes-gw.webullfintech.com/api/search/pc/tickers?keyword={ticker}&regionId=6&pageIndex=1&pageSize=1"
        res = scraper.get(search_url, timeout=10)
        data = res.json()
        ticker_list = data.get("data", [])
        if not ticker_list:
            raise ValueError("查無微牛代碼")
            
        t_info = ticker_list[0]
        ticker_id = t_info.get("tickerId")
        exchange = str(t_info.get("disExchangeCode", "nasdaq")).lower()
        
        # 2. 模擬真人訪問 Webull 公開網頁版新聞區
        web_url = f"https://www.webull.com/quote/{exchange}-{ticker.lower()}/news"
        html_res = scraper.get(web_url, timeout=15)
        html_text = html_res.text
        
        raw_news = []
        
        # 3. 暴力挖礦：找出 __NEXT_DATA__ 並用遞迴拆解器找出所有新聞！
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.DOTALL)
        if match:
            try:
                json_data = json.loads(match.group(1))
                raw_news = find_news_in_json(json_data)
            except: pass
            
        # 4. 如果網頁底層真的被掏空了，啟動 API 備案通道 (即使沒登入也碰碰運氣)
        if not raw_news:
            api_url = f"https://quotes-gw.webullfintech.com/api/information/news/v8/tickerNews?tickerId={ticker_id}&currentNewsId=0&pageSize=10"
            api_res = scraper.get(api_url, timeout=10).json()
            api_news = api_res.get("news", [])
            for n in api_news:
                raw_news.append({
                    "title": n.get("title", ""),
                    "newsTime": n.get("newsTime", ""),
                    "newsUrl": n.get("newsUrl", web_url),
                    "id": str(n.get("id", random.randint(1000, 99999)))
                })

        # 5. 過濾 4 天前的新聞，並標記今日顏色
        valid_news = []
        # 用標題做去重，避免微牛重複推送
        seen_titles = set()
        
        for n in raw_news:
            title = n.get("title", "")
            link = n.get("newsUrl", web_url)
            pub_time_str = n.get("newsTime", "")
            
            if not title or not pub_time_str or title in seen_titles: continue
            seen_titles.add(title)
            
            # 時間計算 (支援 2026-03-27 15:30:00 與 2026-03-27T15:30:00Z 兩種格式)
            try:
                pub_date_only = pub_time_str[:10]
                pub_dt = datetime.strptime(pub_date_only, "%Y-%m-%d")
                days_diff = (now_ny.date() - pub_dt.date()).days
            except:
                days_diff = 0
                pub_date_only = ""
                
            # 【需求】：最多讀取 4 天前的新聞
            if days_diff > 4: 
                continue
                
            # 【需求】：當天日期判斷 (前端會變橘色)
            is_today = (pub_date_only == today_str)
                
            # 擷取顯示文字 (今日只顯示 HH:MM，其他顯示 MM-DD)
            # 處理 'T' 格式的字串
            clean_time_str = pub_time_str.replace('T', ' ')
            time_display = clean_time_str[11:16] if len(clean_time_str) >= 16 else ""
            date_display = clean_time_str[5:10] if len(clean_time_str) >= 10 else ""
            display_str = f"{time_display}" if is_today else f"{date_display} {time_display}"
            
            valid_news.append({
                "id": str(n.get("id", random.randint(1000, 99999))),
                "title": title,
                "score": 0,
                "link": link,
                "time": display_str,
                "is_today": is_today,
                "is_read": False
            })
            
            if len(valid_news) >= 5: break
            
        if valid_news:
            cell["NewsList"] = valid_news
        else:
            tw_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
            cell["NewsList"] = [{"id": "0", "title": "🗞️ 點擊前往 TradingView (近4天無新聞)", "score": 0, "link": tw_url, "time": "", "is_today": False}]
            
    except Exception as e:
        tw_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
        cell["NewsList"] = [{"id": "0", "title": f"🗞️ 微牛網頁爬蟲遭阻擋，點此看線圖", "score": 0, "link": tw_url, "time": "", "is_today": False}]


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
        bg_task_pool.submit(fetch_static_bg, ticker)
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
# ★ Webull 飆股主引擎 (嚴守 ROSS 排行榜邏輯)
# ==========================================
def fetch_webull_gainers():
    global auto_hot_symbols, feed_gappers
    tz_tw = pytz.timezone('Asia/Taipei')
    
    while True:
        try:
            rank_type, market_status = get_market_rank_type()
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🕵️‍♂️ Webull 排行榜篩選中 ({market_status})...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
                page = context.new_page()
                page.goto("https://app.webull.com/screener", timeout=30000)
                time.sleep(4) 
                
                sort_id = "fm_53" if rank_type == "2" else "fm_12"
                min_vol = "5000" if rank_type == "2" else "50000"
                
                js_code = f"""
                async () => {{
                    const payload = {{
                        "fetch": 30,
                        "rules": [
                            {{"proId": "fm_13", "rule": "between", "val": ["1", "20"]}},       
                            {{"proId": "fm_43", "rule": "between", "val": ["0", "20000000"]}}, 
                            {{"proId": "fm_14", "rule": "between", "val": ["{min_vol}", "999999999"]}}
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
                            "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                            "Code": sym,
                            "Price": f"${float(price_raw):.2f}" if float(price_raw) > 0 else "獲取中",
                            "ChangeAmt": chg_amt_str,
                            "Change": chg_str,
                            "Volume": format_vol_km(vol_float),
                            "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "0.0x",
                            "FloatStr": float_str,
                            "discovery_time": time.time()
                        }
                        update_or_add_gapper(new_entry)
                
                if new_found:
                    feed_gappers = feed_gappers[:1000]
                    auto_hot_symbols = auto_hot_symbols[:200] 
                elif not data.get('data', []):
                    raise ValueError("深夜靜音模式切換")
                    
        except Exception as e:
            if "深夜靜音模式切換" not in str(e):
                print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 Webull 篩選失敗，切換備用雷達...")
                
            try:
                rank_type, _ = get_market_rank_type()
                if rank_type == "2": url = "https://stockanalysis.com/markets/premarket/"
                elif rank_type == "1": url = "https://stockanalysis.com/markets/after-hours/"
                else: url = "https://stockanalysis.com/markets/gainers/"
                
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
                        if idx > 29: continue
                        sym = str(row.get('Symbol', ''))
                        if sym and '-' not in sym:
                            if sym not in auto_hot_symbols: auto_hot_symbols.insert(0, sym)
                            new_found.append(sym)
                            
                            f, avg_vol, prev_close = get_static(sym)
                            float_str = f"{f/1e6:.1f}M" if f >= 1e6 else f"{f/1e3:.0f}K"
                            
                            p_val = str(row[price_col]).replace('$', '') if price_col and pd.notna(row[price_col]) else '0'
                            c_val = str(row[change_col]) if change_col and pd.notna(row[change_col]) else '0%'
                            c_amt_val = str(row[change_amt_col]).replace('+', '').replace('$', '') if change_amt_col and pd.notna(row[change_amt_col]) else '0'
                            
                            v_float = parse_vol_to_float(row[vol_col]) if vol_col and pd.notna(row[vol_col]) else 0.0
                            
                            try: c_amt_float = float(c_amt_val)
                            except: c_amt_float = 0.0
                            chg_amt_str = f"+${c_amt_float:.2f}" if c_amt_float > 0 else f"-${abs(c_amt_float):.2f}"
                            
                            rvol_val = (v_float / 50000.0) if avg_vol == 500000 else (v_float / avg_vol)
                            
                            new_entry = {
                                "Time": datetime.now(tz_tw).strftime('%H:%M:%S'),
                                "Code": sym,
                                "Price": f"${p_val}" if not p_val.startswith('$') else p_val,
                                "ChangeAmt": chg_amt_str,
                                "Change": c_val if '%' in c_val else f"{c_val}%",
                                "Volume": format_vol_km(v_float),
                                "RVOL": f"{rvol_val:.1f}x" if rvol_val > 0 else "0.0x",
                                "FloatStr": float_str,
                                "discovery_time": time.time()
                            }
                            update_or_add_gapper(new_entry)
                            
                    if new_found:
                        feed_gappers = feed_gappers[:1000]
                        auto_hot_symbols = auto_hot_symbols[:200]
            except Exception as ex:
                pass
                
        time.sleep(random.randint(4, 12))

# ==========================================
# ★ 副引擎 (只追蹤排行榜中的名單，嚴守 ROSS 紀律)
# ==========================================
def scanner_engine():
    global feed_gappers, feed_hod, feed_surge
    count = 0
    tz_tw = pytz.timezone('Asia/Taipei')
    print("🔥 啟動 V12.1 (微牛新聞無死角暴力拆解版)...")
    
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
                if wait_count % 5 == 0: print(f"[{current_time_tw}] ⏳ 無足夠交易量，雷達待命中...")
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
                        if "獲取中" in gap_entry['Price'] or "$0" in gap_entry['Price']:
                            gap_entry['Price'] = f"${p_num:.2f}"
                        if gap_entry['Volume'] == "0K" or gap_entry['Volume'] == "0":
                            gap_entry['Volume'] = format_vol_km(vol_raw)
                        if "雷達" in gap_entry['RVOL'] or "計算中" in gap_entry['RVOL'] or gap_entry['RVOL'] == "0.0x":
                            gap_entry['RVOL'] = f"{rvol:.1f}x"
                        if "0%" in gap_entry['Change'] or gap_entry['Change'] == "0":
                            gap_entry['Change'] = change_str
                        if "$0.00" in gap_entry.get('ChangeAmt', '$0.00'):
                            gap_entry['ChangeAmt'] = chg_amt_str
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
                cell.setdefault("last_vol_delta", 0)
                
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
                    active_grinders.append({
                        "Time": current_time_tw, "Code": sym, "Price": f"${p_num:.2f}",
                        "Streak": f"🔥無量緩推(連{cell['pos_vol_streak']}分)",
                        "ChangeAmt": chg_amt_str, "Change": change_str,
                        "GrindCount": cell["GrindCount"]
                    })
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
                        pb_low = cell["pullback_low"]
                        if p_num > pb_low * 1.01: 
                            sniper_triggered = True
                            sniper_label = "🎯精準回調"
                        is_pullback = False
                        surge_start_price = p_num
                        max_surge_vol = curr_vol_delta
                    else:
                        max_surge_vol = max(max_surge_vol, curr_vol_delta)
                    recent_high = p_num
                    
                    if is_hod_break:
                        if curr_vol_delta > max_surge_vol * 1.5 and max_surge_vol > 0:
                            sniper_triggered = True
                            sniper_label = "⚠️爆量(短線留意)"
                        elif curr_vol_delta > 0 and curr_vol_delta < 5000:
                            sniper_triggered = True
                            sniper_label = "⚠️虛漲(無量誘多)"
                            
                elif p_num < last_price:
                    swing_size = recent_high - surge_start_price
                    retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                    if retrace_ratio <= 0.50:
                        if not is_pullback:
                            is_pullback = True
                            cell["pullback_low"] = p_num
                        else:
                            cell["pullback_low"] = min(cell["pullback_low"], p_num)
                    else:
                        is_pullback = False 

                cell["recent_high"] = recent_high
                cell["surge_start_price"] = surge_start_price
                cell["is_pullback"] = is_pullback
                cell["max_surge_vol"] = max_surge_vol
                cell["sniper_triggered"] = sniper_triggered
                if sniper_triggered: cell["sniper_label"] = sniper_label
                
                streak_text = f"x{cell['streak']}"
                if is_hod_break: 
                    if sniper_triggered: streak_text = f"⭐破高+{cell['sniper_label']}"
                    else: streak_text = f"⭐破高{streak_text}"
                elif sniper_triggered: 
                    streak_text = f"{cell['sniper_label']}"

                has_catalyst = False
                for news in cell["NewsList"]:
                    for kw in CATALYST_KEYWORDS:
                        if kw in news.get("title", "").upper():
                            has_catalyst = True
                            cell["max_news_score"] += 10 
                            break
                
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
                    if not sniper_triggered: 
                        item["Streak"] = "⚡極速(9EMA)"
                    feed_surge.insert(0, item)

                if not cell["NewsList"]: 
                    tw_url = f"https://www.tradingview.com/chart/?symbol={sym}"
                    cell["NewsList"] = [{"id": "0", "title": "🗞️ 正在潛入微牛擷取即時新聞...", "score": 0, "link": tw_url, "time": "", "is_today": False}]
                    bg_task_pool.submit(fetch_webull_news_bg, sym, cell)
                    
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
            if "database is locked" not in str(e) and "NoneType" not in str(e):
                print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 引擎錯誤 (已防護): {e}")
            time.sleep(5)
