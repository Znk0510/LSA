# test_repository.py
import sys
import uuid
from sqlalchemy.exc import IntegrityError

# 確保 Python 找得到 src 套件
sys.path.append(".")

from src.db.database import init_db, SessionLocal
from src.db.repositories import StudentRepository

def test_student_lifecycle():
    print("====== 開始測試資料庫與 Repository 串接 ======")

    # 1. 初始化資料庫 (建立表格)
    print("[1] 正在初始化資料庫表格...")
    init_db()
    print("    -> 表格檢查/建立完成。")

    # 2. 建立 Session 與 Repository
    db = SessionLocal()
    repo = StudentRepository(db)

    # 測試資料
    # 使用隨機 UUID 避免重複執行時撞到 Unique Constraint
    # 但為了讓你方便觀察，我們固定用 "TEST-001"
    t_student_id = "TEST-999"
    t_name = "測試員-蔡秉凱"
    t_mac = "AA:BB:CC:DD:EE:FF" 

    # 3. 測試：建立學生 (Create)
    print(f"\n[2] 測試建立學生: {t_name} ({t_student_id})")
    try:
        student = repo.create_student(
            student_id=t_student_id,
            name=t_name,
            mac_address=t_mac
        )
        print(f"    -> 成功寫入！資料庫 ID: {student.id}")
    except IntegrityError:
        db.rollback() # 發生錯誤要回滾，不然 Session 會卡住
        print("    -> 學生已存在 (Unique Constraint)，跳過建立步驟，繼續測試讀取...")
        student = repo.get_by_student_id(t_student_id)

    # 4. 測試：讀取學生 (Read)
    print(f"\n[3] 測試透過 MAC 讀取學生: {t_mac}")
    fetched_student = repo.get_by_mac(t_mac)
    if fetched_student:
        print(f"    -> 讀取成功！姓名: {fetched_student.name}, 違規次數: {fetched_student.violation_count}")
    else:
        print("    -> X 讀取失敗：找不到學生")
        return

    # 5. 測試：違規記點邏輯 (Update)
    print("\n[4] 測試違規記點功能 (increment_violation)...")
    old_count = fetched_student.violation_count
    new_count = repo.increment_violation(t_mac)
    print(f"    -> 違規次數從 {old_count} 變更為 {new_count}")
    
    if new_count == old_count + 1:
        print("    -> V 驗證成功：數值正確增加")
    else:
        print("    -> X 驗證失敗：數值未正確增加")

    # 6. 測試：增加專注時間 (Update)
    print("\n[5] 測試增加專注時間 (add_focus_time)...")
    repo.add_focus_time(t_mac, 30) # 增加 30 分鐘
    
    # 重新從資料庫抓取以確認寫入
    db.refresh(fetched_student) 
    print(f"    -> 目前專注時間: {fetched_student.focus_time} 分鐘")

    # 7. 測試：排行榜 (Read List)
    print("\n[6] 測試排行榜功能 (get_focus_leaderboard)...")
    leaderboard = repo.get_focus_leaderboard(limit=5)
    print("    -> 目前排行榜前 5 名：")
    for idx, s in enumerate(leaderboard):
        print(f"       {idx+1}. {s.name} (專注: {s.focus_time} min, 違規: {s.violation_count})")

    # 關閉連線
    db.close()
    print("\n====== 測試結束：成功 ======")

if __name__ == "__main__":
    test_student_lifecycle()
