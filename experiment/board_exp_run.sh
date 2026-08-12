#!/bin/bash
# 板端实验运行器: 起 server -> 跑 rk3588-vlm(相机) N秒 + 后台帧采样 -> 杀 server
# 用法: board_exp_run.sh <model> <mmproj> <width> <height> <seconds> <question> <logfile> [sample_frames] [temp] [gst_extra]
#   temp:     采样温度 (0.0~2.0, 实验7; 省略=不传, 用 rk3588-vlm 默认 0.1)
#   gst_extra: 附加 GStreamer 元素串 (实验2/3: 模糊/缩放/裁剪; 省略=无滤镜)
#   说明: 新版 rk3588-vlm (v0.2, 含 --temp/--gst-extra) 才会生效; 旧版二进制会忽略? 否——旧版会报"未知参数"退出, 推板 v0.2 后再跑
export LD_LIBRARY_PATH=/userdata/llama/bin
MODEL="$1"; MMPROJ="$2"; W="$3"; H="$4"; SECS="$5"; Q="$6"; LOG="$7"; SAMPLE="${8:-0}"
TEMP="$9"; GST="${10}"
M_DIR=/userdata/llama/models
TAG=$(basename $LOG .log)
EXTRA_ARGS=()
if [ -n "$TEMP" ]; then EXTRA_ARGS+=(--temp "$TEMP"); fi
if [ -n "$GST" ];  then EXTRA_ARGS+=(--gst-extra "$GST"); fi
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
  --question "$Q" "${EXTRA_ARGS[@]}" > "$LOG" 2>&1
RC=$?
sleep 1
if [ "$SAMPLE" = "1" ]; then kill $SAMPLER 2>/dev/null; fi
pkill -f llama-server 2>/dev/null
echo "rk3588-vlm exit: $RC, log: $LOG, lines: $(wc -l < $LOG), frames: $(ls /tmp/frames_$TAG 2>/dev/null | wc -l)"
