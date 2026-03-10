import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_FILE = os.path.join(BASE_DIR, "api_key.txt")

FINNHUB_API_KEY = ""
if os.path.exists(API_KEY_FILE):
    # ★ 使用 utf-8-sig 強制消除 Windows 記事本產生的隱形 BOM 字元
    with open(API_KEY_FILE, "r", encoding="utf-8-sig") as f:
        FINNHUB_API_KEY = f.read().strip()
else:
    with open(API_KEY_FILE, "w", encoding="utf-8-sig") as f:
        f.write("")
    print(f"⚠️ 找不到 {API_KEY_FILE}，已自動建立。請填寫您的 API Key！")

# ★ 啟動時回報金鑰讀取狀態
if FINNHUB_API_KEY and "請" not in FINNHUB_API_KEY:
    print(f"🔑 API 金鑰已成功讀取: {FINNHUB_API_KEY[:4]}......{FINNHUB_API_KEY[-4:]}")
else:
    print(f"❌ 警告：API 金鑰尚未填寫或格式錯誤！")

MASTER_BRAIN = {
    "gappers": [], "high_vol": [], "net_vol_leaders": [],       
    "hod": [], "surge": [], "news_leaders": [], "grinders": [], 
    "details": {}, "last_update": "N/A", "scan_count": 0
}

stock_cache = {} 

STEALTH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
