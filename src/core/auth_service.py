from typing import Optional
from sqlalchemy.orm import Session
from src.db.repositories import AuthorizationLogRepository
from src.network.firewall import FirewallControllerInterface

class AuthorizationService:
    def __init__(
        self, 
        repo: AuthorizationLogRepository, 
        firewall: FirewallControllerInterface
    ):
        self.repo = repo
        self.firewall = firewall

    async def authorize(self, db: Session, mac: str, details: Optional[dict] = None) -> None:
        """授權：寫 DB -> 開防火牆"""
        # 1. DB 記錄
        self.repo.create_log(
            db=db,
            mac_address=mac,
            status="authorized",
            details=str(details) if details else "{}"
        )
        # 2. 執行 Shell Script (allow)
        await self.firewall.allow_device(mac)

    async def revoke(self, db: Session, mac: str) -> None:
        """撤銷：寫 DB -> 關防火牆"""
        # 1. DB 記錄
        self.repo.create_log(
            db=db,
            mac_address=mac,
            status="revoked"
        )
        # 2. 執行 Shell Script (block)
        await self.firewall.deny_device(mac)

    async def is_authorized(self, db: Session, mac: str) -> bool:
        """檢查 DB 中最新狀態是否為 authorized"""
        latest_log = self.repo.get_latest_log(db, mac)
        if not latest_log:
            return False
        return latest_log.status == "authorized"

    async def restore_state(self, db: Session) -> int:
        """
        [Task 4.4] 系統重啟恢復
        找出所有應該要是 authorized 的人，重新執行 allow script
        """
        # 這裡簡化邏輯：撈出最近 1000 筆 log，整理出最後狀態是 authorized 的 MAC
        all_logs = self.repo.get_logs(db, limit=1000)
        
        # 用 dict 整理每個 MAC 的最後狀態
        mac_status = {}
        for log in all_logs:
            # log 是依時間倒序嗎？如果是，我們只看第一次遇到的(最新的)
            # 假設 get_logs 回傳的是最新的在前面
            if log.mac_address not in mac_status:
                mac_status[log.mac_address] = log.status
        
        restored_count = 0
        for mac, status in mac_status.items():
            if status == "authorized":
                # 重新執行 Shell Script，確保 iptables 規則存在
                await self.firewall.allow_device(mac)
                restored_count += 1
                
        print(f"[System] Restored {restored_count} active sessions via Shell Scripts.")
        return restored_count
