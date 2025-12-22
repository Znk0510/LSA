#!/bin/bash
#檔案: allow_telegram.sh
#用途: 在封鎖 HTTPS 之前，先放行 Telegram 的伺服器 IP (Walled Garden)
#Telegram 的 IP網段 (CIDR)
#來源: Telegram 官方 ASN (AS62041, AS59930, AS44905)
TELEGRAM_IPS=(
    "91.108.4.0/22"
    "91.108.8.0/22"
    "91.108.12.0/22"
    "91.108.16.0/22"
    "91.108.56.0/22"
    "149.154.160.0/20"
    "149.154.164.0/22"
    "149.154.168.0/22"
    "149.154.172.0/22"
)

#清除舊的 Telegram 規則 (避免重複執行導致規則堆積)
#這裡比較難精準刪除，簡單起見我們假設你是重新設定防火牆
#如果要嚴謹，這裡應該要有刪除邏輯，但 Demo 時我們先直接加
echo "正在設定 Telegram 白名單 (Walled Garden)..."

for IP in "${TELEGRAM_IPS[@]}"; do
    # -I FORWARD 1: 插在 FORWARD 鏈的第一條 (最優先)
    # 允許 區域網路 -> Telegram 的流量
    sudo iptables -I FORWARD 1 -s 192.168.10.0/24 -d "$IP" -j ACCEPT

#允許 Telegram -> 區域網路 的流量 (回傳封包)
    sudo iptables -I FORWARD 1 -d 192.168.10.0/24 -s "$IP" -j ACCEPT
done

echo "✅ Telegram IP 已放行！現在學生沒登入也能連上 Telegram 了。"
