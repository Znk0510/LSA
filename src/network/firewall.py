import asyncio
from abc import ABC, abstractmethod
from typing import Set

# --- 1. 抽象介面 (維持不變，這是您跟組員的契約) ---
class FirewallControllerInterface(ABC):
    @abstractmethod
    async def allow_device(self, mac: str) -> None:
        """允許裝置上網"""
        pass
    
    @abstractmethod
    async def deny_device(self, mac: str) -> None:
        """阻擋裝置上網"""
        pass

# --- 2. Shell Script 實作 (您的轉接頭) ---
class ShellScriptFirewallController(FirewallControllerInterface):
    """
    透過 subprocess 呼叫外部 Shell Scripts
    假設組員提供了兩個腳本：
    1. /usr/local/bin/allow_user.sh <MAC>
    2. /usr/local/bin/block_user.sh <MAC>
    """
    def __init__(self, script_path: str = "/usr/local/bin"):
        self.script_path = script_path

    async def _run_script(self, script_name: str, mac: str):
        """執行 Shell Script 的通用函式"""
        full_path = f"{self.script_path}/{script_name}"
        
        # 使用 asyncio 執行 subprocess，避免卡住主執行緒
        process = await asyncio.create_subprocess_exec(
            full_path, mac,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"[Firewall Error] Script: {script_name}, MAC: {mac}")
            print(f"Stderr: {stderr.decode()}")
            # 在生產環境這裡應該寫 Log 或拋出 Exception
        else:
            print(f"[Firewall] Executed {script_name} for {mac}")

    async def allow_device(self, mac: str) -> None:
        # 呼叫組員的 allow 腳本
        await self._run_script("restore.sh", mac)

    # async def deny_device(self, mac: str) -> None:
    #     # 呼叫組員的 block 腳本
    #     await self._run_script("block_game.sh", mac)

# --- 3. Mock 實作 (測試用) ---
class MockFirewallController(FirewallControllerInterface):
    def __init__(self):
        self.allowed = set()
    
    async def allow_device(self, mac: str):
        print(f"[MockFirewall] ALLOW {mac}")
        self.allowed.add(mac)
        
    async def deny_device(self, mac: str):
        print(f"[MockFirewall] DENY {mac}")
        if mac in self.allowed:
            self.allowed.remove(mac)
    def is_allowed(self, mac: str) -> bool:
        return mac in self.allowed
