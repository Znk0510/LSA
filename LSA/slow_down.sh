#!/bin/bash
# 檔案名稱: slow_down.sh
# 用途: 將特定 IP 加入慢速懲罰通道

TARGET_IP=$1
INTERFACE=$2
LIMIT="256kbit"

if [ -z "$TARGET_IP" ] || [ -z "$INTERFACE" ]; then
    echo "用法: sudo ./slow_down.sh <IP> <介面>"
    exit 1
fi

# --- 階段一：檢查並初始化 ---
# 檢查該網卡是否已經有 htb 規則
if ! tc qdisc show dev $INTERFACE | grep -q "htb"; then
    echo "初始化網卡 $INTERFACE 的流量控制架構..."
    
    # 1. 建立根佇列
    sudo tc qdisc add dev $INTERFACE root handle 1: htb default 10
    
    # 2. 建立「正常高速通道」 (class 1:10) - 不限速 (依網卡極限)
    sudo tc class add dev $INTERFACE parent 1: classid 1:10 htb rate 100mbit
    
    # 3. 建立「懲罰慢速通道」 (class 1:20) - 限速 256kbit
    sudo tc class add dev $INTERFACE parent 1: classid 1:20 htb rate $LIMIT ceil $LIMIT
fi

# 2. 提取 IP 的最後一碼作為唯一 ID (Priority)
#    例如 192.168.56.100 -> ID = 100
ID=$(echo $TARGET_IP | awk -F. '{print $4}')

if [ -z "$ID" ]; then
    echo "錯誤: 無法解析 IP ID"
    exit 1
fi

echo "正在將 $TARGET_IP (ID: $ID) 加入懲罰通道..."

# 3. 刪除舊規則 (如果有)，避免重複疊加
#    我們先試著刪除這個 ID 的舊規則，不管有沒有成功都繼續
sudo tc filter del dev $INTERFACE protocol ip parent 1:0 prio $ID 2>/dev/null

# 4. 新增規則：指定 prio 為該 IP 的 ID
sudo tc filter add dev $INTERFACE protocol ip parent 1:0 prio $ID u32 match ip dst $TARGET_IP flowid 1:20

echo "已對 $TARGET_IP (規則ID: $ID) 執行降速。"
