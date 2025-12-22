from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Text, JSON
from .database import Base

# ==========================================
# Part 1: Pydantic Models (API 資料傳輸用)
# ==========================================
# 用來在 API 請求/回應中驗證資料格式的

# 註冊 (對應老師前端的 registerForm)
class RegisterRequest(BaseModel):
    name: str
    email: str # Pydantic 會自動驗證是否為 Email 格式
    password: str

# 登入 (對應老師前端的 loginForm)
class LoginRequest(BaseModel):
    email: str
    password: str

class ARPScanResult(BaseModel):
    ip: str
    mac: str
    timestamp: datetime = Field(default_factory=datetime.now)

class Student(BaseModel):
    student_id: str
    name: str
    mac_address: str
    telegram_id: Optional[str] = None
    registered_at: datetime = Field(default_factory=datetime.now)
    status: str = "offline"

class AuthorizationRecord(BaseModel):
    mac_address: str
    status: str
    authorized_at: datetime
    expires_at: Optional[datetime] = None
    details: Dict[str, Any] = {}

class ViolationReport(BaseModel):
    ip: str
    violation_type: str
    action: str

# ==========================================
# Part 2: SQLAlchemy Models (PostgreSQL 資料表結構)
# ==========================================
# 真正會寫入資料庫的表格定義

class User(Base):
    __tablename__ = 'users'

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="teacher")
    created_at = Column(DateTime, default=datetime.utcnow)

class StudentRecord(Base):
    """學生名單資料表"""
    __tablename__ = 'students'

    id = Column(String, primary_key=True) 
    student_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    mac_address = Column(String, unique=True, nullable=False, index=True)
    
    # 狀態管理
    p_status = Column(String, default="NORMAL") 
    status = Column(String, default="offline") 
    
    # 專注排行榜與違規統計
    violation_count = Column(Integer, default=0)
    focus_time = Column(Integer, default=0)
    
    # Telegram 綁定
    telegram_id = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ConnectionLog(Base):
    """連線歷史記錄"""
    __tablename__ = 'connection_logs'
  
    id = Column(String, primary_key=True)
    mac_address = Column(String, nullable=False, index=True)
    ip_address = Column(String, nullable=False)
    student_id = Column(String, nullable=True)
    status = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class AuthorizationLog(Base):
    """授權變更記錄"""
    __tablename__ = 'authorization_logs'
    
    id = Column(String, primary_key=True)
    mac_address = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False) 
    authorized_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    details = Column(JSON, nullable=True)

class QuizAttempt(Base):
    """測驗作答記錄"""
    __tablename__ = 'quiz_attempts'
    
    id = Column(String, primary_key=True)
    mac_address = Column(String, nullable=False, index=True)
    question_id = Column(String, nullable=False)
    selected_answer = Column(Integer, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)
