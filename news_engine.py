# news_engine.py
import requests, random, pytz
from datetime import datetime
from deep_translator import GoogleTranslator
import config

def calculate_news_score(headline):
    headline_lower = headline.lower()
    score = 0
    
    # ==========================================
    # 🎯 產業別 NLP 催化劑量化字典 (Catalyst Lexicon)
    # ==========================================

    # 📁 1. 通用財務與公司事件 (General Financial)
    gen_strong_bull = ['merger', 'acquisition', 'buyout', 'special dividend']
    gen_bull = ['earnings', 'guidance', 'upgrade', 'contract', 'partnership', 'agreement', 'raised', 'beat', 'profit', 'revenue', 'dividend', 'milestone', 'positive', 'share buyback', 'record']
    gen_bear = ['offering', 'pricing', 'lawsuit', 'investigation', 'delisting', 'downgrade', 'bankruptcy', 'chapter 11', 'missed', 'loss', 'warning', 'sec', 'subpoena', 'reverse split', 'default', 'shelf registration', 's-3', 'at-the-market', 'warrants']

    # 📁 2. 生技與製藥產業 (Biotech & Pharma) - 爆發力最強
    bio_strong_bull = ['fda approval', 'fda clearance', 'phase 3', 'breakthrough therapy', 'fast track', 'orphan drug', 'pivotal']
    bio_bull = ['fda', 'phase 1', 'phase 2', 'ind acceptance', 'clinical update', 'top-line', 'patent']
    bio_bear = ['clinical hold', 'fda hold', 'failed', 'missed primary endpoint', 'complete response letter', 'crl']

    # 📁 3. 科技與人工智慧 (Tech & AI)
    tech_strong_bull = ['artificial intelligence', 'nvidia', 'openai', 'department of defense', 'prime vendor']
    tech_bull = ['cloud', 'cybersecurity', 'software as a service', 'saas', 'integration']
    tech_bear = ['data breach', 'cyberattack', 'hacked', 'banned']

    # 📁 4. 電動車與清潔能源 (EV & Clean Energy)
    ev_strong_bull = ['battery breakthrough', 'department of energy', 'doe grant', 'gigafactory']
    ev_bull = ['solar', 'ev charger', 'clean energy', 'record delivery']
    ev_bear = ['recall', 'production halt', 'supply chain issue']

    # 📁 5. 加密貨幣與區塊鏈 (Crypto & Blockchain)
    crypto_strong_bull = ['bitcoin', 'spot etf']
    crypto_bull = ['ethereum', 'blockchain', 'web3', 'hash rate', 'mining']
    crypto_bear = ['crypto hack', 'unregistered securities']

    # --- 彙整所有陣列進行打分 ---
    strong_bull = gen_strong_bull + bio_strong_bull + tech_strong_bull + ev_strong_bull + crypto_strong_bull
    bull = gen_bull + bio_bull + tech_bull + ev_bull + crypto_bull
    bear = gen_bear + bio_bear + tech_bear + ev_bear + crypto_bear
    
    # 執行加扣分邏輯
    for word in strong_bull:
        if word in headline_lower: score += 10
    for word in bull:
        if word in headline_lower: score += 5
    for word in bear:
        if word in headline_lower: score -= 10
        
    return score

def fetch_news_bg(ticker, cell):
    try:
        if not config.FINNHUB_API_KEY or "請" in config.FINNHUB_API_KEY:
            cell["NewsList"] = [{"id": "0", "title": "⚠️ 請在 api_key.txt 填寫 Finnhub API Key", "score": 0, "link": "#", "time": ""}]
            cell["max_news_score"] = 0
            return

        tz_us = pytz.timezone('US/Eastern')
        now_us = datetime.now(tz_us)
        target_date = now_us.strftime('%Y-%m-%d')
        
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={target_date}&to={target_date}&token={config.FINNHUB_API_KEY}"
        r = requests.get(url, timeout=5)
        
        if r.status_code == 429:
            cell["NewsList"] = [{"id": "0", "title": "⚠️ API 呼叫太快，請稍後再試", "score": 0, "link": "#", "time": ""}]
            return
            
        data = r.json()
        news = []
        max_score = 0
        if data and isinstance(data, list):
            local_translator = GoogleTranslator(source='auto', target='zh-TW')
            for item in data[:4]: 
                headline_en = item.get('headline', '')
                if not headline_en: continue
                
                # 呼叫剛才升級的產業別評分系統
                score = calculate_news_score(headline_en)
                
                if score > max_score: max_score = score
                elif score < 0 and max_score == 0: max_score = score 
                
                try: title_zh = local_translator.translate(headline_en)
                except: title_zh = headline_en
                    
                news_time = datetime.fromtimestamp(item.get('datetime', 0) or 0, pytz.timezone('Asia/Taipei')).strftime('%m/%d %H:%M')
                news_id = str(item.get('id', random.randint(1000, 999999)))
                news.append({'id': news_id, 'title': title_zh, 'score': score, 'link': item.get('url', '#'), 'time': news_time})
        
        if not news: news = [{"id": "0", "title": "今日無重大公關新聞", "score": 0, "link": "#", "time": ""}]
        cell["NewsList"] = news
        cell["max_news_score"] = max_score
        
    except Exception as e:
        cell["NewsList"] = [{"id": "0", "title": "Finnhub 連線異常", "score": 0, "link": "#", "time": ""}]
        cell["max_news_score"] = 0
