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
| `--strict` | `1` | 0 ~ 1 | 判定模式: 1=严格 yes/no (默认) 0=宽泛语义判定 |

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

## 判定模式 (--strict)

| 模式 | 判定函数 | 行为 |
|------|---------|------|
| `1` (默认) | `parse_yes_no` | 单词边界逐行解析, 只认完整 yes/no 单词 |
| `0` | `parse_yes_no_lenient` | 先严格解析; 失败后按语义关键词判断完整句子 |

### 宽泛模式 (--strict 0) 语义关键词

- **否定词** → NO: `there is no`, `no black`, `not present`, `missing`, `absent`, `doesn't`, `isn't` 等
- **肯定词** → YES: `there is a`, `is in`, `is on`, `is located`, `shows a`, `contains`, `sits on` 等
- **启发式**: 无否定词且以 `a/an` 开头的存在性描述句 → YES (如 "A black fan in a factory warehouse.")
- 肯定/否定都命中或无命中 → -1 (无法识别)

> 用途: 高分辨率 (640×480) 下模型倾向输出完整句子而非 "yes"/"no",
> 此时 `--strict 1` 会判 -1, 用 `--strict 0` 可按语义正确判定。

---

*项目: rk3588-vlm v3*
*日期: 2026-07-13 (更新: 2026-08-07)*
