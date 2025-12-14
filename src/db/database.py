# src/db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# 使用你 models.py 中的設定
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lsa:lsapasswd@localhost/student_guard" 
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 定義 Base，讓 models.py 引用
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # 這會建立所有繼承自 Base 的 Table
    Base.metadata.create_all(bind=engine)
