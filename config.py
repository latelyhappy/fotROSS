import os

# --- 讀取獨立的 API KEY 文字檔 ---
API_KEY_FILE = "api_key.txt"
FINNHUB_API_KEY = ""

if os.path.exists(API_KEY_FILE):
    with open(API_KEY_FILE, "r", encoding="utf-8") as f:
        FINNHUB_API_KEY = f.read().strip()
else:
    # 如果檔案不存在，自動建立一個空的並提示
    with open(API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write("")
    print(f"⚠️ 找不到 {API_KEY_FILE}，已為您自動建立。請填寫您的 API Key！")

# --- 全域數據中樞 ---
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
