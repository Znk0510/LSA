#!/bin/bash
# 檔案名稱: block_game.sh
# 用法: sudo ./block_game.sh <違規學生的IP>

TARGET_IP=$1

if [ -z "$TARGET_IP" ]; then
    echo "錯誤: 請輸入目標 IP"
    exit 1
fi

echo "正在對 IP: $TARGET_IP 執行遊戲阻斷 (封鎖 UDP)..."


sudo iptables -I FORWARD -s $TARGET_IP -p udp -j DROP

echo "IP $TARGET_IP 已被阻斷遊戲連線。"
