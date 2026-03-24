import time, threading, requests, traceback, random, json
from datetime import datetime
import pytz
import yfinance as yf
from bs4 import BeautifulSoup

import config
from news_engine import fetch_news_bg

try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    print("🛡️ 已啟動 Cloudscraper 破甲模式！")
except ImportError:
    scraper = requests.Session()
    scraper.headers.update(config.STEALTH_HEADERS)

def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
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
        threading.Thread(target=fetch_static_bg, args=(ticker,), daemon=True).start()
        return (1000000, 500000, 1.0)

def format_vol_km(v_float):
    if v_float >= 1_000_000: return f"{v_float/1_000_000:.1f}M"
    elif v_float >= 1_000: return f"{v_float/1_000:.1f}K"
    else: return f"{int(v_float)}"

def parse_vol(v_str):
    if isinstance(v_str, (int, float)): return float(v_str)
    v_str = str(v_str).upper().replace(',', '').strip()
    try:
        if 'M' in v_str: return float(v_str.replace('M', '')) * 1e6
        if 'K' in v_str: return float(v_str.replace('K', '')) * 1e3
        return float(v_str)
    except: return 0.0

def scanner_engine():
    count = 0
    print("🔥 啟動七星陣列掃描引擎 (V215.8 終極微觀價量結構版)...")
    tz_tw = pytz.timezone('Asia/Taipei')
    tz_us = pytz.timezone('US/Eastern')
    
    while True:
        try:
            loop_start_time = time.time() 
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            now_us = datetime.now(tz_us)
            
            cache_str = f"?_t={int(time.time())}"
            
            if 4 <= now_us.hour < 9 or (now_us.hour == 9 and now_us.minute < 30): 
                url = f"https://stockanalysis.com/markets/premarket/gainers/{cache_str}"
            elif 9 <= now_us.hour < 16: 
                url = f"https://stockanalysis.com/markets/gainers/{cache_str}"
            else: 
                url = f"https://stockanalysis.com/markets/after-hours/{cache_str}"

            r = scraper.get(url, timeout=10)
            if r.status_code == 404: 
                url = f"https://stockanalysis.com/markets/premarket/gainers/{cache_str}"
                r = scraper.get(url, timeout=10)
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                title = soup.title.string.lower() if soup.title else ""
                
                if "just a moment" in title or "cloudflare" in title:
                    print(f"[{current_time_tw}] 🚨 遭到 Cloudflare 阻擋！正在迴避...")
                    time.sleep(10)
                    continue

                extracted_stocks = []

                next_data = soup.find("script", id="__NEXT_DATA__")
                if next_data:
                    try:
                        json_content = json.loads(next_data.string)
                        def extract_list(node):
                            if isinstance(node, list):
                                if len(node) > 10 and isinstance(node[0], dict) and ('s' in node[0] or 'symbol' in node[0]): return node
                                for item in node:
                                    res = extract_list(item)
                                    if res: return res
                            elif isinstance(node, dict):
                                for k, v in node.items():
                                    res = extract_list(v)
                                    if res: return res
                            return None
                        
                        raw_list = extract_list(json_content)
                        if raw_list:
                            for item in raw_list[:100]:
                                sym = item.get('s') or item.get('symbol')
                                price = item.get('price') or item.get('p')
                                change = item.get('change') or item.get('c')
                                vol = item.get('vol') or item.get('v') or item.get('volume')
                                if sym and price is not None:
                                    extracted_stocks.append({'sym': str(sym), 'price': float(price), 'change_str': f"{change}%" if change else "0%", 'vol_raw': parse_vol(vol) if vol else 0.0})
                    except: pass

                if not extracted_stocks:
                    tables = soup.find_all('table')
                    target_table = None
                    for t in tables:
                        if len(t.find_all('tr')) > 10:
                            target_table = t; break
                    
                    if target_table:
                        headers = [th.text.strip().lower() for th in target_table.find_all('th')]
                        sym_idx, price_idx, change_idx, vol_idx = 1, 4, 3, 5
                        for i, h in enumerate(headers):
                            if h == 'symbol': sym_idx = i
                            elif h == 'price': price_idx = i
                            elif '% change' in h or 'change' in h: change_idx = i
                            elif h == 'volume': vol_idx = i

                        rows = target_table.find_all('tr')
                        for tr in rows[1:100]: 
                            tds = tr.find_all('td')
                            if len(tds) <= max(sym_idx, price_idx, change_idx, vol_idx): continue
                            try:
                                sym = tds[sym_idx].text.strip()
                                p_num = float(tds[price_idx].text.strip().replace('$','').replace(',',''))
                                change_str = tds[change_idx].text.strip()
                                vol_raw = parse_vol(tds[vol_idx].text.strip())
                                extracted_stocks.append({'sym': sym, 'price': p_num, 'change_str': change_str, 'vol_raw': vol_raw})
                            except: continue

                t_all, c_hod, c_surge, c_grind = [], [], [], []
                current_t = time.time()
                
                for data in extracted_stocks:
                    sym = data['sym']
                    p_num = data['price']
                    change_str = data['change_str']
                    vol_raw = data['vol_raw']
                    
                    if 0.5 <= p_num <= 50.0:
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
                            # ★ V215.8 新增：微觀結構與極端拉伸變數
                            "surge_start_price": initial_hod, "max_surge_vol": 0, 
                            "pullback_start_time": 0, "pullback_min_vol": 9999999, "is_extended": False
                        })
                        
                        is_hod_break = False
                        if p_num > cell["HOD"]: cell["HOD"] = p_num; cell["streak"] += 1; is_hod_break = True
                        
                        gap_p = ((p_num - prev) / prev * 100) if prev > 0 else 0
                        rvol = vol_raw / a if a > 0 else 1.0
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

                        if cell["grind_1m_count"] >= 2: 
                            cell["is_grinder"] = True
                        elif cell["grind_1m_count"] == 0:
                            cell["is_grinder"] = False

                        # ==========================================
                        # ★ V215.8 核心：5大防護網與微觀結構辨識
                        # ==========================================
                        recent_high = cell.get("recent_high", initial_hod)
                        surge_start_price = cell.get("surge_start_price", initial_hod)
                        max_surge_vol = cell.get("max_surge_vol", 0)
                        pullback_start_time = cell.get("pullback_start_time", 0)
                        pullback_min_vol = cell.get("pullback_min_vol", 9999999)
                        
                        is_pullback = cell.get("is_pullback", False)
                        sniper_triggered = False
                        is_extended = False
                        
                        # 靈感五：極端乖離 (防追高)，瞬間噴漲 > 15% 未洗盤
                        if surge_start_price > 0 and (p_num - surge_start_price) / surge_start_price > 0.15:
                            is_extended = True
                            
                        if p_num > recent_high: # 價格創高或推升中
                            if is_pullback:
                                # 建議三：量能點火確認 (突破量必須明顯大於洗盤量)
                                if curr_vol_delta > pullback_min_vol * 1.2: 
                                    sniper_triggered = True
                                is_pullback = False
                                surge_start_price = p_num 
                                max_surge_vol = curr_vol_delta 
                            else:
                                max_surge_vol = max(max_surge_vol, curr_vol_delta)
                            recent_high = p_num
                            
                        elif p_num < last_price: # 價格回落洗盤中
                            swing_size = recent_high - surge_start_price
                            retrace_ratio = (recent_high - p_num) / swing_size if swing_size > 0 else 0
                            
                            # 建議一：1/3 量縮防護 (寬容度設為 40% 以適應 API 頻率)
                            is_vol_contracted = (curr_vol_delta <= max_surge_vol * 0.4) if max_surge_vol > 0 else True
                            
                            # 建議二：50% 黃金分割防守
                            if retrace_ratio <= 0.50 and net_vol > 0 and is_vol_contracted:
                                if not is_pullback:
                                    is_pullback = True
                                    pullback_start_time = current_t
                                    pullback_min_vol = curr_vol_delta
                                else:
                                    pullback_min_vol = min(pullback_min_vol, curr_vol_delta)
                            else:
                                # 若跌破 50% 或是下跌爆量，立刻取消盯盤 (防 A 轉)
                                if retrace_ratio > 0.50 or curr_vol_delta > max_surge_vol * 0.6:
                                    is_pullback = False 

                        # 靈感四：時間衰減 (洗盤超過 15 分鐘 = 動能失效)
                        if is_pullback and (current_t - pullback_start_time > 900):
                            is_pullback = False

                        bull_trap = False
                        if is_hod_break and net_vol < 0: 
                            bull_trap = True

                        cell["recent_high"] = recent_high
                        cell["surge_start_price"] = surge_start_price
                        cell["max_surge_vol"] = max_surge_vol
                        cell["pullback_start_time"] = pullback_start_time
                        cell["pullback_min_vol"] = pullback_min_vol
                        cell["is_pullback"] = is_pullback
                        cell["sniper_triggered"] = sniper_triggered
                        cell["bull_trap"] = bull_trap
                        cell["is_extended"] = is_extended
                        
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
                            
                        # 寫入破高區塊
                        if is_hod_break and (rvol > 0.2 or vol_raw > 50000): 
                            item_hod = item.copy()
                            if bull_trap: item_hod["Streak"] = "⚠️虛漲倒貨"
                            else: item_hod["Streak"] = f"⭐破高x{cell['streak']}"
                            c_hod.append(item_hod)
                            cell["last_act"] = "hod"

                        # 寫入動能區塊 (整合全新拉伸與狙擊訊號)
                        is_vol_spike = (curr_vol_delta > last_vol_delta * 3) and (curr_vol_delta > 20000) and (p_num >= last_price)
                        
                        if sniper_triggered or (cell["streak"] >= 2 and is_hod_break) or is_vol_spike or is_extended:
                            item_surge = item.copy()
                            if sniper_triggered: item_surge["Streak"] = "🎯精準狙擊"
                            elif bull_trap and is_hod_break: item_surge["Streak"] = "⚠️虛漲倒貨"
                            elif is_extended: item_surge["Streak"] = "🔥極度拉伸"
                            elif is_vol_spike: item_surge["Streak"] = f"💥爆量+{format_vol_km(curr_vol_delta)}"
                            else: item_surge["Streak"] = f"⭐破高x{cell['streak']}"
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
                            
                            if sniped: item_grind["Streak"] = "🎯精準狙擊"
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
                    "hod": (c_hod + config.MASTER_BRAIN["hod"])[:1000],
                    "surge": (c_surge + config.MASTER_BRAIN["surge"])[:1000],
                    "news_leaders": news_leaders, 
                    "net_vol_leaders": net_vol_leaders, 
                    "grinders": active_grinders, 
                    "last_update": current_time_tw, "scan_count": count
                })
                
                cost_time = time.time() - loop_start_time
                if len(t_all) == 0:
                    print(f"[{current_time_tw}] ❌ 解析失敗：找不到符合條件的股票！")
                else:
                    print(f"[{current_time_tw}] ⏱️ 掃描完成: 找到 {len(t_all)} 檔目標，本輪耗時 {cost_time:.2f} 秒")

            time.sleep(random.uniform(3.0, 5.0)) 
        except Exception as e:
            print(f"[{datetime.now(tz_tw).strftime('%H:%M:%S')}] 🚨 發生例外錯誤，重啟迴圈：")
            traceback.print_exc()
            time.sleep(3)
