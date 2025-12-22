import sqlite3
import time
import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc

# 1. 取得目前檔案的絕對路徑
current_file_path = os.path.abspath(__file__)
current_dir_path = os.path.dirname(current_file_path)
parent_dir_path = os.path.dirname(current_dir_path)
sys.path.append(parent_dir_path)

from src.db.database import SessionLocal
from src.db.models import StudentRecord, ConnectionLog

# --- 設定區 ---
DECAY_AMOUNT = 1         # 每次迴圈沒偵測到時，扣多少分
SCORE_INCREMENT_VIDEO = 21 # 偵測到影片關鍵字，加多少分
SCORE_INCREMENT_GAME = 0  # 偵測到遊戲關鍵字，加多少分
PUNISH_THRESHOLD = 20     # 積分超過多少才處罰 (累積制)
MAX_SCORE = 50           # 積分上限 (避免無限疊加)
PIHOLE_DB_PATH = "/etc/pihole/pihole-FTL.db"
CHECK_INTERVAL = 10
INTERFACE = "eno1" 

# 定義黑名單關鍵字
BLACKLIST_VIDEO = ["googlevideo.com", "nflxvideo.net", "netflix.com", "youtube.com", "tiktok.com"]
BLACKLIST_GAME = ["steamcommunity.com", "steampowered.com", "riotgames.com", "epicgames.com", "roblox.com"]

# --- 分開設定閥值 ---
# 影片的請求通常較多 (載入縮圖、廣告、影片分段)，建議閥值稍高
THRESHOLD_VIDEO = 5 
# 遊戲連線通常較為固定，閥值可視情況調整
THRESHOLD_GAME = 3   

def get_db():
    return SessionLocal()

def mark_punished(db, mac_address, violation_type):
    student = db.query(StudentRecord).filter(StudentRecord.mac_address == mac_address).first()
    if student:
        student.p_status = 'PUNISHED'
        student.violation_count += 1
        # 可以選擇將違規原因寫入 log 或備註欄位 (若有的話)
        print(f"[DB] 學生 {student.name} ({student.student_id}) 因 {violation_type} 已被標記為 PUNISHED")
        db.commit()

def get_punished_macs(db):
    students = db.query(StudentRecord).filter(StudentRecord.p_status == 'PUNISHED').all()
    return [s.mac_address for s in students]

def get_mac_from_ip(db, ip):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    log = db.query(ConnectionLog)\
        .filter(ConnectionLog.ip_address == ip)\
        .filter(ConnectionLog.timestamp > cutoff)\
        .order_by(desc(ConnectionLog.timestamp))\
        .first()
    return log.mac_address if log else None

def get_recent_queries():
    try:
        # 使用唯讀模式開啟資料庫，避免鎖定
        conn = sqlite3.connect(f"file:{PIHOLE_DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()
        # 檢查過去 60 秒內的紀錄
        ts = int(time.time()) - 60
        cursor.execute(f"SELECT client, domain FROM queries WHERE timestamp > {ts}")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[Pi-hole Error] {e}")
        return []

def punish_user(db, ip, mac, violation_type):
    print(f"🚨 違規偵測確認！IP: {ip} / MAC: {mac} / 類型: {violation_type}")
    
    if violation_type == "GAME":
        # 執行封鎖遊戲腳本 (只傳 IP)
        cmd = f"sudo ./LSA/block_game.sh {ip}"
        print(f"執行: {cmd}")
        os.system(cmd)
        
    elif violation_type == "VIDEO":
        # 執行限速腳本 (傳 IP 和 介面)
        cmd = f"sudo ./LSA/slow_down.sh {ip} {INTERFACE}"
        print(f"執行: {cmd}")
        os.system(cmd)
    
    # 更新資料庫狀態
    mark_punished(db, mac, violation_type)

def main():
    print("👀 違規偵測啟動中...")
    
    # 這是用來記憶每個 IP 的積分，格式: { '192.168.1.10': {'video_score': 0, 'game_score': 0} }
    # 放在 while 迴圈外面，這樣資料才不會被清空
    ip_scores = {} 

    while True:
        db = get_db()
        try:
            logs = get_recent_queries() # 抓取過去 60 秒的紀錄
            
            # 1. 先建立當次迴圈的「臨時」計數
            current_hits = {} 

            for client_ip, domain in logs:
                if client_ip not in current_hits:
                    current_hits[client_ip] = {'video': False, 'game': False}
                
                for kw in BLACKLIST_VIDEO:
                    if kw in domain:
                        current_hits[client_ip]['video'] = True
                        break
                
                for kw in BLACKLIST_GAME:
                    if kw in domain:
                        current_hits[client_ip]['game'] = True
                        break

            # 2. 更新長期的積分 (ip_scores)
            # 先把所有已知的 IP 拿出來跑一遍
            # 注意：這裡要包含 ip_scores 裡原本有的 IP (正在冷卻中) 和 current_hits 新出現的 IP
            all_ips = set(ip_scores.keys()) | set(current_hits.keys())

            for ip in all_ips:
                if ip not in ip_scores:
                    ip_scores[ip] = {'video_score': 0, 'game_score': 0}
                
                # 取得該 IP 這一輪有沒有命中
                hit_video = current_hits.get(ip, {}).get('video', False)
                hit_game = current_hits.get(ip, {}).get('game', False)

                # --- 影片積分計算 ---
                if hit_video:
                    ip_scores[ip]['video_score'] += SCORE_INCREMENT_VIDEO
                else:
                    ip_scores[ip]['video_score'] -= DECAY_AMOUNT
                
                # 限制範圍 (0 ~ MAX_SCORE)
                ip_scores[ip]['video_score'] = max(0, min(ip_scores[ip]['video_score'], MAX_SCORE))

                # --- 遊戲積分計算 ---
                if hit_game:
                    ip_scores[ip]['game_score'] += SCORE_INCREMENT_GAME
                else:
                    ip_scores[ip]['game_score'] -= DECAY_AMOUNT
                
                # 限制範圍 (0 ~ MAX_SCORE)
                ip_scores[ip]['game_score'] = max(0, min(ip_scores[ip]['game_score'], MAX_SCORE))

                # 顯示目前的監控狀態 (Debug用，太吵可以註解掉)
                if ip_scores[ip]['video_score'] > 0 or ip_scores[ip]['game_score'] > 0:
                    print(f"IP: {ip} | 影片積分: {ip_scores[ip]['video_score']} | 遊戲積分: {ip_scores[ip]['game_score']}")
                    # print(f"IP: {ip} | VIDEO_SCORE{ip_scores[ip]['video_score']}")
            # 3. 檢查是否超過閥值並處罰
            punished_macs = get_punished_macs(db)

            for ip, scores in ip_scores.items():
                violation_type = None
                
                if scores['game_score'] >= PUNISH_THRESHOLD:
                    violation_type = "GAME"
                elif scores['video_score'] >= PUNISH_THRESHOLD:
                    violation_type = "VIDEO"
                
                if violation_type:
                    target_mac = get_mac_from_ip(db, ip)
                    if target_mac:
                        if target_mac not in punished_macs:
                            punish_user(db, ip, target_mac, violation_type)
                            # 處罰後可以選擇將分數歸零，或保持高分持續壓制
                            # 這裡選擇歸零，避免腳本重複呼叫
                            ip_scores[ip]['game_score'] = 0
                            ip_scores[ip]['video_score'] = 0
        
        except Exception as e:
            print(f"[Error] {e}")
        finally:
            db.close()
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ 請使用 sudo 執行此程式，以確保有權限呼叫 shell scripts！")
        exit(1)
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 程式已手動停止")
