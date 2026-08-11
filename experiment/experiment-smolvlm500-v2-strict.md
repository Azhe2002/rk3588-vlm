# 实验：SmolVLM-500M 板端连续采图推理性能测试 (640×480 + 严厉 Prompt)

> 实验日期：2026-08-07
> 测试平台：RK3588S (Debian 11, 192.168.1.8)
> 测试程序：`/userdata/llama/bin/rk3588-vlm` (main 主程序, v3)
> 版本：v2-strict — 分辨率 640×480 + 更严厉的 yes/no 强制 prompt

---

## 1. 实验目的

- 针对 v2 (640×480) 的输出格式漂移问题，改用更严厉的 prompt 重新测试 500M
- 验证 prompt 强化是否能恢复严格 yes/no 合规输出（与 256M 同条件对比）

## 2. 测试配置

| 项目 | 值 |
|------|-----|
| 模型 | `SmolVLM-500M-Instruct-Q8_0.gguf` (417MB) |
| mmproj | `mmproj-SmolVLM-500M-Instruct-Q8_0.gguf` (104MB) |
| 相机 | /dev/video22, 640×480, 5fps |
| 推理间隔 | 1s |
| **Prompt（严厉版）** | `Is there a black industrial fan in the center of the image? You must answer with exactly one word, either "yes" or "no". No other text, no punctuation, no explanation.` |
| 系统提示词 | 默认工业检测模板（含 "Please respond with only 'yes' or 'no'"） |
| 测试图 | 实时采集帧（黑色工业风扇画面） |

> 与 v2 唯一差异：用户 prompt 从 "Please answer only yes or no." 强化为 "You must answer with exactly one word... No other text, no punctuation, no explanation."

## 3. 原始数据（前 10 轮）

| 轮次 | 耗时 (s) | 原始输出 | 程序判定 | 语义判定 |
|------|---------|---------|---------|---------|
| #1 | 8.12 | "A black industrial fan is on a table in a factory warehouse." | ❓ -1 | ✅ YES |
| #2 | 6.61 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #3 | 6.57 | "A black industrial fan is located in a factory warehouse." | ❓ -1 | ✅ YES |
| #4 | 6.62 | "A black fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #5 | 6.55 | "A black industrial fan is located in a factory warehouse." | ❓ -1 | ✅ YES |
| #6 | 6.63 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #7 | 6.56 | "A black fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #8 | 6.58 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #9 | 6.62 | "A black industrial fan is in the foreground of the image." | ❓ -1 | ✅ YES |
| #10 | 6.44 | "A black fan in a factory warehouse." | ❓ -1 | ✅ YES |

## 4. 统计结果

| 指标 | 数值 |
|------|------|
| min / max | 6.44s / 8.12s |
| **平均（#2-#10）** | **6.58s/帧** |
| 程序判定识别率 | 0/10 = **0%**（无一输出严格 yes/no） |
| 语义判定识别率 | 10/10 = **100%** |
| 等效帧率 | ~0.15 FPS |

> 程序实际运行 139.69s，推理 21 次；#11-#21 输出模式相同（板端 `/tmp/main_vlm_500_640_strict.log`）。

## 5. 关键发现

1. **⚠️ 严厉 prompt 完全无效**：10/10 全部输出完整句子，**0 个**严格 "yes"/"no" —— 比 v2 (非 strict) 更糟（v2 虽也全 -1，但语义上一致确认）
2. **语义识别 100%**：所有轮次正确识别风扇存在（foreground/table/warehouse 等描述均确认存在）
3. **耗时 6.58s**：与 v2 (6.67s) 几乎相同
4. **结论：对 500M @ 640×480，prompt 工程同样无法恢复严格 yes/no 合规输出** —— 需从解析器侧解决

## 6. 附注

- 实验日志：板端 `/tmp/main_vlm_500_640_strict.log`
- 综合对比见 `report.md`
