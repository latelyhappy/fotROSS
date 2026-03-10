import threading, warnings
from flask import Flask, jsonify, render_template
from flask_cors import CORS
import config
from scanner import scanner_engine

warnings.filterwarnings('ignore')
app = Flask(__name__)
CORS(app)

@app.route('/data')
def get_data(): return jsonify(config.MASTER_BRAIN)

@app.route('/')
def index(): return render_template('index.html')

if __name__ == '__main__':
    threading.Thread(target=scanner_engine, daemon=True).start()
    print("🌐 網頁伺服器啟動！請在瀏覽器輸入: http://127.0.0.1:8080")
    app.run(host='0.0.0.0', port=8080)
