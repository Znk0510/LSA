from typing import Dict
from sqlalchemy.orm import Session
from src.core.auth_service import AuthorizationService

class CaptivePortalService:
    def __init__(self, auth_service: AuthorizationService):
        self.auth_service = auth_service

    async def check_authorization_status(self, db: Session, mac: str) -> bool:
        return await self.auth_service.is_authorized(db, mac)

    async def authorize_device(self, db: Session, mac: str, ip: str):
        await self.auth_service.authorize(db, mac, ip, details={"source": "captive_portal"})

    async def revoke_device(self, db: Session, mac: str, ip: str):
        await self.auth_service.revoke(db, mac, ip)

    async def get_portal_config(self) -> Dict:
        return {
            "payment_url": "https://t.me/kda_v1_bot",
            "quiz_rules": "請回答問題以解除網速限制。",
            "maintenance_mode": False
        }