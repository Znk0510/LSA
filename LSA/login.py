from flask import Flask, request, render_template_string
import os
import threading
import time
import subprocess
import psycopg2

app = Flask(__name__)

# --- 資料庫設定 (請修改為你的真實設定) ---
DB_CONFIG = {
    "dbname": "student_guard",
    "user": "lsa",      # 請修改
    "password": "lsapasswd", # 請修改
    "host": "127.0.0.1",
    "port": "5432"
}

# --- HTML 模板 (保持不變) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>NCNU Network Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; text-align: center; padding: 50px; }
        .btn { 
            background-color: #0088cc; color: white; padding: 15px 30px; 
            text-decoration: none; border-radius: 5px; font-size: 18px; display: inline-block;
        }
        .step { margin: 20px 0; color: #555; }
    </style>
</head>
<body>
    <h1>歡迎使用 NCNU 資管網路</h1>
    <div class="step">
        <p>您的 IP 位址是: <strong>{{ user_ip }}</strong></p>
        <p>請點擊下方按鈕進行 Telegram 驗證</p>
    </div>
    
    <a href="https://t.me/KDA_V2_bot?start={{ ip_param }}" target="_blank" class="btn">
        🔵 啟動 Telegram 驗證
    </a>
</body>
</html>
"""

# --- 背景任務：檢查並踢除離線使用者 ---
def monitor_offline_users():
    print("啟動背景監控執行緒...")
    while True:
        try:
            # 連線資料庫
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # === 修改重點 1: 修改查詢語句 ===
            # 目標: 找出 status='offline' 的學生，並從 connection_logs 撈出他們"最新"的 IP
            # 我們使用子查詢 (Subquery) 來找最後一筆連線紀錄 (ORDER BY id/timestamp DESC)
            query = """
                SELECT s.mac_address, 
                       (SELECT ip_address 
                        FROM connection_logs cl 
                        WHERE cl.mac_address = s.mac_address 
                        ORDER BY cl.timestamp DESC LIMIT 1) as latest_ip
                FROM students s
                WHERE s.status = 'offline'
            """
            cur.execute(query)
            rows = cur.fetchall()

            for row in rows:
                target_mac = row[0] # 第一個欄位是 MAC
                target_ip = row[1]  # 第二個欄位是查出來的 IP

                # === 修改重點 2: 檢查是否有找到 IP ===
                if target_ip:
                    print(f"[監控] 發現離線使用者 MAC: {target_mac}, 對應 IP: {target_ip}，執行踢除...")
                    
                    # 3. 執行 Shell Script (傳入 IP)
                    # 注意：這裡您的檔名寫 "LSA/login.sh"，但註解寫"踢除"，請確認是否應該是 logout.sh？
                    result = subprocess.run(
                        ["sudo", "./LSA/logout.sh", target_ip], 
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        print(f"[成功] IP: {target_ip} (MAC: {target_mac}) 已執行腳本。")

                        # 4. 更新資料庫狀態 (避免下次迴圈又抓到)
                        # 使用 MAC 來更新狀態
                        update_query = "UPDATE students SET status = 'log_out' WHERE mac_address = %s"
                        cur.execute(update_query, (target_mac,))
                        conn.commit()
                    else:
                        print(f"[失敗] Script 執行錯誤: {result.stderr}")
                else:
                    # 邊緣情況：學生在 students 表是 offline，但在 logs 裡找不到 IP (可能從未連線過)
                    print(f"[警告] 找不到 MAC {target_mac} 的 IP 紀錄，將狀態強制改為 log_out 以跳過。")
                    update_query = "UPDATE students SET status = 'log_out' WHERE mac_address = %s"
                    cur.execute(update_query, (target_mac,))
                    conn.commit()

            cur.close()
            conn.close()

        except Exception as e:
            print(f"[資料庫/系統錯誤] {e}")
        
        # 每 5 秒檢查一次
        time.sleep(5)

# --- Flask 路由 ---
@app.route("/", defaults={'path': ''})
@app.route("/<path:path>")
def login(path):
    user_ip = request.headers.get('X-Real-IP', request.remote_addr)
    ip_param = user_ip.replace('.', '_')
    return render_template_string(HTML_TEMPLATE, user_ip=user_ip, ip_param=ip_param)

if __name__ == "__main__":
    # 建立一個背景執行緒來跑監控程式
    monitor_thread = threading.Thread(target=monitor_offline_users)
    monitor_thread.daemon = True # 設定為守護執行緒 (主程式關閉時它也會關閉)
    monitor_thread.start()

    # 啟動 Flask
    app.run(host="127.0.0.1", port=5000) 