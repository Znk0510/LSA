import sys
from datetime import datetime
from sqlalchemy import text

# 讓 Python 找得到 src
sys.path.append(".")

from src.db.database import init_db, SessionLocal
from src.network.registry import StudentRegistryService
from src.core.models import ARPScanResult
from src.db.repositories import StudentRepository

def test_attendance_logic():
    print("====== 開始測試出席比對邏輯 (Registry) ======")
    
    # 1. 初始化
    init_db()
    db = SessionLocal()
    registry = StudentRegistryService(db)
    student_repo = StudentRepository(db)

    # 2. 準備測試資料
    # 修改：為了避免誤刪其他測試資料，我們指定刪除這兩位特定的學生 ID
    try:
        db.execute(text("DELETE FROM students WHERE student_id IN ('s112213080', 's112213025')"))
        db.execute(text("DELETE FROM connection_logs"))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"清理舊資料失敗 (可能是第一次執行): {e}")

    print("[1] 正在建立測試學生資料...")
    
    # 學生 A: 蔡小凱 (MAC AA...) -> 設定為出席者
    s1 = student_repo.create_student("s112213080", "蔡小凱", "AA:AA:AA:AA:AA:AA")
    
    # 學生 B: 施小新 (MAC BB...) -> 設定為缺席者
    s2 = student_repo.create_student("s112213025", "施小新", "BB:BB:BB:BB:BB:BB")
    
    print(f"    -> 已建立: {s1.name} ({s1.student_id}) MAC: {s1.mac_address}")
    print(f"    -> 已建立: {s2.name} ({s2.student_id}) MAC: {s2.mac_address}")

    # 3. 模擬 ARP 掃描結果
    # 情境：只掃到 蔡小凱 (AA...) 和一個陌生人 (CC...)，施小新 (BB...) 沒出現
    print("\n[2] 模擬 ARP 掃描結果輸入...")
    fake_scan_results = [
        ARPScanResult(ip="192.168.1.101", mac="AA:AA:AA:AA:AA:AA"), # 蔡小凱
        ARPScanResult(ip="192.168.1.102", mac="CC:CC:CC:CC:CC:CC")  # 陌生人
    ]
    print(f"    -> 模擬掃描到 {len(fake_scan_results)} 個裝置")

    # 4. 執行核心比對功能
    print("\n[3] 執行 process_scan_results...")
    report = registry.process_scan_results(fake_scan_results)

    # 5. 驗證結果
    print("\n[4] 比對結果報告：")
    print(f"    -> 出席名單 (Present): {report['present']}")
    print(f"    -> 缺席名單 (Absent) : {report['absent']}")
    print(f"    -> 未知裝置數量      : {report['unknown_count']}")

    # 6. 自動驗證邏輯
    # 修改：驗證名稱改為新的學生名字
    if "蔡小凱" in report['present'] and "施小新" in report['absent']:
        print("\n✅ 測試成功：蔡小凱 被標記出席，施小新 被標記缺席。")
    else:
        print("\n❌ 測試失敗：名單分類不正確。")
        # 顯示詳細除錯資訊
        print(f"    預期出席: 蔡小凱, 實際: {report['present']}")
        print(f"    預期缺席: 施小新, 實際: {report['absent']}")

    db.close()

if __name__ == "__main__":
    test_attendance_logic()
