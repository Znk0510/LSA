from src.db.database import init_db, SessionLocal
from src.core import models 
from sqlalchemy import text  # <--- 新增這一行

print("1. 開始初始化資料庫...")
try:
    init_db()
    print("   資料庫表格初始化成功！")
except Exception as e:
    print(f"X  資料庫初始化失敗: {e}")
    exit(1)

print("2. 測試資料庫連線與寫入...")
db = SessionLocal()
try:
    # 使用 text() 包裝 SQL 語句
    db.execute(text("SELECT 1"))  # <--- 修改這裡
    print("   連線測試成功！")
finally:
    db.close()
