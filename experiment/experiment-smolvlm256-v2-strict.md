# 实验：SmolVLM-256M 板端连续采图推理性能测试 (640×480 + 严厉 Prompt)

> 实验日期：2026-08-07
> 测试平台：RK3588S (Debian 11, 192.168.1.8)
> 测试程序：`/userdata/llama/bin/rk3588-vlm` (main 主程序, v3)
> 版本：v2-strict — 分辨率 640×480 + 更严厉的 yes/no 强制 prompt

---

## 1. 实验目的

- 针对 v2 (640×480) 的输出格式漂移问题（模型输出完整句子而非 "yes"/"no"），改用更严厉的 prompt 重新测试
- 验证 prompt 强化是否能恢复 320×240 下的严格 yes/no 合规输出

## 2. 测试配置

| 项目 | 值 |
|------|-----|
| 模型 | `SmolVLM-256M-Instruct-Q8_0.gguf` (167MB) |
| mmproj | `mmproj-SmolVLM-256M-Instruct-Q8_0.gguf` (99MB) |
| 相机 | /dev/video22, 640×480, 5fps |
| 推理间隔 | 1s |
| **Prompt（严厉版）** | `Is there a black industrial fan in the center of the image? You must answer with exactly one word, either "yes" or "no". No other text, no punctuation, no explanation.` |
| 系统提示词 | 默认工业检测模板（含 "Please respond with only 'yes' or 'no'"） |
| 测试图 | 实时采集帧（黑色工业风扇画面） |

> 与 v2 唯一差异：用户 prompt 从 "Please answer only yes or no." 强化为 "You must answer with exactly one word... No other text, no punctuation, no explanation."

## 3. 原始数据（前 10 轮）

| 轮次 | 耗时 (s) | 原始输出 | 程序判定 | 语义判定 |
|------|---------|---------|---------|---------|
| #1 | 6.23 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #2 | 5.76 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #3 | 5.71 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #4 | 5.72 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #5 | 5.73 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #6 | 5.71 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #7 | 5.70 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #8 | 5.71 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |
| #9 | 5.50 | "Yes." | ✅ YES (1) | ✅ YES |
| #10 | 5.67 | "There is a black industrial fan in the center of the image." | ❓ -1 | ✅ YES |

## 4. 统计结果

| 指标 | 数值 |
|------|------|
| min / max | 5.50s / 6.23s |
| **平均** | **5.74s/帧** |
| 程序判定识别率 | 1/10 = **10%**（仅 #9） |
| 语义判定识别率 | 10/10 = **100%** |
| 等效帧率 | ~0.17 FPS |

> 程序实际运行 139.69s（500M 实验共用时间轴，此文件为 256M 部分），推理 21 次；#11-#21 输出模式相同（板端 `/tmp/main_vlm_256_640_strict.log`）。

## 5. 关键发现

1. **⚠️ 严厉 prompt 基本无效**：10 轮中仍只有 1 轮 (#9) 输出严格 "Yes."，其余 9 轮仍是完整句子 —— 与 v2 (非 strict) 的合规率几乎相同（v2 也是 1/10）
2. **语义识别 100%**：所有轮次都正确识别风扇存在，识别能力无退化
3. **耗时 5.74s**：与 v2 (5.69s) 几乎相同，prompt 长度变化不影响耗时
4. **结论：对 256M @ 640×480，prompt 工程无法恢复严格 yes/no 合规输出** —— 需从解析器侧解决（增强 `parse_yes_no` 识别完整句子，或限制 max_tokens）

## 6. 附注

- 实验日志：板端 `/tmp/main_vlm_256_640_strict.log`
- 综合对比见 `report.md`
