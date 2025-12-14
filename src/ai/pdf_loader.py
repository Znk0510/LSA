import pdfplumber
import random
import os
import glob

class PDFLoader:
    def __init__(self, storage_dir=None):
        # 取得專案根目錄的絕對路徑
        # 無論在哪裡執行 uvicorn，檔案都會存在 /home/znk/smart-classroom/data/uploads
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.storage_dir = os.path.join(base_dir, "data", "uploads")
        
        # 確保目錄存在
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # 知識庫
        self.knowledge_base = []
        print(f"[PDFLoader] 檔案儲存路徑設定為: {self.storage_dir}")

        # 啟動時自動載入既有的 PDF
        self.reload_existing_files()

    def reload_existing_files(self):
        """重新載入資料夾內所有的 PDF"""
        pdf_files = glob.glob(os.path.join(self.storage_dir, "*.pdf"))
        if not pdf_files:
            print("[PDFLoader] 資料夾為空，無預載教材。")
            return

        print(f"[PDFLoader] 發現 {len(pdf_files)} 個歷史教材，正在重新建立知識庫...")
        for pdf_path in pdf_files:
            try:
                self._parse_and_store(pdf_path)
            except Exception as e:
                print(f"[PDFLoader] 載入 {pdf_path} 失敗: {e}")
        
        print(f"[PDFLoader] 重建完成，目前知識庫有 {len(self.knowledge_base)} 個片段。")

    def save_and_extract(self, file_content: bytes, filename: str) -> bool:
        file_path = os.path.join(self.storage_dir, filename)
        with open(file_path, "wb") as f:
            f.write(file_content)
        return self._parse_and_store(file_path)

    def _parse_and_store(self, file_path: str) -> bool:
        """內部方法：解析單一 PDF 並存入記憶體"""
        try:
            text_content = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: text_content += text + "\n"

            if not text_content: return False

            chunk_size = 1000
            for i in range(0, len(text_content), chunk_size):
                chunk = text_content[i : i + chunk_size]
                if len(chunk) > 50:
                    self.knowledge_base.append(chunk)
            return True
        except:
            return False

    def get_random_context(self) -> str:
        """
        隨機取得一段教材內容
        """
        if not self.knowledge_base:
            return ""
        return random.choice(self.knowledge_base)

# 全域實例
pdf_loader = PDFLoader()
