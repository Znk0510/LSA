import json
import re
from typing import Dict
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_fixed

class AIQuizService:
    def __init__(self, model: str = "gemma2:2b"):
        # 設定連線到本地 Ollama
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"  # 必填但隨意
        )
        self.model = model

    def _extract_json(self, text: str) -> str:
        """
        尋找字串中第一個 '{' 和最後一個 '}' 來提取內容
        """
        try:
            # 1. 移除 Markdown code blocks (如果有的話)
            if "```" in text:
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
                if match:
                    return match.group(1)

            # 2. 如果沒有 code block，嘗試直接尋找 JSON 物件結構
            # 尋找最外層的 {}
            start_idx = text.find('{')
            end_idx = text.rfind('}')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                return text[start_idx : end_idx + 1]
            
            # 如果都找不到，回傳原始文字賭賭看
            return text.strip()
        except:
            return text

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def generate_quiz(self, context_text: str = "") -> Dict:
        """
        生成測驗 (支援 RAG)
        """
        prompt = f"""
        你是一位嚴格的考官。請閱讀以下【教材內容】，並出一道單選題。
        
        【教材內容開始】
        {context_text}
        【教材內容結束】

        要求：
        1. 題目必須與上述內容相關。
        2. 使用繁體中文。
        3. 嚴格遵守 JSON 格式回傳，不要有任何額外的對話或文字。
        4. "correct_index" 必須是 0, 1, 2, 或 3 (分別代表選項 A, B, C, D)。

        範例輸出格式：
        {{
            "question": "SSH 預設的 Port 是多少？",
            "options": ["21", "22", "80", "443"],
            "correct_index": 1,
            "explanation": "因為 SSH 協定標準定義在 Port 22。"
        }}
        """
        
        if not context_text:
            prompt = "請出一個關於 Linux 網路管理的單選題，繁體中文，回傳 JSON 格式 (同上範例)。"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一個只回傳 JSON 的 API。不要說廢話。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5, # 降低隨機性，讓格式更穩定
                max_tokens=300
            )
            
            raw_content = response.choices[0].message.content
            # print(f"[AI Raw] {raw_content}") # Debug 用，如果出錯可以打開看 AI 回了什麼
            
            # 清洗並解析
            clean_content = self._extract_json(raw_content)
            quiz_data = json.loads(clean_content)

            # 驗證必要欄位
            if "correct_index" not in quiz_data or "options" not in quiz_data:
                raise ValueError("AI 回傳格式缺少關鍵欄位")

            return quiz_data

        except Exception as e:
            print(f"[AI Error] Generation Failed: {e}")
            raise e # 拋出讓 retry 機制重試

    async def get_fallback_quiz(self) -> Dict:
        """
        備案：如果 AI 真的掛了或是格式爛掉，回傳這題
        """
        return {
            "id": "fallback",
            "question": "【系統備用題】Ping 指令使用什麼協定？",
            "options": [
                "TCP",
                "UDP",
                "ICMP",
                "HTTP"
            ],
            "correct_index": 2,
            "explanation": "Ping 使用 ICMP (Internet Control Message Protocol) 來測試連線。"
        }

