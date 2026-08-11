#!/bin/bash
# 板端实验运行器: 起 server -> 跑 rk3588-vlm(相机) N秒 + 后台帧采样 -> 杀 server
# 用法: board_exp_run.sh <model> <mmproj> <width> <height> <seconds> <question> <logfile> [sample_frames]
export LD_LIBRARY_PATH=/userdata/llama/bin
MODEL="$1"; MMPROJ="$2"; W="$3"; H="$4"; SECS="$5"; Q="$6"; LOG="$7"; SAMPLE="${8:-0}"
M_DIR=/userdata/llama/models
TAG=$(basename $LOG .log)
pkill -f llama-server 2>/dev/null
sleep 1
/userdata/llama/bin/llama-server -m $M_DIR/$MODEL --mmproj $M_DIR/$MMPROJ --port 8088 -t 8 >/tmp/server.log 2>&1 &
SRV=$!
sleep 8
if [ "$SAMPLE" = "1" ]; then
  rm -rf /tmp/frames_$TAG; mkdir -p /tmp/frames_$TAG
  ( i=0; while [ -e /proc/$SRV ]; do
      if [ -f /dev/shm/frame.jpg ]; then
        cp /dev/shm/frame.jpg /tmp/frames_$TAG/f_$(printf %04d $i).jpg 2>/dev/null
        i=$((i+1))
      fi
      sleep 2
    done ) &
  SAMPLER=$!
fi
timeout $SECS /userdata/llama/bin/rk3588-vlm \
  --model $M_DIR/$MODEL --mmproj $M_DIR/$MMPROJ \
  --width $W --height $H --interval 1 \
  --question "$Q" > "$LOG" 2>&1
RC=$?
sleep 1
if [ "$SAMPLE" = "1" ]; then kill $SAMPLER 2>/dev/null; fi
pkill -f llama-server 2>/dev/null
echo "rk3588-vlm exit: $RC, log: $LOG, lines: $(wc -l < $LOG), frames: $(ls /tmp/frames_$TAG 2>/dev/null | wc -l)"
