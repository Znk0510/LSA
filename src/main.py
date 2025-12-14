import asyncio
import random
import os
import uuid
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
from src.db.database import SessionLocal, engine, Base
from src.db.repositories import AuthorizationLogRepository, StudentRepository

# 核心服務與網路元件
# 測試用 Mock，實際換成 ShellScriptFirewallController
from src.network.firewall import MockFirewallController
from src.network.scanner import ARPScanner
from src.network.registry import StudentRegistryService
from src.core.auth_service import AuthorizationService
from src.gateway.service import CaptivePortalService

# === 設定區 ===
# 請使用 ip addr 確認無線網卡名稱 (例如 wlan0, wlp2s0)
WIFI_INTERFACE = "lo"  
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
origins = ["http://localhost", "http://127.0.0.1", "http://example.com", "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

# --- 題目答案暫存區 ---
# 結構: { "question_uuid": "A" }
ACTIVE_QUIZZES = {}

# --- 學生測驗狀態暫存區 ---
# 格式: { "MAC_ADDRESS": { "penalty": 0, "wrong_count": 0 } }
student_quiz_state = {}

# === Helper: 取得 MAC ===
async def get_current_mac(
    request: Request,
    x_mac_address: Optional[str] = Header(None, alias="X-Mac-Address")
) -> str:
    if x_mac_address:
        return x_mac_address
    mac_param = request.query_params.get("mac")
    if mac_param:
        return mac_param
    return "00:00:00:00:00:00"

# === 定期掃描網路 (Background Task) ===
async def network_scanner_loop():
    print(f"[System] 啟動 ARP 掃描器，目標網段: {TARGET_NETWORK}")
    while True:
        try:
            db = SessionLocal()
            registry_service = StudentRegistryService(db)
            
            # 執行掃描
            scan_results = scanner.scan(TARGET_NETWORK) 
            
            if scan_results:
                registry_service.process_scan_results(scan_results)
            
            db.close()
        except Exception as e:
            # 這裡把錯誤印出來，但不要讓 loop 停下來
            # print(f"[Scanner Error] {e}") 
            pass
            
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    # 建立資料庫表格
    Base.metadata.create_all(bind=engine)
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

@app.post("/api/login")
async def login(data: dict):
    return {"token": "fake-jwt-token", "user": {"name": "陳老師"}}

# --- Dashboard 相關 API ---

@app.get("/api/students")
async def get_students(db: Session = Depends(get_db)):
    from src.db.models import StudentRecord, ConnectionLog
    
    all_students = db.query(StudentRecord).all()
    response_data = []
    # 判斷狀態 (最近 15 秒內有連線紀錄就算 online)
    cutoff_time = datetime.utcnow() - timedelta(seconds=15)
    
    for student in all_students:
        recent_log = db.query(ConnectionLog)\
            .filter(ConnectionLog.student_id == student.student_id)\
            .filter(ConnectionLog.timestamp > cutoff_time)\
            .first()
            
        status = "online" if recent_log else "offline"
        traffic = random.randint(10, 800) if status == "online" else 0
        
        response_data.append({
            "student_id": student.student_id,
            "name": student.name,
            "status": status,
            "traffic": traffic,
            "mac": student.mac_address
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
    # 基礎費用 70 + 累積罰款
    total_amount = 70
    if user_mac in student_quiz_state:
        total_amount += student_quiz_state[user_mac]["penalty"]
    
    return {"status": "pay_capital", "amount": total_amount}

# --- 付款確認 API ---
@app.post("/api/payment/confirm")
async def confirm_payment(
    data: dict,
    db: Session = Depends(get_db)
):
    user_mac = data.get("student_id")
    # 解鎖網路
    await portal_service.authorize_device(db, user_mac)
    
    # 清除罰款狀態
    if user_mac in student_quiz_state:
        del student_quiz_state[user_mac]
        
    return {"status": "success", "message": "付款成功，網路已解鎖"}


# --- 付款相關 ---
# --- 檢查付款狀態 ---
@app.get("/api/payment/check")
async def check_payment_status(
    mac: str = Depends(get_current_mac),
    db: Session = Depends(get_db)
):
    # 檢查是否在名單中
    if mac not in student_quiz_state:
        # 如果不在名單中，可能是已經解鎖並移除了，或是根本沒欠費
        # 檢查是否已授權
        if await portal_service.check_authorization_status(db, mac):
            return {"status": "paid", "message": "已付款"}
        return {"status": "error", "message": "無需處理"}

    state = student_quiz_state[mac]
    
    # 檢查狀態是否變成 paid
    if state.get("payment_status") == "paid":
        # 執行解鎖
        await portal_service.authorize_device(db, mac)
        # 清除狀態
        del student_quiz_state[mac]
        return {"status": "paid", "message": "付款成功"}
    
    return {"status": "pending", "message": "等待付款中..."}

# --- 模擬 TG Bot ---
# 真實：TG Bot 收到錢後，會打這個 API 通知 Server
@app.post("/api/payment/callback")
async def payment_callback(data: dict):
    target_mac = data.get("student_id") # 或是用 mac
    
    if target_mac in student_quiz_state:
        print(f"[Payment] 收到來自 TG 的付款通知: {target_mac}")
        student_quiz_state[target_mac]["payment_status"] = "paid"
        return {"status": "success", "message": "已標記為付款完成"}
    
    return {"status": "error", "message": "找不到該學生"}

# --- Debug APIs ---
@app.post("/api/debug/authorize")
async def debug_authorize(mac: str, db: Session = Depends(get_db)):
    await portal_service.authorize_device(db, mac)
    return {"message": f"Device {mac} authorized"}

@app.post("/api/debug/revoke")
async def debug_revoke(mac: str, db: Session = Depends(get_db)):
    await portal_service.revoke_device(db, mac)
    if mac in student_quiz_state:
        del student_quiz_state[mac] # 順便清除測驗狀態
    return {"message": f"Device {mac} revoked"}
