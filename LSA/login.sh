#!/bin/bash
# 檔案: login.sh
# 用途: 登入使用者 (放行網路)
# 用法: sudo ./login.sh <IP>

TARGET_IP=$1

if [ -z "$TARGET_IP" ]; then
    echo "用法: sudo ./login.sh <IP>"
    exit 1
fi

echo "正在開通使用者 $TARGET_IP 的網路權限..."

# 1. 在 NAT 表 PREROUTING 鏈的最前面插入 ACCEPT (讓它不再被轉去登入頁)
sudo iptables -t nat -I PREROUTING 1 -s $TARGET_IP -j ACCEPT

# 2. 在 FILTER 表 FORWARD 鏈插入 ACCEPT (允許它連外網)
sudo iptables -I FORWARD 1 -s $TARGET_IP -j ACCEPT

echo "使用者 $TARGET_IP 登入成功！"
