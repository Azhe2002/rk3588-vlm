# 实验：SmolVLM-500M 板端连续采图推理性能测试 (640×480)

> 实验日期：2026-08-07
> 测试平台：RK3588S (Debian 11, 192.168.1.8)
> 测试程序：`/userdata/llama/bin/rk3588-vlm` (main 主程序, v3)
> 版本：v2 — 分辨率 640×480（v1 为 320×240）

---

## 1. 实验目的

- 验证分辨率从 320×240 提升到 640×480 后，SmolVLM-500M 的耗时变化与识别表现
- 与 v1 (320×240) 同口径对比，评估高分辨率对性能/合规性的影响

## 2. 测试配置

| 项目 | 值 |
|------|-----|
| 模型 | `SmolVLM-500M-Instruct-Q8_0.gguf` (417MB) |
| mmproj | `mmproj-SmolVLM-500M-Instruct-Q8_0.gguf` (104MB) |
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
| #1 | 7.88 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #2 | 6.61 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #3 | 6.56 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #4 | 6.70 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #5 | 6.70 | "A black industrial fan sits on a table in a factory warehouse." | ❓ -1 | ✅ YES |
| #6 | 6.69 | "A black industrial fan sits on a table in a factory warehouse." | ❓ -1 | ✅ YES |
| #7 | 6.74 | "A black industrial fan is on a table in the foreground of the image." | ❓ -1 | ✅ YES |
| #8 | 6.70 | "A black industrial fan is on a table in the foreground of the image." | ❓ -1 | ✅ YES |
| #9 | 6.69 | "A black industrial fan is on a table in the foreground of the image." | ❓ -1 | ✅ YES |
| #10 | 6.60 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |

## 4. 统计结果

| 指标 | 数值 |
|------|------|
| min / max | 6.56s / 7.88s |
| **平均（#2-#10）** | **6.67s/帧** |
| 程序判定识别率 | 0/10 = **0%**（全部被 parse_yes_no 判 -1） |
| **语义判定识别率** | **10/10 = 100%**（全部确认风扇存在） |
| 等效帧率 | ~0.15 FPS |

> 程序实际运行 140.81s，共推理 21 次；#11-#21 输出模式相同（数据见板端 `/tmp/main_vlm_500_640.log`）。

## 5. 关键发现

1. **耗时 6.67s/帧**：比 v1 (320×240) 的 6.18s 慢 ~8% —— 分辨率提升的边际开销比 256M 更明显
2. **⚠️ 输出格式漂移（同 256M）**：640×480 下 100% 输出完整句子，无一输出严格 "Yes."/"No."
   - 语义全部正确（确认风扇存在），但 `parse_yes_no` 全部判 -1
   - 注意：500M 描述为 "foreground"（前景）而非 "center"（中心）—— 640×480 下风扇占画面比例大，模型表述更具体
3. **语义正确率 100%**（10/10 确认存在）
4. 与 256M 相同结论：高分辨率下模型倾向完整句子回答，**解析器必须增强**（识别 "There is a.../A ... is in..." 等句型）

## 6. 附注

- 实验日志：板端 `/tmp/main_vlm_500_640.log`
- 与 320×240/256M 的综合对比见 `report.md`
