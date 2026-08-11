# 实验：SmolVLM-256M 板端连续采图推理性能测试 (640×480)

> 实验日期：2026-08-07
> 测试平台：RK3588S (Debian 11, 192.168.1.8)
> 测试程序：`/userdata/llama/bin/rk3588-vlm` (main 主程序, v3)
> 版本：v2 — 分辨率 640×480（v1 为 320×240）

---

## 1. 实验目的

- 验证分辨率从 320×240 提升到 640×480 后，SmolVLM-256M 的耗时变化与识别表现
- 与 v1（320×240）同口径对比，评估高分辨率对性能/合规性的影响

## 2. 测试配置

| 项目 | 值 |
|------|-----|
| 模型 | `SmolVLM-256M-Instruct-Q8_0.gguf` (167MB) |
| mmproj | `mmproj-SmolVLM-256M-Instruct-Q8_0.gguf` (99MB) |
| 推理服务 | llama-server (板端常驻, port 8088) |
| 相机 | /dev/video22, **640×480**, 5fps |
| 推理间隔 | 1s（实际被推理时间淹没） |
| Prompt | `Is there a black industrial fan in the center of the image? Please answer only yes or no.` |
| 系统提示词 | 默认工业检测模板（目标: industrial items, 场景: factory warehouse, dim lighting） |
| 测试图 | 实时采集帧（黑色工业风扇画面，与 v1 同一场景） |

> ⚠️ 与 v1 (320×240) 唯一差异：分辨率；其余（程序/prompt/场景/间隔）全部一致。

## 3. 原始数据（前 10 轮）

| 轮次 | 耗时 (s) | 原始输出 | 程序判定 | 语义判定 |
|------|---------|---------|---------|---------|
| #1 | 6.10 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #2 | 5.73 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #3 | 5.70 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #4 | 5.47 | "Yes." | ✅ YES (1) | ✅ YES |
| #5 | 5.67 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #6 | 5.64 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #7 | 5.72 | "There is a black industrial fan in the corner of the image." | ❓ -1 | ⚠️ 存疑（corner≠center） |
| #8 | 5.61 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #9 | 5.64 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #10 | 5.63 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |

## 4. 统计结果

| 指标 | 数值 |
|------|------|
| min / max | 5.47s / 6.10s |
| **平均** | **5.69s/帧** |
| 程序判定识别率 | 1/10 = **10%**（仅 #4 被 parse_yes_no 识别） |
| **语义判定识别率** | **9/10 = 90%**（#7 corner 存疑） |
| 等效帧率 | ~0.18 FPS |

> 程序实际运行至 #27+ 后被终止；#11-#27 同样以完整句子输出为主（数据见板端 `/tmp/main_vlm_256_640.log`）。

## 5. 关键发现

1. **耗时 5.69s/帧**：比 v1 (320×240) 的 5.49s 仅慢 ~4% —— 分辨率提升对耗时的边际影响小，编码仍是瓶颈
2. **⚠️ 分辨率改变导致输出格式漂移**：320×240 时稳定输出 "Yes."；640×480 时 90% 输出完整句子 `"There is a black industrial fan in the center of the image."`
   - 语义全部正确（风扇确实在中心），但主程序 `parse_yes_no` 只认严格 yes/no → 判 -1
   - **这是解析器兼容性问题，不是模型识别失败**
3. **语义正确率 90%**（9/10 YES，1 轮 corner 存疑）
4. 若需 640×480 生产使用，需改进 `parse_yes_no`：识别 "There is a.../Yes/No" 等完整句子，或加长 prompt 强制 "answer in a word"

## 6. 附注

- 实验日志：板端 `/tmp/main_vlm_256_640.log`
- 与 320×240/500M 的综合对比见 `report.md`
