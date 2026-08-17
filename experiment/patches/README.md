# 板端代码补丁说明

## v0.3: 图文顺序修复 (2026-08-17 生成, **未应用**)

> 本补丁**只改一处请求体结构**：user content 数组改为 image 在前（image→text）。
> **尚未应用，由用户自行 `git apply` 后编译推板（`bash build-arm64-docker.sh` →
> 推 `/userdata/llama/bin/rk3588-vlm`）。** 推板后跑任意一组，banner 应显示
> `顺序: image→text (v0.3, S2-E1 消融修复)` 以确认新二进制生效。

```bash
git apply experiment/patches/v03_image_first.patch
```

### 为什么改（S2-E1 证据，2026-08-13 同帧配对消融）

| 顺序 | 负场景 (风扇不在) | 正场景 (风扇在) |
|------|------------------|----------------|
| text→image（旧 v0.2） | 0/20 单词；**20/20 幻觉** "There is a black industrial fan..." | 0/20 单词（描述句，语义正确） |
| image→text（v0.3） | 20/20 单词 "No." | 20/20 单词 "Yes." |

- McNemar p = 1.9×10⁻⁶；引导式提问（text 在前）压倒图像证据，**不只是格式问题，是确认幻觉/可靠性问题**
- 详见 `experiment/data/s2e1/SESSION-REPORT-2x2.md`

### 改动内容

| 文件 | 改动 |
|------|------|
| `llama_server.c` | user content 数组 `[image_url, text]` 顺序（原 `[text, image_url]`）；snprintf 实参顺序同步调整 |
| `main.c` | banner 增加 `顺序: image→text (v0.3, S2-E1 消融修复)` 行（推板后验证用） |

> 注: S2-E5（grammar 受限解码）正在验证"不改顺序、用 grammar 硬保格式"的备选方案——
> 若 S2-E5 显示 grammar 能同时保住语义（负场景给 "No."），v0.3 顺序修复与 grammar 方案可叠加决策。

---

## 实验7 / 实验2/3 代码补丁 (2026-08-11, **2026-08-12 已应用**)

> 本补丁**只改实验所需的最小范围**，不改变既有行为（默认值与原来完全一致）。
> **2026-08-12: 补丁已 git apply 到工作区源码（当前代码即 v0.2，含 --temp/--gst-extra）。**
> 由用户自行编译（`bash build-arm64-docker.sh`）、推板到 `/userdata/llama/bin/rk3588-vlm` 后执行对应的实验组。

## 应用方式（已应用，无需重复执行）

```bash
# 已在工作区根目录 (rk3588-vlm/) 执行:
git apply experiment/patches/exp7_temp_exp23_gstextra.patch
# 当前代码即新版本; 直接编译即可
# 编译 (build-arm64-docker.sh) → 推送 /userdata/llama/bin/rk3588-vlm → 跑实验
```

## 配套脚本（2026-08-12 新增）

| 文件 | 作用 |
|------|------|
| `experiment/board_exp_run.sh` | 已支持第 9/10 参数 `[temp] [gst_extra]`（bash 数组传参，元素串可含空格） |
| `experiment/run_exp7.py` | 温度扫描驱动（256M@640, temp∈{0.0,0.1,0.5,1.0}；`--500` 追加 500M 组）；自动推送新版 board_exp_run.sh 到板端 |
| `experiment/run_exp2_3.py` | 滤镜变体驱动（实验2 B/C/D + 实验3 B1/B2/B3/C，逐组帧采样）；自动推送新版 board_exp_run.sh |

> 注意: 板端旧版 rk3588-vlm 二进制无 --temp/--gst-extra，新脚本传参会报"未知参数"退出——**必须先推板 v0.2 二进制**。

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
