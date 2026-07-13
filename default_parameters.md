# rk3588-vlm — 全部参数与默认值

## 命令行参数 (main.c)

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `--camera` | `/dev/video22` | — | V4L2 相机设备 |
| `--model` | `.../SmolVLM-500M-Instruct-Q8_0.gguf` | — | GGUF 模型路径 |
| `--mmproj` | `.../mmproj-SmolVLM-500M-Instruct-Q8_0.gguf` | — | 多模态投影文件 |
| `--object` | `industrial items` | — | 检测目标定义 |
| `--scene` | `factory warehouse, dim lighting` | — | 场景描述 |
| `--question` | `is there any anomaly?` | — | 检测问题 (固定, 改需重启) |
| `--width` | `320` | 1 ~ 3840 | 采集宽度 |
| `--height` | `240` | 1 ~ 2160 | 采集高度 |
| `--interval` | `15` | 1 ~ 86400 | 推理间隔 (秒) |

## 系统提示词模板

```
You are an expert in recognition, processing, and analysis.
Please carefully analyze the image and answer the question accurately.
Please respond with only 'yes' or 'no'.
Detection target: {--object}. Scene: {--scene}.
```

## 硬编码参数

### 推理服务 (llama_server.c)

| 参数 | 值 | 说明 |
|------|-----|------|
| `SERVER_BIN` | `/userdata/llama/bin/llama-server` | llama-server 二进制 |
| `LIB_PATH` | `/userdata/llama/bin` | LD_LIBRARY_PATH |
| `SERVER_HOST` | `127.0.0.1` | 绑定地址 |
| `SERVER_PORT` | `8088` | 监听端口 |
| `HEALTH_TIMEOUT_SEC` | `30` | 服务启动超时 |
| `INFER_TIMEOUT_SEC` | `30` | 单次推理超时 |
| `temperature` | `0.1` | 推理温度 |
| `max_tokens` | `16` | 最大输出 token 数 |

### 相机采集 (camera.c)

| 参数 | 值 | 说明 |
|------|-----|------|
| `CAMERA_FPS` | `5` | 采集帧率 |
| `FIRST_FRAME_TIMEOUT_SEC` | `8` | 首帧超时 |
| `SAVE_FRAME_TIMEOUT_SEC` | `8` | 取帧超时 |
| `MAX_JPEG_BYTES` | `64 MiB` | JPEG 帧上限 |

### 主程序 (main.c)

| 参数 | 值 | 说明 |
|------|-----|------|
| `FRAME_PATH` | `/dev/shm/frame.jpg` | 帧文件路径 (tmpfs) |
| `MAX_DIMENSION` | `8192` | 分辨率上限 |
| `MAX_INTERVAL` | `86400` | 间隔上限 (24h) |

---

*项目: rk3588-vlm v3*
*日期: 2026-07-13*
