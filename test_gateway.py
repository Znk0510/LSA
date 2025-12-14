import pytest
from httpx import AsyncClient, ASGITransport  # 新增匯入 ASGITransport
from src.main import app
from src.gateway.service import portal_service

@pytest.mark.asyncio
async def test_full_auth_lifecycle():
    """
    測試完整的授權生命週期：
    未授權 -> 授權 -> 檢查狀態 -> 撤銷 -> 檢查狀態
    """
    mac = "AA:BB:CC:DD:EE:FF"
    
    # --- 修正點：使用 ASGITransport 來連接 FastAPI ---
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. 初始狀態應為 False
        # 確保測試前環境乾淨
        await portal_service.revoke_device(mac) 
        
        resp = await ac.get(f"/api/auth/status?mac={mac}")
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False

        # 2. 執行授權 (Task 3.5 / 4.1)
        await portal_service.authorize_device(mac)
        
        # 3. 檢查是否變為 True
        resp = await ac.get(f"/api/auth/status?mac={mac}")
        assert resp.json()["authorized"] is True

        # 4. [Task 5.7] 執行撤銷
        await portal_service.revoke_device(mac)

        # 5. [Task 5.8] 驗證撤銷後狀態回歸 False
        resp = await ac.get(f"/api/auth/status?mac={mac}")
        assert resp.json()["authorized"] is False
