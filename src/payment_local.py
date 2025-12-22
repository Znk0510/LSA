import os
import asyncio
import logging
import aiohttp
import subprocess
import uuid
import sys
from datetime import datetime, timezone

# Aiogram 核心
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import LabeledPrice, PreCheckoutQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# --- 路徑修正 (確保能讀到 src 的模組) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir) # 專案根目錄
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# 資料庫引用
from src.db.database import SessionLocal
from src.db.models import StudentRecord, ConnectionLog, AuthorizationLog

load_dotenv()

# --- 設定區 ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
# 星星支付不需要 Token，留空
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

# 設定 Log
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("kda_master_bot")

if not BOT_TOKEN:
    raise ValueError("❌ 錯誤: 未設定 BOT_TOKEN，請檢查 .env 檔案")

# 初始化 Bot 與 Dispatcher (加入 FSM 記憶體儲存)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- 定義註冊流程的狀態機 (FSM) ---
class Registration(StatesGroup):
    waiting_for_student_id = State()
    waiting_for_name = State()

# --- 輔助函式區 ---

def get_db():
    return SessionLocal()

def get_mac_address(ip):
    """
    從系統 ARP 表查找 IP 對應的 MAC
    (移植自 wifi_bot.py)
    """
    try:
        # 先 ping 一下確保 ARP 表有資料 (timeout 1秒)
        subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 讀取 ARP 表
        cmd = f"ip neigh show {ip}"
        output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        if "lladdr" in output:
            parts = output.split()
            try:
                # 輸出格式通常是: 192.168.100.x dev eno1 lladdr aa:bb:cc:dd:ee:ff REACHABLE
                return parts[parts.index("lladdr") + 1]
            except ValueError:
                pass
        return "UNKNOWN"
    except Exception as e:
        logger.error(f"MAC 查找失敗: {e}")
        return "UNKNOWN"

def activate_student_network(chat_id, student_record, ip_address):
    """
    啟用網路權限並寫入紀錄
    (整合了 login.sh 的呼叫與資料庫寫入)
    """
    db = get_db()
    try:
        # 1. 寫入連線紀錄
        new_conn = ConnectionLog(
            id=str(uuid.uuid4()),
            mac_address=student_record.mac_address,
            ip_address=ip_address,
            student_id=student_record.student_id,
            status="connected",
            timestamp=datetime.now(timezone.utc)
        )
        db.add(new_conn)

        # 2. 寫入授權紀錄
        new_auth = AuthorizationLog(
            id=str(uuid.uuid4()),
            mac_address=student_record.mac_address,
            status="active",
            authorized_at=datetime.now(timezone.utc),
            details={"source": "telegram_bot", "chat_id": str(chat_id)}
        )
        db.add(new_auth)
        
        # 3. 更新學生狀態為 online
        db.query(StudentRecord).\
            filter(StudentRecord.student_id == student_record.student_id).\
            update({"status": "online"})
            
        db.commit()
        logger.info(f"學生 {student_record.name} 資料庫狀態已更新為 Online")

        # 4. 執行 Linux 開網腳本
        # 請確保路徑正確，假設專案結構:
        # root/
        #   src/payment_local.py
        #   lsa/login.sh
        script_path = os.path.join(parent_dir, "LSA", "login.sh")
        
        if os.path.exists(script_path):
            # 執行 sudo ./lsa/login.sh <IP>
            subprocess.run(["sudo", script_path, ip_address])
            return True, "✅ <b>網路已開通！</b>\n系統已放行您的裝置，請關閉此視窗，回到瀏覽器開始上網。"
        else:
            logger.error(f"找不到腳本: {script_path}")
            return False, "⚠️ 找不到開網腳本，請聯繫管理員。"
            
    except Exception as e:
        logger.error(f"開通失敗: {e}")
        db.rollback()
        return False, "⚠️ 系統錯誤，開通失敗。"
    finally:
        db.close()

async def notify_backend(action: str, payload: dict):
    """通知後端 API (用於付款解鎖)"""
    url = f"{BACKEND_API_URL}/api/{action}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    return True, await resp.json()
                else:
                    return False, await resp.text()
    except Exception as e:
        return False, str(e)

# --- Handler: /start 指令 ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    args = command.args
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    
    # ---------------------------------------------------------
    # 模式 A: 付款流程 (參數包含 pay_ 或 undefined_)
    # ---------------------------------------------------------
    if args and (args.startswith("pay_") or args.startswith("undefined_")):
        try:
            amount_str = args.split("_")[1]
            amount = int(amount_str)
            logger.info(f"💰 [付款] 用戶 {user_name} ({user_id}), 金額 {amount}")

            await bot.send_invoice(
                chat_id=message.chat.id,
                title="KDA 違規罰款",
                description=f"依據課堂規則，需支付 {amount} 星星以解鎖網路。",
                payload=str(user_id), 
                provider_token=PAYMENT_PROVIDER_TOKEN,
                currency="XTR", 
                prices=[LabeledPrice(label="違規罰金", amount=amount)],
                start_parameter=f"pay_{amount}"
            )
        except Exception as e:
            logger.error(f"付款參數解析失敗: {e}")
            await message.answer("❌ 參數錯誤，無法產生帳單。")
        return

    # ---------------------------------------------------------
    # 模式 B: 登入註冊流程 (參數包含 IP，例如 192_168_1_10)
    # ---------------------------------------------------------
    if args and "_" in args and not args.startswith("pay"):
        # 將底線還原成點 (192_168_100_1 -> 192.168.100.1)
        user_ip = args.replace("_", ".")
        logger.info(f"👋 [登入] 用戶 {user_name}, IP: {user_ip}")

        # 1. 檢查是否已經註冊過
        db = get_db()
        student = db.query(StudentRecord).filter(StudentRecord.telegram_id == str(user_id)).first()
        
        if student:
            # --- 舊生：直接開通 ---
            await message.answer(f"歡迎回來，{student.name}！\n正在為您開通網路...")
            
            # 更新 MAC (防止換手機)
            current_mac = get_mac_address(user_ip)
            if current_mac != "UNKNOWN" and current_mac != student.mac_address:
                student.mac_address = current_mac
                db.commit() # 更新 MAC
            
            db.close()
            
            # 執行開通
            success, msg = activate_student_network(user_id, student, user_ip)
            await message.answer(msg, parse_mode="HTML")
            
        else:
            # --- 新生：開始註冊流程 ---
            db.close()
            
            # 檢查 MAC 是否抓得到 (確認有連上 Wi-Fi)
            mac = get_mac_address(user_ip)
            if mac == "UNKNOWN":
                await message.answer("⚠️ <b>無法偵測到您的裝置</b>\n請確認您已連上教室 Wi-Fi 後，重新點擊網頁上的按鈕。", parse_mode="HTML")
                return

            # 儲存暫時資訊到狀態機
            await state.update_data(ip=user_ip, mac=mac)
            await state.set_state(Registration.waiting_for_student_id)
            await message.answer(f"👋 初次見面！偵測到您的 IP 為 {user_ip}\n\n請輸入您的 **學號**：", parse_mode="Markdown")
        return

    # ---------------------------------------------------------
    # 模式 C: 無參數 (直接在 TG 裡點開始)
    # ---------------------------------------------------------
    await message.answer(
        f"🤖 <b>KDA 智慧教室助理</b>\nID: <code>{user_id}</code>\n\n本機器人需透過網頁連結啟動，請回到瀏覽器操作。",
        parse_mode="HTML"
    )

# --- Handler: 註冊流程對話 (State Machine) ---

@dp.message(Registration.waiting_for_student_id)
async def process_student_id(message: types.Message, state: FSMContext):
    if not message.text: return
    await state.update_data(student_id=message.text.strip())
    await state.set_state(Registration.waiting_for_name)
    await message.answer("收到，請輸入您的 **真實姓名**：", parse_mode="Markdown")

@dp.message(Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text: return
    
    # 取出所有暫存資料
    data = await state.get_data()
    student_id = data['student_id']
    ip = data['ip']
    mac = data['mac']
    name = message.text.strip()
    user_id = str(message.from_user.id)

    db = get_db()
    try:
        # 建立新學生資料
        new_student = StudentRecord(
            id=str(uuid.uuid4()),
            student_id=student_id,
            name=name,
            mac_address=mac,
            telegram_id=user_id,
            p_status='NORMAL',
            status='offline' 
        )
        db.add(new_student)
        db.commit()
        
        await message.answer(f"✅ 註冊成功！{name} ({student_id})")
        
        # 馬上開通
        success, msg = activate_student_network(user_id, new_student, ip)
        await message.answer(msg, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"註冊失敗: {e}")
        await message.answer("❌ 註冊過程發生錯誤，請稍後再試或聯繫管理員。")
    finally:
        db.close()
        await state.clear() # 結束對話狀態

# --- Handler: 支付流程 ---

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def success_payment(message: types.Message):
    payment = message.successful_payment
    total_amount = payment.total_amount
    user_id = message.from_user.id
    
    logger.info(f"✅ 付款成功! 用戶 ID: {user_id}, 金額: {total_amount}")
    await message.answer(f"🎉 <b>收到 {total_amount} 星星！</b>\n系統正在搜尋裝置並解鎖...", parse_mode="HTML")

    success, resp = await notify_backend("payment/callback", {
        "telegram_id": str(user_id),
        "payment_id": payment.telegram_payment_charge_id,
        "amount": total_amount
    })

    if success:
        msg = resp.get("message", "網路已恢復")
        await message.answer(f"✅ <b>{msg}</b>\n請關閉視窗並重新整理網頁。", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ <b>解鎖失敗</b>\n{resp}", parse_mode="HTML")

# --- 啟動 ---
if __name__ == "__main__":
    print("🤖 KDA 全能機器人 (Master Bot) 啟動中...")
    asyncio.run(dp.start_polling(bot))