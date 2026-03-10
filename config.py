import os

# ★ 強制使用絕對路徑，確保系統絕對能找到您的 API KEY
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_FILE = os.path.join(BASE_DIR, "api_key.txt")

FINNHUB_API_KEY = ""
if os.path.exists(API_KEY_FILE):
    with open(API_KEY_FILE, "r", encoding="utf-8") as f:
        FINNHUB_API_KEY = f.read().strip()
else:
    with open(API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write("")
    print(f"⚠️ 找不到 {API_KEY_FILE}，已自動建立。請填寫您的 API Key！")

MASTER_BRAIN = {
    "gappers": [], "high_vol": [], "net_vol_leaders": [],       
    "hod": [], "surge": [], "news_leaders": [], "grinders": [], 
    "details": {}, "last_update": "N/A", "scan_count": 0
}

stock_cache = {} 

STEALTH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
