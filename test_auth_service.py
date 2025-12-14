import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.database import Base
from src.db.repositories import AuthorizationLogRepository
from src.network.firewall import MockFirewallController
from src.core.auth_service import AuthorizationService

# --- 設定測試用 DB (SQLite Memory) ---
engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def auth_service():
    repo = AuthorizationLogRepository()
    firewall = MockFirewallController()
    return AuthorizationService(repo, firewall), firewall

@pytest.mark.asyncio
async def test_authorization_triggers_firewall(db_session, auth_service):
    """
    Task 4.3 / Property 6: 授權觸發防火牆通知
    驗證呼叫 authorize() 後，MockFirewall 確實收到 allow 指令
    """
    service, firewall = auth_service
    mac = "11:11:11:11:11:11"

    # 1. 執行授權
    await service.authorize(db_session, mac)

    # 2. 驗證資料庫有紀錄
    assert await service.is_authorized(db_session, mac) is True

    # 3. 驗證防火牆有收到通知
    assert firewall.is_allowed(mac) is True

@pytest.mark.asyncio
async def test_revoke_triggers_firewall(db_session, auth_service):
    """
    驗證撤銷流程
    """
    service, firewall = auth_service
    mac = "22:22:22:22:22:22"

    await service.authorize(db_session, mac)
    assert firewall.is_allowed(mac) is True

    await service.revoke(db_session, mac)
    
    assert await service.is_authorized(db_session, mac) is False
    assert firewall.is_allowed(mac) is False

@pytest.mark.asyncio
async def test_state_recovery(db_session):
    """
    Task 4.5 / Property 9: 系統重啟後授權狀態恢復
    """
    repo = AuthorizationLogRepository()
    
    # 1. 模擬系統關機前：資料庫有一些授權紀錄
    mac_active = "AA:AA:AA:AA:AA:AA"
    mac_revoked = "BB:BB:BB:BB:BB:BB"
    
    repo.create_log(db_session, mac_active, "authorized")
    repo.create_log(db_session, mac_revoked, "authorized")
    repo.create_log(db_session, mac_revoked, "revoked") # 這台最後被撤銷了

    # 2. 系統重啟：建立全新的 Service 和 Firewall
    new_firewall = MockFirewallController()
    new_service = AuthorizationService(repo, new_firewall)

    # 3. 執行恢復
    count = await new_service.restore_state(db_session)

    # 4. 驗證
    # mac_active 應該被恢復 (在防火牆白名單內)
    assert new_firewall.is_allowed(mac_active) is True
    # mac_revoked 不應該被恢復
    assert new_firewall.is_allowed(mac_revoked) is False
    # 恢復數量應為 1
    assert count == 1
