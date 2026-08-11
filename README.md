# rk3588-vlm — RK3588 板端 VLM 工业检测程序

## 项目结构

```
rk3588-vlm/
├── CMakeLists.txt              # 交叉编译 (ARM64, glibc + libcurl)
├── main.c                      # 主程序: 安全参数解析 + 定时推理循环 + 相机自动恢复
├── camera.h / camera.c         # V4L2 持久管道采集 (内存帧, 零磁盘)
├── llama_server.h / llama_server.c  # 常驻 llama-server + HTTP 推理 (模型只加载一次)
├── result_parser.h / result_parser.c  # 单词边界 yes/no 解析 (防误判)
└── README.md
```

*注: 本地开发目录另有 `test_parser.c` (宽泛判定单元测试, 20 用例) 与 `build-arm64-docker.sh` (一键交叉编译脚本)。*

## 架构

```
┌───────────┐     ┌──────────────────┐     ┌───────────────┐
│ camera.c  │ ──▶ │   main.c         │ ──▶ │ result_parser │
│ (持久管道) │     │  (每 N 秒推理一次)  │     │ (单词边界解析) │
│ GStreamer │     │         │        │     └───────────────┘
│ fdsink    │     │         ▼        │
│ 5fps流解析│     │   llama_server.c  │
└───────────┘     │  (HTTP 常驻服务)  │
                   └──────────────────┘
```

## v3 相对 v1 的核心改进

| 模块 | 改进 |
|------|------|
| **camera.c** | 持久 GStreamer 管道 → 内存帧 → 原子写盘 → 异常自动恢复 |
| **llama_server.c** | CLI 每次启动 → **常驻 HTTP server**, 模型只加载一次 |
| **main.c** | `sigaction` 信号安全 + `strtol` 严格校验 + `CLOCK_MONOTONIC` 计时 + `--camera` 参数 + 相机自动重启 |
| **result_parser.c** | 单词边界逐行解析, 防止 "not"/"nobody" 误判, 冲突检测 |

## 编译 (Docker 交叉编译)

```bash
sudo rm -rf ~/workspace/rk3588-vlm/build

sudo docker run --rm -v ~/workspace/rk3588-vlm:/workspace -w /workspace debian:bullseye bash -c "
  dpkg --add-architecture arm64
  apt-get update -qq
  apt-get install -y -qq gcc-aarch64-linux-gnu cmake make libcurl4-openssl-dev:arm64
  cmake -B build \
    -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc \
    -DCMAKE_BUILD_TYPE=Release
  cmake --build build -j1
"

file build/rk3588-vlm
```

## 部署

```bash
python3 -c "
import paramiko
c=paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.1.8',22,'linaro','rockchip',timeout=10)
s=c.open_sftp()
s.put('/home/azhe/workspace/rk3588-vlm/build/rk3588-vlm','/userdata/llama/bin/rk3588-vlm')
s.chmod('/userdata/llama/bin/rk3588-vlm',0o755)
s.close()
c.close()
print('done')
"
```

## 运行

```bash
cd /userdata/llama/bin
export LD_LIBRARY_PATH=/userdata/llama/bin

./rk3588-vlm \
  --camera   /dev/video22 \
  --question "Is there a pink cup or bottle in the center of the image?" \
  --width    320 --height 240 --interval 15
```

### 停止服务

```bash
/userdata/llama/bin/kill-vlm
```

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--camera` | `/dev/video22` | 相机设备 |
| `--model` | `.../SmolVLM-500M-Instruct-Q8_0.gguf` | 模型路径 |
| `--mmproj` | `.../mmproj-SmolVLM-500M-Instruct-Q8_0.gguf` | mmproj 路径 |
| `--object` | `industrial items` | 检测目标 |
| `--scene` | `factory warehouse, dim lighting` | 场景描述 |
| `--question` | `is there any object in the center of picture?` | 检测问题 |
| `--width` | `320` | 采集宽度 (1~3840) |
| `--height` | `240` | 采集高度 (1~2160) |
| `--interval` | `15` | 推理间隔秒数 (1~86400) |
| `--strict` | `1` | 判定模式: 1=严格 yes/no (默认) 0=宽泛语义判定 |

### 判定模式 (--strict)

- `--strict 1`（默认）：`parse_yes_no` 单词边界逐行解析，只认完整 yes/no 单词 —— 低分辨率 (320×240) 下模型输出合规，推荐。
- `--strict 0`：`parse_yes_no_lenient` 先严格解析，失败后按语义关键词判断完整句子（`there is a` / `is in` / `no black` / `missing` 等）—— 高分辨率 (640×480) 下模型倾向输出完整句子（如 *"There is a black industrial fan in the center of the image."*），此时严格模式会判 -1，用宽泛模式可按语义正确判定。

```bash
# 640x480 + 宽泛语义判定
./rk3588-vlm --width 640 --height 480 --strict 0 \
  --question "Is there a black industrial fan in the center of the image?"
```

## 版本

| 版本 | 日期 | 说明 |
|------|------|------|
| v3.1 | 2026-08-07 | 新增 `--strict` 判定模式 (0=宽泛语义判定) + `parse_yes_no_lenient` + 单元测试 |
| v3 | 2026-07-13 | 持久相机管道 + 常驻 server + 单词边界解析 + 安全信号/参数 |
| v1 | 2026-07-07 | 初版: shell CLI + 简单解析 |

---

*项目: rk3588-vlm*
