### 專案架構概覽
- 後端：Python FastAPI
    - 負責 API 處理、資料庫存取、AI 題目生成、ARP 網路掃描
- 前端：HTML5 + Vue.js 3 (CDN) + TailwindCSS
    - 老師端 (teacher.html)：儀表板，查看學生違規狀況、上傳 PDF 教材
    - 學生端 (index.html)：轉盤命運遊戲、AI 測驗介面、支付介面
- 系統服務：
    - Nginx：反向代理 server，負責 Captive Portal 的重導向與靜態檔案服務
    - Ollama (AI)：本地運行的 LLM (Gemma 2:2b)，負責讀取教材並出題
    - PostgreSQL：儲存使用者、學生狀態、連線紀錄與測驗結果
    - Scapy：進行 ARP 掃描以偵測區網內的裝置

### 功能清單
我目前已經完成了以下模組：
- 網路攔截與認證 (Captive Portal)：
    - 透過 Nginx攔截未授權流量，將學生導向 /portal
    - 實作「命運轉盤」，隨機決定學生需要「回答問題」還是「支付罰款」
- AI 出題：
    - 老師上傳 PDF 講義，後端自動解析
    - 整合 Ollama (Gemma 2)，根據講義內容即時生成單選題
- 即時監控儀表板：
    - 自動掃描區網 (ARP Scan) 辨識上線裝置
    - 顯示違規次數排行榜（不認真排行榜）
- 系統整合：
    - 資料庫 ORM 設計 (SQLAlchemy)
    - 模擬防火牆控制 (MockFirewall)，可隨時切換為真實 Shell Script

###  系統需求
參考 `requirements.txt`

### 資料庫設定
```bash
# 進入 psql
sudo -u postgres psql

# 建立使用者與資料庫 (密碼請對應 src/db/database.py 的設定)
CREATE USER lsa WITH PASSWORD 'lsapasswd';
CREATE DATABASE student_guard OWNER lsa;
\q
```
### AI 模型設定 (Ollama)
```bash
# 到瀏覽器開啟 
https://github.com/ollama/ollama/releases

# 找到 v0.13.3，下載
ollama-linux-amd64.tgz

# 下載好了
cd ~/Downloads

# 解壓縮並安裝
sudo tar -C /usr -xzf ollama-linux-amd64.tgz

# 建立 Ollama 使用者
sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
sudo usermod -a -G ollama $(whoami)

# 設定開機服務
sudo vim /etc/systemd/system/ollama.service
# ExecStart 的路徑改成 /usr/bin/ollama

# 啟動服務
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl status ollama

# 確認 ollama version is 0.13.3
ollama --version

# 下載模型 
ollama pull gemma2:2b
```
### 專案安裝
```bash
# Clone
git clone <repository_url>
cd smart-classroom

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝依賴
pip install -r requirements.txt
```
### Nginx 設定
將 Nginx config 部署到系統：
1. 複製靜態檔案：將前端檔案移至 Nginx 預設讀取路徑
```BASH
sudo mkdir -p /var/www/portal
# 假設你在專案根目錄
sudo cp -r src/gateway/portal/* /var/www/portal/
```
2. 開放權限讓 Nginx 可以讀取專案靜態檔
```bash
# 讓其他人(包含 Nginx) 可以進入家目錄
# 給 /home/[user] 目錄 execute 權限 (x)，允許進入但不允許列出檔案列表
# [user] 要換成自己
chmod o+x /home/znk

# 確保專案路徑沿途都有權限
chmod o+x /home/[user]/smart-classroom
chmod o+x /home/[user]/smart-classroom/src
chmod o+x /home/[user]/smart-classroom/src/gateway
chmod o+x /home/[user]/smart-classroom/src/gateway/portal

# 確保 index.html 檔案可讀
chmod o+r /home/[user]/smart-classroom/src/gateway/portal/index.html
```
### 啟動方式
1. 啟動後端 API
在專案根目錄 (`smart-classroom/`) 執行：
```bash
# 啟動 FastAPI，預設 Port 為 8000
# 使用 sudo 才能執行 ARP 掃描 (Scapy 需要 root 權限)
sudo ./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
>[!Warning]
>`main.py` 中的 WIFI_INTERFACE 和 TARGET_NETWORK 變數依你的實際網卡名稱修改

>`./venv/bin/uvicorn`：直接指定要跑「虛擬環境資料夾」裡面的 uvicorn
>- 這樣它會自動知道要用虛擬環境裡的 Python 和套件，而不會跑去用系統的
>
>`src.main:app`：因為 `main.py` 在 src 資料夾內，要告訴它路徑
`--host 0.0.0.0`：這樣做 Captive Portal 才能被連上熱點的手機存取

2. 瀏覽器測試
- 老師後台: 開啟瀏覽器輸入 http://localhost/teacher
    - 預設無帳號，先註冊建立帳號
- 學生模擬:
    - 開啟 http://localhost/internet (會被重導向至 Portal)
    - 或者直接輸入 http://localhost/portal 體驗被鎖定的畫面
### API 說明
主要 API Endpoints
| 分類 (Category) | Method | Endpoint | 說明 (Description) |
| :--- | :--- | :--- | :--- |
| **Auth** | `POST` | `/api/login` | 老師登入 (回傳 Token) |
| **Auth** | `POST` | `/api/register` | 老師註冊 |
| **Dashboard** | `GET` | `/api/students` | 取得所有學生狀態 (含違規次數) |
| **File** | `POST` | `/api/admin/upload` | 上傳 PDF 教材 (自動 RAG 處理) |
| **Quiz** | `GET` | `/api/quiz` | AI 生成題目 |
| **Quiz** | `POST` | `/api/quiz/answer` | 提交答案，判斷是否解鎖網路 |
| **Portal** | `GET` | `/api/auth/status` | 前端輪詢用，檢查是否已授權 |

---
### 檔案結構
```text
smart-classroom/
├── config/                  # 設定檔
│   └── nginx/               # Nginx 設定
├── data/uploads/            # PDF 教材存放區
├── src/
│   ├── ai/                  # AI 模組
│   │   ├── pdf_loader.py    # PDF 解析與切塊
│   │   └── service.py       # Ollama 串接與 Prompt Engineering
│   ├── core/                # 核心邏輯
│   │   └── auth_service.py  # 授權狀態管理
│   ├── db/                  # 資料庫層
│   │   ├── database.py      # 連線設定
│   │   ├── models.py        # SQLAlchemy 模型定義
│   │   └── repositories.py  # 資料存取層 (CRUD)
│   ├── gateway/
│   │   ├── portal/              # 前端靜態檔案 (HTML/CSS/JS)
│   │   │   ├── index.html       # 勸導介面
│   │   │   ├── teacher.html     # 老師後台
│   │   │   └── js/portal.js     # 勸導介面
│   │   │   └── css/style.css    # 勸導介面
│   │   └── service.py       # Captive Portal 邏輯 (API 與 Core 的橋樑)
│   ├── network/             # 網路控制層
│   │   ├── firewall.py      # 防火牆控制器 (Mock/Shell)
│   │   ├── scanner.py       # ARP 掃描器
│   │   └── registry.py      # 學生裝置註冊邏輯
│   └── main.py              # FastAPI 入口點
└── requirements.txt         # Python 依賴清單