import requests, random, pytz
from datetime import datetime
from deep_translator import GoogleTranslator
import config

def calculate_news_score(headline):
    headline_lower = headline.lower()
    score = 0
    strong_bull = ['fda', 'phase', 'approval', 'clearance', 'merger', 'acquisition', 'buyout', 'patent', 'breakthrough', 'fast track', 'orphan', 'pivotal']
    bull = ['earnings', 'guidance', 'upgrade', 'contract', 'partnership', 'agreement', 'raised', 'beat', 'profit', 'revenue', 'dividend', 'milestone', 'positive', 'department of defense', 'dod', 'award']
    bear = ['offering', 'pricing', 'lawsuit', 'investigation', 'delisting', 'downgrade', 'bankruptcy', 'missed', 'loss', 'warning', 'sec', 'subpoena', 'reverse split', 'default', 'shelf registration', 's-3', 'at-the-market', 'atm', 'warrants']
    
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
