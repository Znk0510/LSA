import asyncio, uvicorn, random, os, uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Request, Depends, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

# AI 模組
from src.ai.pdf_loader import pdf_loader
from src.ai.service import AIQuizService

# 資料庫相關
from src.db.database import get_db, init_db, SessionLocal
from src.db.models import StudentRecord, ConnectionLog, QuizAttempt, LoginRequest, RegisterRequest, User
from src.db.repositories import AuthorizationLogRepository, StudentRepository, ConnectionLogRepository, UserRepository

# 核心服務與網路元件
# 測試用 Mock，實際換成 ShellScriptFirewallController
from src.network.firewall import MockFirewallController
from src.network.scanner import ARPScanner
from src.network.registry import StudentRegistryService
from src.core.auth_service import AuthorizationService
from src.gateway.service import CaptivePortalService

# === 設定區 ===
# 請使用 ip addr 確認無線網卡名稱 (例如 wlan0, wlp2s0)
WIFI_INTERFACE = "eno1"  
# 設定熱點網段 (例如 192.168.10.0/24)
TARGET_NETWORK = "192.168.10.0/24"

# 初始化 AI (Mistral 跑不動)
ai_service = AIQuizService(model="gemma2:2b")

# 初始化 FastAPI
app = FastAPI(
    title="Smart Classroom System",
    description="Backend API for Captive Portal and AI Quiz",
    version="1.0.0"
)

# CORS 設定
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://192.168.10.1",      # 你的伺服器 IP (前端網址)
    "http://192.168.10.1:8000", # 有時候瀏覽器會帶 Port
    "*"                          # 開發測試時，可以直接用 "*" 允許所有來源
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency: 資料庫 Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Dependency Injection：系統元件初始化
auth_repo = AuthorizationLogRepository()
scanner = ARPScanner(interface=WIFI_INTERFACE)
# 測試用 Mock，實際換成 ShellScriptFirewallController() 
firewall_controller = MockFirewallController()
auth_service = AuthorizationService(auth_repo, firewall_controller)
portal_service = CaptivePortalService(auth_service)
student_repo = StudentRepository() 
user_repo = UserRepository()

# --- 題目答案暫存區 ---
# 結構: { "question_uuid": "A" }
ACTIVE_QUIZZES = {}

# --- 學生測驗狀態暫存區 ---
# 格式: { "MAC_ADDRESS": { "penalty": 0, "wrong_count": 0 } }
student_quiz_state = {}

# === Helper: 取得 MAC ===
async def get_current_mac(
    request: Request,
    x_mac_address: Optional[str] = Header(None, alias="X-Mac-Address"),
    db: Session = Depends(get_db) # ### 新增：注入資料庫連線
) -> str:
    # 優先順序 1：HTTP Header (通常由 Gateway 轉發時帶入)
    if x_mac_address:
        return x_mac_address

    # 優先順序 2：網址參數 (例如 ?mac=aa:bb:cc...)
    mac_param = request.query_params.get("mac")
    if mac_param:
        return mac_param

    # 優先順序 3：透過來源 IP 去資料庫反查 MAC
    client_ip = request.client.host
    
    # 排除 localhost (開發測試時可能是 127.0.0.1)
    if client_ip in ["127.0.0.1", "localhost"]:
        # 開發環境下，隨便回傳一個假的或寫死的，方便測試
        return "00:00:00:00:00:00"

    print(f"[MAC Lookup] 嘗試透過 IP 反查: {client_ip}")

    # 查詢 ConnectionLog 表
    # 邏輯：找這個 IP 最近的一筆連線紀錄
    last_log = db.query(ConnectionLog)\
    .filter(ConnectionLog.ip_address == client_ip)\
    .order_by(ConnectionLog.timestamp.desc())\
    .first()

    if last_log:
        print(f"[MAC Lookup] 找到對應 MAC: {last_log.mac_address}")
        return last_log.mac_address

    # 優先順序 4 (保底)：如果資料庫也沒有，嘗試讀取系統 ARP 表 (更即時)
    # 有時候資料庫還沒寫入，但系統底層已經有 ARP 了
    try:
        with open('/proc/net/arp', 'r') as f:
            lines = f.readlines()[1:] # 跳過標題
            for line in lines:
                parts = line.split()
                # parts[0] 是 IP, parts[3] 是 MAC
                if len(parts) >= 4 and parts[0] == client_ip:
                    print(f"[MAC Lookup] ARP 表命中: {parts[3]}")
                    return parts[3]
    except Exception as e:
        print(f"[MAC Lookup] ARP 讀取失敗: {e}")

    print(f"[MAC Lookup] 無法識別 MAC，IP: {client_ip}")
    return "00:00:00:00:00:00"

def get_ip_by_mac(target_mac: str) -> Optional[str]:
    """
    簡單讀取 /proc/net/arp 來尋找對應 MAC 的 IP
    注意：這需要該設備近期有發送過封包，ARP 表才會有紀錄
    """
    try:
        with open('/proc/net/arp', 'r') as f:
            lines = f.readlines()[1:] # 跳過標題
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[0]
                    mac = parts[3]
                    if mac.lower() == target_mac.lower():
                        return ip
    except Exception as e:
        print(f"[ARP Lookup Error] {e}")
    return None

# === ### 新增: 執行解鎖 Script 的 Helper ===
def execute_restore_script(ip: str, interface: str):
    """
    執行 sudo ./restore.sh <IP> <介面>
    注意：執行此程式的使用者需要有 sudo 權限且設定 NOPASSWD，否則會卡在輸入密碼。
    """
    try:
        print(f"[System] 執行解鎖腳本: sudo ./restore.sh {ip} {interface}")
        # 確保 restore.sh 有執行權限 (chmod +x restore.sh)
        result = subprocess.run(
            ["sudo", "./restore.sh", ip, interface],
            capture_output=True,
            text=True,
            check=False # 不拋出異常，手動檢查 returncode
        )
        
        if result.returncode == 0:
            print(f"[System] 解鎖成功: {result.stdout}")
            return True
        else:
            print(f"[System] 解鎖失敗 (Code {result.returncode}): {result.stderr}")
            return False
    except Exception as e:
        print(f"[System] 執行腳本發生錯誤: {e}")
        return False

def check_and_mark_offline(db: Session, timeout_seconds: int = 45):
    """
    檢查所有目前狀態為 'online' 的學生
    如果他們最近一筆連線紀錄超過 timeout_seconds 秒，就標記為 'offline'
    """
    try:
        # 1. 找出所有目前資料庫標記為 online 的學生
        online_students = db.query(StudentRecord).filter(StudentRecord.status == 'online').all()
        
        # 設定逾時時間點 (現在時間 - 容許秒數)
        # 注意：這裡必須跟 ConnectionLog 的寫入時間時區一致，建議都用 utcnow
        cutoff_time = datetime.utcnow() - timedelta(seconds=timeout_seconds)
        
        offline_count = 0
        
        for student in online_students:
            # 2. 找該學生最後一次的連線紀錄
            last_log = db.query(ConnectionLog)\
                .filter(ConnectionLog.mac_address == student.mac_address)\
                .order_by(ConnectionLog.timestamp.desc())\
                .first()

            if last_log:
                now = datetime.utcnow()
                diff = now - last_log.timestamp
                print(f"現在時間: {datetime.utcnow()}")
                print(f"最後紀錄: {last_log.timestamp}")
                print(f"相差秒數: {diff.total_seconds()}")
            
            # 3. 判斷是否逾時
            # 如果完全沒紀錄，或者最後紀錄時間早於截止時間 -> 判定離線
            if not last_log or last_log.timestamp < cutoff_time:
                print(f"[System] 偵測到 {student.name} ({student.mac_address}) 已離線")
                student.status = 'offline'
                offline_count += 1
        
        if offline_count > 0:
            db.commit()
            # print(f"[System] 已將 {offline_count} 位使用者標記為離線")
            
    except Exception as e:
        print(f"[Check Offline Error] {e}")
        db.rollback()

# === 定期掃描網路 (Background Task) ===
async def network_scanner_loop():
    print(f"[System] 啟動 ARP 掃描器，目標網段: {TARGET_NETWORK}")
    while True:
        try:
            db = SessionLocal()
            registry_service = StudentRegistryService(db)
            
            # 1. 執行掃描 (將掃到的裝置更新為 Online / 寫入 Log)
            scan_results = scanner.scan(TARGET_NETWORK) 
            if scan_results:
                registry_service.process_scan_results(scan_results)
            
            # 2. ### 新增：檢查並標記離線使用者 ###
            # 建議設定 45~60 秒。因為掃描每 5 秒一次，給一點緩衝避免訊號不穩閃爍
            check_and_mark_offline(db, timeout_seconds=45)
            
            db.close()
        except Exception as e:
            print(f"[Scanner Loop Error] {e}") 
            pass
            
        await asyncio.sleep(5)
@app.on_event("startup")
async def startup_event():
    # 建立資料庫表格
    init_db()
    os.makedirs("data/uploads", exist_ok=True)
    
    asyncio.create_task(network_scanner_loop())
    
    # 恢復防火牆狀態 (使用 Mock 不會報錯)
    db = SessionLocal()
    await auth_service.restore_state(db)
    db.close()
    print("[System] 系統啟動完成")

# === API Endpoints ===

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/portal/config")
async def get_config():
    return await portal_service.get_portal_config()

@app.get("/api/auth/status")
async def check_auth_status(
    mac: str = Depends(get_current_mac),
    db: Session = Depends(get_db)
):
    """前端 Polling 狀態"""
    is_authorized = await portal_service.check_authorization_status(db, mac)
    return {"mac": mac, "authorized": is_authorized}

# --- Dashboard 相關 API ---

@app.post("/api/register")
async def register(data: RegisterRequest, db: Session = Depends(get_db)):
    # 檢查 Email 是否已被註冊
    existing_user = user_repo.get_user_by_email(db, email=data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="此電子郵件已被註冊")
    
    # 簡單把密碼反轉當作加密示範，避免明碼存入
    fake_hashed_password = data.password + "_secret" 
    
    # 寫入資料庫
    new_user = user_repo.create_user(
        db=db,
        name=data.name,
        email=data.email,
        hashed_password=fake_hashed_password
    )
    
    return {"status": "success", "message": "註冊成功，請登入", "user_id": new_user.id}

@app.post("/api/login")
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    print(f"收到登入請求: {data.email}")
    
    # 查詢使用者
    user = user_repo.get_user_by_email(db, email=data.email)
    
    if not user:
        raise HTTPException(status_code=401, detail="帳號不存在")
    
    # 驗證密碼 (對應上面的加密邏輯)
    verify_password = data.password + "_secret"
    
    if user.hashed_password != verify_password:
        raise HTTPException(status_code=401, detail="密碼錯誤")
        
    # 登入成功，回傳資料
    return {
        "status": "success",
        "token": f"token-{uuid.uuid4()}",
        "user": {
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }

@app.get("/api/students")
async def get_students(db: Session = Depends(get_db)):
    students = student_repo.get_all_students(db) # 這裡現在會正常運作了
    response_data = []
    
    cutoff_time = datetime.utcnow() - timedelta(seconds=30)

    for s in students:
        last_log = db.query(ConnectionLog)\
            .filter(ConnectionLog.mac_address == s.mac_address)\
            .order_by(ConnectionLog.timestamp.desc())\
            .first()
            
        is_online = False
        
        # 修改這裡：
        # 前端 teacher.html 判斷 traffic > 1000 才會變紅燈
        # 我們讓違規次數 > 0 的人，流量看起來很高
        # TEST
        current_traffic = s.violation_count * 100 
        
        if last_log and last_log.timestamp > cutoff_time:
            is_online = True
            
        response_data.append({
            "student_id": s.student_id,
            "name": s.name,
            "mac": s.mac_address,
            "status": "online" if is_online else "offline",
            "violation_count": s.violation_count,
            "traffic": current_traffic # 傳回計算後的模擬流量
        })
        
    return response_data

@app.post("/api/admin/upload")
async def upload_material(file: UploadFile = File(...)):
    """教師上傳 PDF 教材"""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支援 PDF 檔案")
    
    content = await file.read()
    success = pdf_loader.save_and_extract(content, file.filename)
    
    if success:
        return {"message": f"成功載入：{file.filename}，知識庫片段數: {len(pdf_loader.knowledge_base)}"}
    else:
        raise HTTPException(status_code=500, detail="解析 PDF 失敗")
        
# 取得已上傳檔案
@app.get("/api/admin/files")
async def get_uploaded_files():
    upload_dir = "data/uploads"
    files = []
    
    # 確保資料夾存在
    if os.path.exists(upload_dir):
        # 讀取資料夾內所有檔案
        for filename in os.listdir(upload_dir):
            if filename.endswith(".pdf"):
                file_path = os.path.join(upload_dir, filename)
                
                # 取得檔案建立時間
                timestamp = os.path.getctime(file_path)
                date_str = datetime.fromtimestamp(timestamp).strftime('%Y/%m/%d')
                
                files.append({
                    "name": filename,
                    "date": date_str
                })
    
    # 回傳前端
    return files

# --- 測驗相關 ---

@app.post("/api/quiz/init")
async def init_quiz(mac: str = Depends(get_current_mac)):
    return {"status": "initialized", "mac": mac}

@app.get("/api/quiz")
async def get_quiz():
    """生成測驗題目 (RAG)"""
    # 隨機抓一段教材
    context = pdf_loader.get_random_context()
    context_len = len(context) if context else 0
    print(f"[RAG] 取得教材，長度: {context_len}")

    # AI 出題 (這裡不能直接 return，否則無法記錄答案)
    try:
        quiz_data = {}
        if context:
            quiz_data = await ai_service.generate_quiz(context_text=context)
        else:
            print("[AI] 知識庫為空，使用通用題庫")
            quiz_data = await ai_service.generate_quiz()
        
        # Server 端處理答案
        # 正確答案索引 -> A,B,C,D
        option_map = ['A', 'B', 'C', 'D']
        correct_idx = quiz_data.get("correct_index", 0)
        
        try:
            correct_idx = int(correct_idx)
        except:
            correct_idx = 0
            
        if correct_idx < 0 or correct_idx >= len(option_map): 
            correct_idx = 0
        
        correct_answer_char = option_map[correct_idx]
        
        # 產生唯一的 Question ID (取代 AI 給的隨機 ID，避免重複)
        q_id = str(uuid.uuid4())
        quiz_data['id'] = q_id
        ACTIVE_QUIZZES[q_id] = correct_answer_char
        
        # 作弊小抄
        print(f"\n====== [AI 出題作弊小抄] ======")
        print(f"題目 QID: {q_id}")
        print(f"AI 認定的正確答案: 【 {correct_answer_char} 】")
        print(f"==============================\n")
        
        if 'correct_index' in quiz_data:
            del quiz_data['correct_index']
            
        return quiz_data

    except Exception as e:
        print(f"[AI Error] Generation Failed: {e}")
        return await ai_service.get_fallback_quiz()

@app.post("/api/quiz/answer")
async def submit_answer(
    answer_data: dict,
    db: Session = Depends(get_db)
):
    """提交答案進行比對並計算懲罰邏輯"""
    user_mac = answer_data.get("student_id")
    question_id = answer_data.get("question_id")
    user_answer = answer_data.get("answer")
    
    print(f"[Answer] MAC: {user_mac}, QID: {question_id}, User: {user_answer}")
    
    # 檢查題目是否存在
    real_answer = ""
    if question_id not in ACTIVE_QUIZZES:
        if question_id == "fallback":
            real_answer = "B" # 假設備用題答案固定
        else:
            return {"status": "error", "message": "題目已過期，請重新整理"}
    else:
        real_answer = ACTIVE_QUIZZES[question_id]
    
    # 進行比對
    is_correct = (user_answer == real_answer)
    
    # 初始化或取得學生狀態
    if user_mac not in student_quiz_state:
        student_quiz_state[user_mac] = {"penalty": 0, "wrong_count": 0}
    state = student_quiz_state[user_mac]

    # --- 判斷對錯與懲罰邏輯 ---
    if is_correct:
        # 答對
        if question_id in ACTIVE_QUIZZES:
            del ACTIVE_QUIZZES[question_id]

        if state["penalty"] == 0:
            # 沒有懲罰 -> 正常解鎖
            await portal_service.authorize_device(db, user_mac)
            # 任務完成，移除學生狀態
            if user_mac in student_quiz_state:
                del student_quiz_state[user_mac]
            return {"status": "unlocked", "message": "恭喜答對！", "penalty": 0, "correct": True}
        else:
            # 後來答對，但之前有累積懲罰
            return {"status": "pay_penalty", "message": "答對了！但需支付累積罰款", "penalty": state["penalty"], "correct": True}
    else:
        # 答錯
        state["penalty"] += 20
        state["wrong_count"] += 1
        
        return {
            "status": "wrong", 
            "message": f"答錯了！", 
            "penalty": state["penalty"],
            "correct": False,
            # 回傳 wrong_count 讓前端決定是否彈窗
            "wrong_count": state["wrong_count"] 
        }

# --- 放棄作答 API ---

@app.post("/api/quiz/giveup")
async def give_up_quiz(data: dict):
    user_mac = data.get("student_id")
    total_amount = 70 + (student_quiz_state[user_mac]["penalty"] if user_mac in student_quiz_state else 0)
    return {"status": "pay_capital", "amount": total_amount}

# --- 付款確認 API ---
@app.post("/api/payment/confirm")
async def confirm_payment(data: dict, db: Session = Depends(get_db)):
    """前端轉盤頁面按下支付確認按鈕時的處理（假設走假支付或手動確認）"""
    user_mac = data.get("mac_address")
    user_ip = get_ip_by_mac(user_mac)
    
    if not user_ip:
        last_log = db.query(ConnectionLog).filter(ConnectionLog.mac_address == user_mac).order_by(ConnectionLog.timestamp.desc()).first()
        if last_log: user_ip = last_log.ip_address

    student = db.query(StudentRecord).filter(StudentRecord.mac_address == user_mac).first()
    if student and getattr(student, 'p_status', 'NORMAL') == 'PUNISHED':
        student.p_status = 'NORMAL'
        db.commit()

    await portal_service.authorize_device(db, user_mac)
    if user_ip: execute_restore_script(user_ip, WIFI_INTERFACE)

    if user_mac in student_quiz_state: del student_quiz_state[user_mac]
    return {"status": "success", "message": "付款成功，違規狀態已解除，網路已解鎖"}

@app.get("/api/payment/check")
async def check_payment_status(mac: str = Depends(get_current_mac), db: Session = Depends(get_db)):
    if mac not in student_quiz_state:
        if await portal_service.check_authorization_status(db, mac):
            return {"status": "paid", "message": "已付款"}
        return {"status": "error", "message": "無需處理"}
    
    if student_quiz_state[mac].get("payment_status") == "paid":
        await portal_service.authorize_device(db, mac)
        del student_quiz_state[mac]
        return {"status": "paid", "message": "付款成功"}
    return {"status": "pending", "message": "等待付款中..."}


# === 修正後的 Payment Callback API ===
@app.post("/api/payment/callback")
async def payment_callback(data: dict, db: Session = Depends(get_db)):
    """
    接收來自 Telegram Bot 的付款通知
    Payload: {"telegram_id": "12345", "amount": 100, ...}
    """
    tg_id = data.get("telegram_id")
    
    if not tg_id:
        return {"status": "error", "message": "缺少 telegram_id 參數"}

    print(f"[Payment] 收到付款通知，Telegram ID: {tg_id}")
    
    # 1. 透過 Telegram ID 查找學生
    student = db.query(StudentRecord).filter(StudentRecord.telegram_id == str(tg_id)).first()
    
    if not student:
        return {"status": "error", "message": "找不到對應的學生紀錄 (未綁定)"}

    target_mac = student.mac_address
    print(f"[Payment] 對應學生: {student.name}, MAC: {target_mac}")
    
    # 2. 更新暫存狀態 (讓前端 Polling 也能知道已付款)
    if target_mac in student_quiz_state:
        student_quiz_state[target_mac]["payment_status"] = "paid"
    
    # 3. 更新資料庫懲罰狀態
    if getattr(student, 'p_status', 'NORMAL') == 'PUNISHED':
        student.p_status = 'NORMAL'
        db.commit()
        print(f"[Payment] 已解除 PUNISHED 狀態")

    # 4. 取得 IP 並執行解鎖
    # 先嘗試 ARP 表
    user_ip = get_ip_by_mac(target_mac)
    
    # 如果 ARP 沒資料，嘗試從資料庫找最近連線
    if not user_ip:
        last_log = db.query(ConnectionLog)\
            .filter(ConnectionLog.mac_address == target_mac)\
            .order_by(ConnectionLog.timestamp.desc())\
            .first()
        if last_log:
            user_ip = last_log.ip_address
            print(f"[Payment] ARP 未命中，使用最後連線 IP: {user_ip}")

    # 執行系統授權 (FastAPI 層)
    await portal_service.authorize_device(db, target_mac)

    # 執行物理層解鎖 (Shell Script)
    if user_ip:
        success = execute_restore_script(user_ip, WIFI_INTERFACE)
        if success:
            return {"status": "success", "message": f"已成功解鎖 {student.name} ({user_ip})"}
        else:
            return {"status": "warning", "message": "資料庫已更新，但防火牆腳本執行失敗"}
    else:
        return {"status": "warning", "message": "資料庫已更新，但找不到裝置 IP，請重新連線"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
