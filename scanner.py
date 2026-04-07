def fetch_direct_news_bg(ticker, cell):
    try:
        tz_ny = pytz.timezone('America/New_York')
        now_ny = datetime.now(tz_ny)
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            articles = []
            for item in root.findall('./channel/item')[:5]:
                raw_t = item.find('title').text
                link = item.find('link').text
                pubDate = item.find('pubDate').text
                
                dt = parsedate_to_datetime(pubDate).astimezone(tz_ny)
                if (now_ny.date() - dt.date()).days > 4: continue
                is_today = (dt.date() == now_ny.date())
                
                # 🚨 明確標記：今日 或 月/日
                t_str = f"今日 {dt.strftime('%H:%M')}" if is_today else dt.strftime("%m/%d %H:%M")
                
                articles.append({
                    "id": str(random.randint(1,9999)), 
                    "title": translate_to_zh(raw_t), 
                    "link": link, "time": t_str, 
                    "is_today": is_today, "pub_ts": dt.timestamp(),
                    "raw_title": raw_t 
                })
            if articles: cell["NewsList"] = articles
    except: pass
