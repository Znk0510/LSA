#!/bin/bash

TARGET_IP=$1

if [ -z "$TARGET_IP" ]; then
    echo "用法: sudo ./logout.sh <IP>"
    exit 1
fi

echo "正在移除使用者 $TARGET_IP 的網路權限..."

# 1. 從 NAT 表 PREROUTING 鏈刪除該規則 (恢復轉址到登入頁)
# 使用 -D (Delete) 替代 -I (Insert)
sudo iptables -t nat -D PREROUTING -s $TARGET_IP -j ACCEPT

# 2. 從 FILTER 表 FORWARD 鏈刪除該規則 (禁止連外網)
# 使用 -D (Delete) 替代 -I (Insert)
sudo iptables -D FORWARD -s $TARGET_IP -j ACCEPT

echo "使用者 $TARGET_IP 已登出 (網路權限已移除)！"