import uuid
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from src.db.models import StudentRecord, ConnectionLog, AuthorizationLog, User

class UserRepository:
    """
    負責老師的存取
    """
    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email == email).first()

    def create_user(self, db: Session, name: str, email: str, hashed_password: str) -> User:
        new_user = User(
            id=str(uuid.uuid4()),
            name=name,
            email=email,
            hashed_password=hashed_password,
            created_at=datetime.utcnow()
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

class StudentRepository:
    """
    負責學生資料 (StudentRegistry) 的存取
    """
    def get_student_by_mac(self, db: Session, mac_address: str) -> Optional[StudentRecord]:
        return db.query(StudentRecord).filter(StudentRecord.mac_address == mac_address).first()

    def create_student(self, db: Session, student_id: str, name: str, mac_address: str) -> StudentRecord:
        student = StudentRecord(
            id=str(uuid.uuid4()),
            student_id=student_id,
            name=name,
            mac_address=mac_address,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(student)
        db.commit()
        db.refresh(student)
        return student

    def get_all_students(self, db: Session) -> List[StudentRecord]:
        return db.query(StudentRecord).all()


class ConnectionLogRepository:
    """
    負責網路連線紀錄 (Connection Logs) 的存取
    """
    def create_log(self, db: Session, mac_address: str, ip_address: str, status: str, student_id: Optional[str] = None) -> ConnectionLog:
        log = ConnectionLog(
            id=str(uuid.uuid4()),
            mac_address=mac_address,
            ip_address=ip_address,
            student_id=student_id,
            status=status,
            timestamp=datetime.utcnow()
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def get_logs_by_mac(self, db: Session, mac_address: str, limit: int = 50) -> List[ConnectionLog]:
        return db.query(ConnectionLog)\
            .filter(ConnectionLog.mac_address == mac_address)\
            .order_by(desc(ConnectionLog.timestamp))\
            .limit(limit)\
            .all()


class AuthorizationLogRepository:
    """
    負責授權狀態紀錄 (Authorization Logs) 的存取
    這是 Phase 4 與 Phase 5 的核心
    """
    
    def create_log(self, db: Session, mac_address: str, status: str, details: str = "{}") -> AuthorizationLog:
        """
        新增一筆授權或撤銷紀錄
        """
        now = datetime.utcnow()
        
        # 根據狀態設定對應的時間欄位
        # 注意：為了符合 Database Schema (authorized_at NOT NULL)，
        # 我們將 'authorized_at' 當作 'event_time' 使用，或在撤銷時填入當前時間
        
        log = AuthorizationLog(
            id=str(uuid.uuid4()),
            mac_address=mac_address,
            status=status,
            details=details,
            authorized_at=now,  # 記錄事件發生的時間
            revoked_at=now if status == "revoked" else None,
            expires_at=None     # 未來可擴充過期邏輯
        )
        
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def get_latest_log(self, db: Session, mac_address: str) -> Optional[AuthorizationLog]:
        """
        取得該 MAC 最近的一筆狀態變更紀錄
        """
        return db.query(AuthorizationLog)\
            .filter(AuthorizationLog.mac_address == mac_address)\
            .order_by(desc(AuthorizationLog.authorized_at))\
            .first()

    def get_logs(self, db: Session, limit: int = 100) -> List[AuthorizationLog]:
        """
        取得系統最近的授權紀錄 (供稽核使用)
        """
        return db.query(AuthorizationLog)\
            .order_by(desc(AuthorizationLog.authorized_at))\
            .limit(limit)\
            .all()
