from typing import Dict
from sqlalchemy.orm import Session
from src.core.auth_service import AuthorizationService

class CaptivePortalService:
    def __init__(self, auth_service: AuthorizationService):
        # 注入 Phase 4 的 AuthorizationService
        self.auth_service = auth_service

    async def check_authorization_status(self, db: Session, mac: str) -> bool:
        # 改為查詢真正的資料庫
        return await self.auth_service.is_authorized(db, mac)

    async def authorize_device(self, db: Session, mac: str):
        # 呼叫核心服務 -> 寫入 Log -> 觸發防火牆 Script
        await self.auth_service.authorize(db, mac, details={"source": "captive_portal"})

    async def revoke_device(self, db: Session, mac: str):
        # 呼叫核心服務撤銷
        await self.auth_service.revoke(db, mac)

    async def get_portal_config(self) -> Dict:
        return {
            "payment_url": "https://paypal.com/fake-payment",
            "quiz_rules": "請回答 3 題 AI 生成的問題以解鎖網路。",
            "maintenance_mode": False
        }
