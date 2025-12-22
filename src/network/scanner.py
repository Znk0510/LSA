# src/network/scanner.py
import logging
import scapy.config
from scapy.all import ARP, Ether, srp
from typing import List
from datetime import datetime

# 引用你的 Pydantic 模型
from src.db.models import ARPScanResult

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ARPScanner:
    def __init__(self, interface: str = "enp0s3"): 
        """
        初始化掃描器
        :param interface: 網路介面名稱 (用 ip addr 確認你的介面，要是學生連上來的網卡)
        """
        self.interface = interface

    def scan(self, ip_range: str = "192.168.10.0/24") -> List[ARPScanResult]:
        """
        執行 ARP 掃描
        :param ip_range: 要掃描的網段 (CIDR 格式)
        :return: 掃描結果列表
        """
        logger.info(f"開始掃描網段: {ip_range} 使用介面: {self.interface}")
        
        try:
            # 1. 建立 ARP 請求封包 (廣播問這網段的 IP 是誰的)
            # Ether(dst="ff:ff:ff:ff:ff:ff") 代表廣播給所有人
            packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip_range)
            
            # 2. 發送封包並等待回應
            # srp = Send and Receive Packet at layer 2
            # timeout=2: 等待 2 秒
            # verbose=False: 不要在終端機印出一堆 scapy 的訊息
            answered, unanswered = srp(packet, timeout=2, iface=self.interface, verbose=False)
            
            results = []
            for sent, received in answered:
                # received.psrc = 發送者的 IP (Protocol Source)
                # received.hwsrc = 發送者的 MAC (Hardware Source)
                scan_result = ARPScanResult(
                    ip=received.psrc,
                    mac=received.hwsrc,
                    timestamp=datetime.now()
                )
                results.append(scan_result)
            
            logger.info(f"掃描完成，發現 {len(results)} 個裝置")
            return results

        except PermissionError:
            logger.error("權限不足！請使用 sudo 執行此程式 (ARP 掃描需要 root 權限)")
            return []
        except Exception as e:
            logger.error(f"掃描發生錯誤: {e}")
            return []

# --- 簡單測試區 (直接執行此檔案時會跑) ---
if __name__ == "__main__":
    # 這裡的網段請改成你家裡/學校的真實網段，例如 192.168.0.0/24 或 10.0.2.0/24
    # 如果不知道，可以在終端機打 `ip addr` 查看
    import sys
    
    # 預設測試網段
    target_ip = "192.168.10.0/24" 
    if len(sys.argv) > 1:
        target_ip = sys.argv[1]

    scanner = ARPScanner() # 預設介面 enp0s3
    print(f"正在掃描 {target_ip} ... (請確保你有用 sudo 執行)")
    devices = scanner.scan(target_ip)
    
    print("\n====== 掃描結果 ======")
    print(f"{'IP Address':<15} | {'MAC Address':<17}")
    print("-" * 35)
    for device in devices:
        print(f"{device.ip:<15} | {device.mac:<17}")
