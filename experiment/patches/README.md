# 实验7 / 实验2/3 代码补丁说明 (2026-08-11)

> 本补丁**只改实验所需的最小范围**，不改变既有行为（默认值与原来完全一致）。
> 由用户自行编译、推板后执行对应的实验组。

## 应用方式

```bash
# 在工作区根目录 (rk3588-vlm/) 执行:
git apply experiment/patches/exp7_temp_exp23_gstextra.patch
# 编译 (沿用 build-arm64-docker.sh) → 推送 /userdata/llama/bin/rk3588-vlm → 跑实验
```

## 改动内容

| 文件 | 改动 |
|------|------|
| `llama_server.c/h` | `llama_init()` 增加 temperature 参数；请求体 `"temperature":0.1` 改为 `%.2f` 动态值（原硬编码点: 请求体） |
| `main.c` | 新增 `--temp F` (0.0~2.0, 默认 0.1) 与 `--gst-extra STR` 参数；banner 显示 |
| `camera.c/h` | `camera_start()` 增加 gst_extra 参数；GStreamer 管道在 jpegenc 前插入附加元素串 |

## 实验7: 温度扫描 (H6)

```bash
# 每组 20+ 轮, 640×480, 256M; temp ∈ {0.0, 0.1, 0.5, 1.0}
bash /tmp/board_exp_run.sh SmolVLM-256M-Instruct-Q8_0.gguf \
  mmproj-SmolVLM-256M-Instruct-Q8_0.gguf 640 480 180 \
  "Is there a black industrial fan in the center of the image? Please answer only yes or no." \
  /tmp/exp7_t0.log 0   # 加 --temp 需在 rk3588-vlm 命令后追加
```

注意: board_exp_run.sh 当前不传 --temp；编译版跑温度组时需在脚本的
`rk3588-vlm` 调用后追加 `--temp <值>`（或直接命令行手工起 server + rk3588-vlm）。

## 实验2: 分辨率与有效像素解耦

板端 GStreamer 滤镜已验证可用: `videoscale / gaussianblur / videocrop / videobox / smooth`。

| 组 | 操作 | 命令 (--gst-extra) |
|----|------|--------------------|
| B | 640×480 捕获 → 输入前缩到 320×240 | `videoscale ! video/x-raw,width=320,height=240` |
| C | 320×240 捕获 → 放大到 640×480 (宽高参数仍传 640 480) | `videoscale ! video/x-raw,width=640,height=480` |
| D | 640×480 裁剪中心 320×240 区域 | `videocrop left=160 right=160 top=120 bottom=120` |

> 实现说明: 相机采集 caps 用 `--width/--height` 指定。C 组让 v4l2src 按 640×480
> 采集后由 videoscale 下采样/上采样，等价于"显示分辨率与有效像素分离"。
> 元素串内勿含空格；带空格的 caps 用单引号包裹（如 `video/x-raw,width=320,height=240` 无空格可不加）。

## 实验3: 模糊/噪声扰动 (H2)

| 组 | 操作 | 命令 (--gst-extra) |
|----|------|--------------------|
| B1 | 高斯模糊 σ=3 | `gaussianblur sigma=3` |
| B2 | 高斯模糊 σ=7 | `gaussianblur sigma=7` |
| B3 | 高斯模糊 σ=15 | `gaussianblur sigma=15` |
| C | 下采样再上采样去纹理 | `videoscale ! video/x-raw,width=160,height=120 ! videoscale ! video/x-raw,width=640,height=480` |
| D | 强噪声 | 板端无 gst noise 元素；可用 ffmpeg 或跳过（如实报告局限） |

## 验证建议

推板后先用短跑验证: 跑 1-2 分钟单组，检查日志 banner 显示 `温度: 0.xx` 与
GStreamer 附加行，确认帧仍正常输出后再跑正式实验。
