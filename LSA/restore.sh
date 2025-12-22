#!/bin/bash
# 檔案名稱: restore.sh
# 用途: 解除特定使用者的懲罰 (不影響其他人)

TARGET_IP=$1
INTERFACE=$2

if [ -z "$TARGET_IP" ] || [ -z "$INTERFACE" ]; then
    echo "用法: sudo ./restore.sh <IP> <介面>"
    exit 1
fi

# 1. 提取 IP 的最後一碼作為唯一 ID
ID=$(echo $TARGET_IP | awk -F. '{print $4}')

echo "正在解除 $TARGET_IP (ID: $ID) 的限制..."

# --- 解除遊戲阻斷 (IPTables) ---
# iptables 本來就是針對 IP 的，所以不會誤殺別人
sudo iptables -D FORWARD -s $TARGET_IP -p udp -j DROP 2>/dev/null
sudo iptables -D OUTPUT -d $TARGET_IP -p udp -j DROP 2>/dev/null
sudo iptables -D OUTPUT -d $TARGET_IP -j DROP 2>/dev/null


# --- 解除網速限制 (TC - 精準移除法) ---
# 只刪除優先權為 $ID 的那個過濾器
sudo tc filter del dev $INTERFACE protocol ip parent 1:0 prio $ID 2>/dev/null

if [ $? -eq 0 ]; then
    echo "已移除 TC 規則 ID: $ID"
else
    echo "找不到該 IP 的限速規則 (可能已經解除過了)"
fi

echo "$TARGET_IP 已恢復自由，其他受罰者不受影響。"
