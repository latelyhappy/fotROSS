# 這是微軟官方提供的 Playwright 專用影像檔，內建了所有 Chrome 運行所需的 Linux 系統檔案！
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# 設定雲端主機的工作目錄
WORKDIR /app

# 把您的所有程式碼複製到雲端主機
COPY . /app

# 安裝 Python 必備套件
RUN pip install --no-cache-dir -r requirements.txt

# 開放戰情室網頁的 Port
EXPOSE 8080

# 啟動系統
CMD ["python", "main.py"]