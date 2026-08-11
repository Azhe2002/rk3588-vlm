#!/bin/bash
# ============================================================
# rk3588-vlm 交叉编译 (x86_64 → aarch64/arm64)
# 环境: Docker debian:bullseye + gcc-aarch64-linux-gnu
# 用法: bash build-arm64-docker.sh
# 产出: build-arm64/rk3588-vlm (arm64 ELF)
# ============================================================
set -e
cd "$(dirname "$0")"

echo "=== [1/3] 启动 Docker 容器并安装交叉工具链 ==="
docker run --rm --name rk3588-build \
  -v "$(pwd)":/ws \
  debian:bullseye \
  bash -c '
    set -e
    dpkg --add-architecture arm64
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      gcc-aarch64-linux-gnu \
      libcurl4-openssl-dev:arm64 \
      pkg-config
    echo "=== 工具链安装完成 ==="
'

echo "=== [2/3] 交叉编译 ==="
docker run --rm --name rk3588-build-2 \
  -v "$(pwd)":/ws \
  debian:bullseye \
  bash -c '
    set -e
    dpkg --add-architecture arm64
    apt-get update -qq >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      gcc-aarch64-linux-gnu \
      libcurl4-openssl-dev:arm64 \
      pkg-config >/dev/null 2>&1 || true
    cd /ws
    rm -rf build-arm64
    cmake -B build-arm64 \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_SYSTEM_NAME=Linux \
      -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
      -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc \
      -DCMAKE_FIND_ROOT_PATH=/usr/aarch64-linux-gnu \
      -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
      -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
      -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY
    cmake --build build-arm64 -j4
    echo "=== 编译完成 ==="
'

echo "=== [3/3] 验证产物 ==="
file build-arm64/rk3588-vlm
readelf -h build-arm64/rk3588-vlm | grep -E "Class|Machine"
echo "=== DONE: build-arm64/rk3588-vlm ==="
