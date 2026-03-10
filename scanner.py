# scanner.py
import time, threading, requests, traceback, random
from datetime import datetime
import pytz
import yfinance as yf
from bs4 import BeautifulSoup

import config
from news_engine import fetch_news_bg

def fetch_static_bg(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        f = i.get('floatShares', 0) or i.get('sharesOutstanding', 1000000)
        a = i.get('averageVolume', 500000)
        p = i.get('previousClose', 1.0)
        config.stock_cache[ticker] = (f, a, p)
    except Exception as e:
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
    v_str = v_str.upper().replace(',', '').strip()
    try:
        if 'M' in v_str: return float(v_str.replace('M', '')) * 1e6
        if 'K' in v_str: return float(v_str.replace('K', '')) * 1e3
        return float(v_str)
    except: return 0.0

def scanner_engine():
    count = 0
    print("🔥 啟動七星陣列掃描引擎 (V215.5 智慧抓表防改版)...")
    
    tz_tw = pytz.timezone('Asia/Taipei')
    tz_us = pytz.timezone('US/Eastern')
    
    while True:
        try:
            loop_start_time = time.time() 
            
            current_time_tw = datetime.now(tz_tw).strftime('%H:%M:%S')
            now_us = datetime.now(tz_us)
            
            if 4 <= now_us.hour < 9 or (now_us.hour == 9 and now_us.minute < 30): 
                url = "https://stockanalysis.com/markets/premarket/gainers/"
            elif 9 <= now_us.hour < 16: 
                url = "https://stockanalysis.com/markets/gainers/"
            else: 
                url = "https://stockanalysis.com/markets/after-hours/"

            r = requests.get(url, headers=config.STEALTH_HEADERS, timeout=8)
            if r.status_code == 404: 
                url = "https://stockanalysis.com/markets/premarket/gainers/"
                r = requests.get(url, headers=config.STEALTH_HEADERS, timeout=8)
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                
                # ★ 智慧表格追蹤技術：找出網頁中所有的表格，過濾掉假表格
                tables = soup.find_all('table')
                target_table = None
                for t in tables:
                    if len(t.find_all('tr')) > 10: # 真正的股票表格，列數絕對大於 10
                        target_table = t
                        break
                
                if not target_table:
                    print(f"[{current_time_tw}] ❌ 警告：連線成功，但沒找到股票主表格！(網頁上共 {len(tables)} 個微型假表格)")
                else:
                    # 動態尋找欄位，避免網站更換左右順序
                    headers = [th.text.strip().lower() for th in target_table.find_all('th')]
                    sym_idx, price_idx, change_idx, vol_idx = 1, 4, 3, 5 # 預設值
                    
                    for i, h in enumerate(headers):
                        if h == 'symbol': sym_idx = i
                        elif h == 'price': price_idx = i
                        elif '% change' in h or 'change' in h: change_idx = i
                        elif h == 'volume': vol_idx = i

                    rows = target_table.find_all('tr')
                    t_all, c_hod, c_surge, c_grind = [], [], [], []
                    
                    for tr in rows[1:100]: 
                        tds = tr.find_all('td')
                        if len(tds) <= max(sym_idx, price_idx, change_idx, vol_idx): continue
                        
                        sym = tds[sym_idx].text.strip()
                        raw_price = tds[price_idx].text.strip() 
                        change_str = tds[change_idx].text.strip()
                        raw_vol_str = tds[vol_idx].text.strip()
                        
                        try: p_num = float(raw_price.replace('$','').replace(',',''))
                        except Exception as e: continue
                        
                        if 0.5 <= p_num <= 50.0:
                            f, a, prev = get_static(sym)
                            vol_raw = parse_vol(raw_vol_str)
                            formatted_volume = format_vol_km(vol_raw)
                            
                            is_new_stock = sym not in config.MASTER_BRAIN["details"]
                            initial_hod = (p_num * 0.98) if is_new_stock else p_num
                            
                            cell = config.MASTER_BRAIN["details"].get(sym, {
                                "HOD": initial_hod, "NewsList": [], "max_news_score": 0, "streak": 0, "last_act": "",
                                "last_price": p_num, "last_vol": vol_raw, "last_vol_delta": 0,
                                "up_ticks": 0, "last_grind_tick": 0, "last_long_grind_tick": 0,
                                "cum_buy_vol": 0, "cum_sell_vol": 0
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
                                if p_num > last_price: cell["cum_buy_vol"] += curr_vol_delta
                                elif p_num < last_price: cell["cum_sell_vol"] += curr_vol_delta

                            net_vol = cell["cum_buy_vol"] - cell["cum_sell_vol"]
                            
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
                            
                            if p_num > last_price:
                                up_ticks += 1
                                tick_jump_pct = ((p_num - last_price) / last_price) * 100
                            elif p_num < last_price:
                                up_ticks = 0; tick_jump_pct = 0; cell["last_grind_tick"] = 0; cell["last_long_grind_tick"] = 0 
                            else: tick_jump_pct = 0

                            if is_hod_break and (rvol > 0.2 or vol_raw > 50000): c_hod.append(item); cell["last_act"] = "hod"

                            is_velocity_spike = tick_jump_pct >= 2.0
                            is_steady_grind = (up_ticks >= 3 and up_ticks % 3 == 0 and cell.get("last_grind_tick") != up_ticks)
                            is_vol_spike = (curr_vol_delta > last_vol_delta * 3) and (curr_vol_delta > 20000) and (p_num >= last_price)
                            is_long_grinder = (up_ticks >= 6 and tick_jump_pct < 3.0 and drop_p > -5.0 and p_num >= 1.0)
                            
                            if (cell["streak"] >= 2 and is_hod_break) or is_velocity_spike or is_steady_grind or is_vol_spike:
                                item_surge = item.copy()
                                if is_velocity_spike: item_surge["Streak"] = f"🚀急噴+{tick_jump_pct:.1f}%"
                                elif is_vol_spike: item_surge["Streak"] = f"💥爆量+{format_vol_km(curr_vol_delta)}"
                                elif is_steady_grind: item_surge["Streak"] = f"🔥連漲x{up_ticks}"; cell["last_grind_tick"] = up_ticks 
                                else: item_surge["Streak"] = f"⭐破高x{cell['streak']}"
                                c_surge.append(item_surge); cell["last_act"] = "surge"
                                
                            if is_long_grinder and cell.get("last_long_grind_tick") != up_ticks:
                                item_grind = item.copy()
                                item_grind["Streak"] = f"🐢緩漲x{up_ticks}"
                                c_grind.append(item_grind); cell["last_long_grind_tick"] = up_ticks

                            if not cell["NewsList"]: 
                                cell["NewsList"] = [{"id": "0", "title": "檢索中...", "score": 0, "link": "#", "time": ""}]
                                threading.Thread(target=fetch_news_bg, args=(sym, cell), daemon=True).start()
                                
                            cell["HOD_str"] = f"${cell['HOD']:.2f}"; cell["last_price"] = p_num
                            cell["last_vol"] = vol_raw; cell["last_vol_delta"] = curr_vol_delta
                            cell["up_ticks"] = up_ticks 
                            config.MASTER_BRAIN["details"][sym] = cell

                    count += 1
                    news_list_temp, net_vol_temp = [], []
                    
                    for k_sym, k_cell in config.MASTER_BRAIN["details"].items():
                        if "latest_item" in k_cell and k_cell.get("last_seen") == current_time_tw:
                            score = k_cell.get("max_news_score", 0)
                            if score != 0:
                                i_copy = k_cell["latest_item"].copy()
                                i_copy["NewsScore"] = score
                                news_list_temp.append(i_copy)
                            
                            if k_cell["cum_buy_vol"] > 0 or k_cell["cum_sell_vol"] > 0:
                                net_vol_temp.append(k_cell["latest_item"].copy())
                            
                    news_leaders = sorted(news_list_temp, key=lambda x: x["NewsScore"], reverse=True)[:20]
                    net_vol_leaders = sorted(net_vol_temp, key=lambda x: abs(x.get("NetVolNum", 0)), reverse=True)[:20]

                    gappers = sorted(t_all, key=lambda x: x["gap_num"], reverse=True)[:20]
                    high_vol = sorted(t_all, key=lambda x: x["rvol_num"], reverse=True)[:20]
                    
                    config.MASTER_BRAIN.update({
                        "gappers": gappers, "high_vol": high_vol,
                        "hod": (c_hod + config.MASTER_BRAIN["hod"])[:1000],
                        "surge": (c_surge + config.MASTER_BRAIN["surge"])[:1000],
                        "news_leaders": news_leaders, 
                        "net_vol_leaders": net_vol_leaders, 
                        "grinders": (c_grind + config.MASTER_BRAIN.get("grinders", []))[:1000],
                        "last_update": current_time_tw, "scan_count": count
                    })
                    
                    cost_time = time.time() - loop_start_time
                    
                    # ★ 終極防呆檢測：如果找到表格但還是 0 檔，印出第一筆資料查水表！
                    if len(t_all) == 0:
                        print(f"[{current_time_tw}] ⚠️ 抓到了主表格，但是過濾後符合「$0.5 ~ $50」條件的股票為 0 檔！")
                        if len(rows) > 1:
                            print(f"-> 抓取樣本測試: {rows[1].text.strip().replace(chr(10), ' ')}")
                    else:
                        print(f"[{current_time_tw}] ⏱️ 掃描完成: 找到 {len(t_all)} 檔目標，本輪耗時 {cost_time:.2f} 秒")

            time.sleep(random.uniform(3.0, 5.0)) 
        except Exception as e:
            traceback.print_exc()
            time.sleep(5)
