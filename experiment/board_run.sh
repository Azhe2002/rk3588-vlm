#!/bin/bash
# 板端单轮推理: 输出 "耗时\t输出" 一行
# 用法: board_run.sh <model_dir> <model> <mmproj> <image> <prompt> <seed> <temp> [sysprompt]
export LD_LIBRARY_PATH=/userdata/llama/bin
M_DIR="$1"; MODEL="$2"; MMPROJ="$3"; IMG="$4"; PROMPT="$5"; SEED="$6"; TEMP="$7"; SYS="${8:-}"
T0=$(date +%s%N)
OUT=$(/userdata/llama/bin/llama-mtmd-cli -m "$M_DIR/$MODEL" --mmproj "$M_DIR/$MMPROJ" \
  --image "$IMG" -p "$PROMPT" -n 32 --temp "$TEMP" --seed "$SEED" -t 8 -sys "$SYS" 2>/dev/null | grep -v '^0\.' | tr '\n' ' ')
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo -e "${MS}\t${OUT}" | sed 's/ *$//'
