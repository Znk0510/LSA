# src/network/registry.py

from typing import List, Dict
from sqlalchemy.orm import Session
from src.db.models import ARPScanResult, StudentRecord 
from src.db.repositories import StudentRepository, ConnectionLogRepository

class StudentRegistryService:
    def __init__(self, db: Session):
        self.db = db
        self.student_repo = StudentRepository() # Repository 不需要傳 db 進入 init
        self.log_repo = ConnectionLogRepository()

    def process_scan_results(self, scan_results: List[ARPScanResult]) -> Dict[str, int]:
        """
        比對掃描結果與學生名單
        """
        # 1. 取得所有註冊學生 (修正方法名稱)
        all_students = self.student_repo.get_all_students(self.db)
        
        # 建立 MAC -> 學生物件 的快速查找表
        # 注意: 這裡假設 db model 屬性是 mac_address
        mac_map = {s.mac_address.lower(): s for s in all_students}
        
        present_count = 0
        unknown_count = 0

        # 2. 遍歷掃描到的裝置
        for device in scan_results:
            mac_key = device.mac.lower()
            student = mac_map.get(mac_key)
            
            if student:
                # A. 是註冊學生
                present_count += 1
                # 寫入連線紀錄 (修正方法名稱與參數)
                self.log_repo.create_log(
                    db=self.db,
                    mac_address=device.mac,
                    ip_address=device.ip,
                    status="connected",
                    student_id=student.student_id
                )
            else:
                # B. 是陌生裝置
                unknown_count += 1
                self.log_repo.create_log(
                    db=self.db,
                    mac_address=device.mac,
                    ip_address=device.ip,
                    status="unknown",
                    student_id=None
                )

        return {
            "total_scanned": len(scan_results),
            "students_online": present_count,
            "unknown_devices": unknown_count
        }
