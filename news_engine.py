import requests, random, pytz
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
import config

def calculate_news_score(headline):
    headline_lower = headline.lower()
    score = 0
    gen_strong_bull = ['merger', 'acquisition', 'buyout', 'special dividend']
    gen_bull = ['earnings', 'guidance', 'upgrade', 'contract', 'partnership', 'agreement', 'raised', 'beat', 'profit', 'revenue', 'dividend', 'milestone', 'positive', 'share buyback', 'record']
    gen_bear = ['offering', 'pricing', 'lawsuit', 'investigation', 'delisting', 'downgrade', 'bankruptcy', 'chapter 11', 'missed', 'loss', 'warning', 'sec', 'subpoena', 'reverse split', 'default', 'shelf registration', 's-3', 'at-the-market', 'warrants']
    bio_strong_bull = ['fda approval', 'fda clearance', 'phase 3', 'breakthrough therapy', 'fast track', 'orphan drug', 'pivotal']
    bio_bull = ['fda', 'phase 1', 'phase 2', 'ind acceptance', 'clinical update', 'top-line', 'patent']
    bio_bear = ['clinical hold', 'fda hold', 'failed', 'missed primary endpoint', 'complete response letter', 'crl']
    tech_strong_bull = ['artificial intelligence', 'nvidia', 'openai', 'department of defense', 'prime vendor']
    tech_bull = ['cloud', 'cybersecurity', 'software as a service', 'saas', 'integration']
    tech_bear = ['data breach', 'cyberattack', 'hacked', 'banned']
    ev_strong_bull = ['battery breakthrough', 'department of energy', 'doe grant', 'gigafactory']
    ev_bull = ['solar', 'ev charger', 'clean energy', 'record delivery']
    ev_bear = ['recall', 'production halt', 'supply chain issue']
    crypto_strong_bull = ['bitcoin', 'spot etf']
    crypto_bull = ['ethereum', 'blockchain', 'web3', 'hash rate', 'mining']
    crypto_bear = ['crypto hack', 'unregistered securities']

    strong_bull = gen_strong_bull + bio_strong_bull + tech_strong_bull + ev_strong_bull + crypto_strong_bull
    bull = gen_bull + bio_bull + tech_bull + ev_bull + crypto_bull
    bear = gen_bear + bio_bear + tech_bear + ev_bear + crypto_bear
    
    for word in strong_bull:
        if word in headline_lower: score += 10
    for word in bull:
        if word in headline_lower: score += 5
    for word in bear:
        if word in headline_lower: score -= 10
    return score

def fetch_news_bg(ticker, cell):
    try:
        api_key = config.FINNHUB_API_KEY
        if not api_key or "請" in api_key:
            cell["NewsList"] = [{"id": "0", "title": "⚠️ 請在 api_key.txt 填寫金鑰", "score": 0, "link": "#", "time": ""}]
            cell["max_news_score"] = 0
            return

        tz_us = pytz.timezone('US/Eastern')
        now_us = datetime.now(tz_us)
        
        # ★ 修復點：嚴格鎖定「只抓當天（美東時間）」。如果今天是 3/14，就只顯示 3/14！
        today_str = now_us.strftime('%Y-%m-%d')
        
        # 將 from 和 to 都設定為 today_str
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={today_str}&to={today_str}&token={api_key}"
        r = requests.get(url, timeout=8)
        
        if r.status_code == 401:
            print(f"[{ticker}] ❌ 金鑰無效 (401)！")
            cell["NewsList"] = [{"id": "0", "title": "⚠️ 金鑰無效", "score": 0, "link": "#", "time": ""}]
            return
            
        if r.status_code == 429:
            cell["NewsList"] = [{"id": "0", "title": "⚠️ API 呼叫太快，請稍後再試", "score": 0, "link": "#", "time": ""}]
            return
            
        data = r.json()
        
        if not isinstance(data, list) or len(data) == 0:
            # 提示字眼改為「今日」
            cell["NewsList"] = [{"id": "0", "title": "今日無重大公關新聞", "score": 0, "link": "#", "time": ""}]
            cell["max_news_score"] = 0
            return

        news = []
        max_score = 0
        local_translator = GoogleTranslator(source='auto', target='zh-TW')
        
        for item in data[:4]: 
            headline_en = item.get('headline', '')
            if not headline_en: continue
            
            score = calculate_news_score(headline_en)
            if score > max_score: max_score = score
            elif score < 0 and max_score == 0: max_score = score 
            
            try: title_zh = local_translator.translate(headline_en)
            except: title_zh = headline_en
                
            news_time = datetime.fromtimestamp(item.get('datetime', 0) or 0, pytz.timezone('Asia/Taipei')).strftime('%m/%d %H:%M')
            news_id = str(item.get('id', random.randint(1000, 999999)))
            news.append({'id': news_id, 'title': title_zh, 'score': score, 'link': item.get('url', '#'), 'time': news_time})
        
        cell["NewsList"] = news
        cell["max_news_score"] = max_score
        
    except Exception as e:
        cell["NewsList"] = [{"id": "0", "title": "Finnhub 連線異常", "score": 0, "link": "#", "time": ""}]
        cell["max_news_score"] = 0
