from pydantic import BaseModel
from typing import List, Type
from datetime import datetime
import json

# 引用定義的 Pydantic 模型
from src.core.models import Student, AuthorizationRecord

class SystemBackup(BaseModel):
    """
    系統備份的資料結構
    包含版本資訊、匯出時間、以及核心資料列表
    """
    version: str = "1.0"
    exported_at: datetime = datetime.now()
    students: List[Student] = []
    authorizations: List[AuthorizationRecord] = []
    # 可以在此擴充其他需要備份的資料

class SerializationService:
    def serialize(self, backup_data: SystemBackup) -> str:
        """
        將備份物件轉換為 JSON 字串
        """
        return backup_data.model_dump_json(indent=4)

    def deserialize(self, json_str: str) -> SystemBackup:
        """
        將 JSON 字串還原為備份物件
        """
        return SystemBackup.model_validate_json(json_str)

    def save_to_file(self, backup_data: SystemBackup, filepath: str):
        """便利方法：直接存檔"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.serialize(backup_data))

    def load_from_file(self, filepath: str) -> SystemBackup:
        """便利方法：直接讀檔"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return self.deserialize(content)
