#!/bin/bash
# 板端: 起 llama-server → 跑 HTTP 复现测试 → 杀 server (单会话)
# 用法: board_server_test.sh <model> <mmproj> <rounds>
export LD_LIBRARY_PATH=/userdata/llama/bin
MODEL="$1"; MMPROJ="$2"; ROUNDS="${3:-10}"
pkill -f llama-server 2>/dev/null
sleep 1
/userdata/llama/bin/llama-server -m /userdata/llama/models/$MODEL \
  --mmproj /userdata/llama/models/$MMPROJ --port 8088 -t 8 \
  >/tmp/server.log 2>&1 &
SRV=$!
sleep 8
python3 /tmp/http_test.py "$ROUNDS"
kill $SRV 2>/dev/null
wait $SRV 2>/dev/null
