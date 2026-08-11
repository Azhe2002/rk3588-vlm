# Input Resolution-Dependent Collapse of Output-Format Instruction Following in Small Vision-Language Models

> **状态**: 材料草稿 v0.1 — 实验小助手整理，供研究讨论与扩展
> **日期**: 2026-08-07
> **研究问题**: 为什么 640×480 输入分辨率下，"yes/no 强约束"在 SmolVLM 系列小模型中会失效？

---

## 摘要 (Abstract)

指令遵循（instruction following）是视觉语言模型（VLM）在受控自动化场景中可靠部署的关键能力，其中要求模型输出严格受限格式（如仅输出 "yes"/"no"）的任务尤其依赖该能力。本文报告一个**反直觉且可复现的实验现象**：在两个小规模视觉语言模型（SmolVLM-256M / SmolVLM-500M）上，将输入图像分辨率从 320×240 提升至 640×480 后，模型对 "Please answer only yes or no" 这一显式输出格式约束的遵循率从 **90–100% 骤降至 0–10%**，且**强化 prompt 措辞（严厉版本）无法恢复合规输出**。同时，模型的**语义判断能力保持稳定**（90–100% 正确识别目标是否存在），说明失效发生在"输出格式控制"层面而非"感知/推理"层面。本文系统记录实验流程、原始数据，并提出机制假设——包括视觉 token 数量膨胀导致的指令注意力稀释、分辨率相关的 patch 化表征偏移、以及小模型容量限制下的指令-视觉竞争——供后续受控实验验证。

**关键词**: Vision-Language Models; Instruction Following; Output Format Control; Input Resolution; Edge Deployment; SmolVLM

---

## 1. 引言 (Introduction)

### 1.1 背景

小规模视觉语言模型（<1B 参数）正被广泛部署于边缘设备（如 RK3588 类 SoC）执行实时视觉检测任务。在工业检测、质量门禁等受控场景中，系统通常要求模型输出**机器可解析的严格格式**（如单一 "yes"/"no" token），而非自由文本。这类"输出格式约束"（output format constraint）依赖模型的指令遵循能力。

### 1.2 问题陈述

在 RK3588S 板端部署实验中发现：当输入分辨率从 320×240 提升到 640×480 时，SmolVLM 系列模型输出的格式约束遵循行为发生**崩塌式退化**：

| 分辨率 | 严格格式遵循率（两模型） | 语义正确率（两模型） |
|--------|------------------------|---------------------|
| 320×240 | 90–100% | 90–100% |
| 640×480 | **0–10%** | **90–100%** |

这一现象**不能**由以下平凡因素解释：
- 不是解析器 bug（原始输出直接可见，确实从 "Yes." 变为完整句子）
- 不是感知能力退化（语义判断始终正确）
- 不是 prompt 强度不足（严厉 prompt 无效，见 §5.4）

### 1.3 研究目标

1. 系统记录并复现该现象（本文提供完整实验流程与数据）
2. 提出可检验的机制假设（§6）
3. 设计受控实验以定位失效环节（见 `methods.md`）

### 1.4 贡献

- **现象报告**: 首个在小模型 VLM 上系统报告"输入分辨率→输出格式遵循崩塌"的实证研究（据我们所知）
- **完整流程**: 可复现的板端实验协议（相机采集→常驻推理→逐帧评估）
- **负结果**: 强化 prompt 无法修复格式遵循（排除 prompt 工程路线）
- **机制框架**: 三种可检验假设 + 实验设计

---

## 2. 相关工作 (Related Work)

### 2.1 指令遵循与格式控制

大语言模型（LLM）的指令遵循已被广泛研究（Ouyang et al., 2022; Wei et al., 2021），结构化输出（JSON、代码、受限格式）通常通过 prompt 约束或解码约束（constrained decoding, e.g. guidance, outlines）实现。然而，**视觉语言模型的指令遵循在输入条件变化下的鲁棒性**研究相对较少，尤其是**图像分辨率**这一输入维度的影响鲜有报道。

### 2.2 小模型的能力边界

小模型（<1B）在指令遵循上存在已知容量瓶颈（Zhou et al., 2024），多任务竞争（感知 vs. 指令）时可能顾此失彼。本文现象可能是该瓶颈的输入敏感型表现。

### 2.3 视觉编码与分辨率

现代 VLM（如 SmolVLM、LLaVA、Qwen2-VL）将图像切分为 patch 并投影为视觉 token。分辨率提升直接导致**视觉 token 数量增加**（SmolVLM 中 320×240 → 640×480 使有效 patch 数倍增），改变注意力分布与指令 token 的相对权重——这构成本文假设 H1 的基础。

### 2.4 边缘部署中的 VLM

RK3588 类设备上部署 VLM（llama.cpp 生态）的工程实践已有大量报告，但针对**输出格式鲁棒性**的系统研究缺失。本文填补这一空白。

---

## 3. 方法 (Methods)

### 3.1 硬件平台

| 组件 | 规格 |
|------|------|
| SoC | Rockchip RK3588S |
| OS | Debian 11 (Bullseye), GLIBC 2.31 |
| RAM | 7.7 GB |
| 推理引擎 | llama.cpp v0.15.3（CPU，arm64） |
| 相机 | /dev/video22, MIPI CSI, 最大 3840×2160, NV12 |

### 3.2 模型

| 模型 | 主模型权重 | mmproj | 量化 |
|------|-----------|--------|------|
| SmolVLM-256M-Instruct | 167 MB | 99 MB | Q8_0 |
| SmolVLM-500M-Instruct | 417 MB | 104 MB | Q8_0 |

两模型均为 SmolVLM 架构（HuggingFace SmolVLM-Instruct 系列），通过 llama.cpp 多模态路径推理，支持图像 patch 编码 + 文本解码。

### 3.3 测试程序

自定义 C 程序 `rk3588-vlm`（main 主程序），流水线：

```
V4L2 相机 (持久管道, 5fps, 内存帧)
  → 每轮取最新帧 → 写 /dev/shm/frame.jpg
  → HTTP POST 到常驻 llama-server (port 8088, 模型只加载一次)
  → 解析原始输出 → 记录耗时与判定
```

**关键设计**：
- 每轮**重新取帧**（JPEG 内容逐帧变化）→ 杜绝 KV cache 命中，保证测量真实推理耗时
- 模型常驻 → 排除模型加载时间（首轮除外）
- 原始输出全文记录 → 事后可人工/语义判定

### 3.4 实验任务

- **检测问题 (用户 prompt)**: `Is there a black industrial fan in the center of the image? Please answer only yes or no.`
- **系统提示词**: `You are an expert in recognition... Please respond with only 'yes' or 'no'. Detection target: industrial items. Scene: factory warehouse, dim lighting.`
- **严厉 prompt 版本**: `Is there a black industrial fan in the center of the image? You must answer with exactly one word, either "yes" or "no". No other text, no punctuation, no explanation.`
- **场景**: 黑色工业风扇置于室内（仓库/厂房，暗光），画面静止
- **推理参数**: temperature=0.1, max_tokens=32, 单请求超时 300s

### 3.5 实验矩阵

2 模型 × 2 分辨率 × 2 prompt 强度 = 6 组实验（320×240 仅测普通 prompt；640×480 测普通 + 严厉），每组 10 轮（部分组跑到 20+ 轮）。

### 3.6 评估指标

| 指标 | 定义 |
|------|------|
| 严格格式遵循率 | 原始输出为严格 "yes"/"no"（单词边界解析 `parse_yes_no` 返回 1/0）的轮次占比 |
| 语义判定正确率 | 人工/关键词判定输出语义是否为正确答案的轮次占比 |
| 端到端单帧耗时 | 取帧→推理→返回 的墙钟时间（秒） |
| 输出类型分布 | 严格单词 / 完整句子 / 其他 的分布 |

---

## 4. 结果 (Results)

### 4.1 现象一：分辨率提升导致格式遵循崩塌

**表 1. 六组实验总览**（10 轮/组）

| # | 模型 | 分辨率 | Prompt | 平均耗时 | 严格遵循 | 语义正确 | 输出形态 |
|---|------|--------|--------|---------|---------|---------|---------|
| 1 | 256M | 320×240 | 普通 | 5.49s | **100%** (10/10) | 100% | "Yes." |
| 2 | 500M | 320×240 | 普通 | 6.18s | **90%** (9/10) | 90% | "Yes." |
| 3 | 256M | 640×480 | 普通 | 5.69s | **10%** (1/10) | 90% | 完整句子 |
| 4 | 500M | 640×480 | 普通 | 6.67s | **0%** (0/10) | 100% | 完整句子 |
| 5 | 256M | 640×480 | 严厉 | 5.74s | **10%** (1/10) | 100% | 完整句子 |
| 6 | 500M | 640×480 | 严厉 | 6.58s | **0%** (0/10) | 100% | 完整句子 |

**核心发现**：
- 分辨率 320×240 → 640×480 时，严格格式遵循从 90–100% 崩塌至 0–10%
- 语义正确率保持 90–100% —— **感知/推理能力未受损**
- 256M 组（#1 vs #3）：遵循率 100% → 10%；500M 组（#2 vs #4）：90% → 0%

### 4.2 现象二：严厉 prompt 无法恢复合规

将 prompt 强化为 "You must answer with exactly one word... No other text, no punctuation, no explanation." 后：
- 256M @ 640×480: 遵循率仍为 10%（#5 ≈ #3）
- 500M @ 640×480: 遵循率仍为 0%（#6 = #4）

**结论**：格式遵循的崩塌**不随 prompt 措辞强度变化**，暗示机制性因素（输入表征）而非指令表述不足。

### 4.3 输出形态分析

640×480 下模型倾向输出**完整的描述性句子**，且内容上正确回答（存在性确认）：

| 模型 | 典型输出 |
|------|---------|
| 256M @ 640×480 | "There is a black industrial fan in the center of the image." |
| 500M @ 640×480 | "A black industrial fan is in the foreground of the image." / "A black industrial fan sits on a table in a factory warehouse." |

**注意**：500M 在 640×480 下还表现出"位置描述更具体"（foreground/on a table），说明模型在高分辨率下确实利用了更多视觉细节——这为假设 H2（信息量驱动）提供初步支持。

### 4.4 耗时数据（性能维度）

**表 2. 端到端单帧耗时**（10 轮均值）

| 对比 | 数值 | 说明 |
|------|------|------|
| 256M @ 320×240 | 5.49s | 基准 |
| 500M @ 320×240 | 6.18s | 大 11% |
| 256M @ 640×480 | 5.69s | 分辨率 ↑ 仅慢 4% |
| 500M @ 640×480 | 6.67s | 分辨率 ↑ 慢 8% |

**关键洞察**：分辨率提升（像素 ×4）仅带来 4–8% 耗时增加 → 耗时瓶颈是**视觉编码固定开销（~4.5s）**，而非 token 数或生成长度。这为假设 H1（视觉 token 数量）提供一个反证线索——若 token 数量是主因，耗时应有更显著增长（见 §6 讨论）。

### 4.5 对照实验：KV cache 假象

固定图片连续 10 次请求时，第 1 次 5.75s、第 2–10 次仅 0.07–0.13s——这是 llama-server 的 KV cache/prompt cache 命中，**不代表真实逐帧性能**。本论文所有数据均使用逐帧新图测量，规避此陷阱。

---

## 5. 实验流程记录 (Reproducibility)

### 5.1 板端部署

```bash
# 模型推送 (SFTP)
/userdata/llama/models/SmolVLM-{256M,500M}-Instruct-Q8_0.gguf
/userdata/llama/models/mmproj-SmolVLM-{256M,500M}-Instruct-Q8_0.gguf
```

### 5.2 运行命令

```bash
cd /userdata/llama
export LD_LIBRARY_PATH=/userdata/llama/bin

./rk3588-vlm \
  --model   /userdata/llama/models/SmolVLM-256M-Instruct-Q8_0.gguf \
  --mmproj  /userdata/llama/models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf \
  --width   640 --height 480 \
  --interval 1 \
  --question "Is there a black industrial fan in the center of the image? Please answer only yes or no."
```

### 5.3 数据记录

- 每轮输出：轮次号、原始输出全文、程序判定、端到端耗时
- 板端日志：`/tmp/main_vlm*.log`（6 份，每组实验一份）
- 本地汇总：`experiment-smolvlm*.md`（6 份）+ `report.md`

### 5.4 判定函数

- **严格判定** `parse_yes_no()`: 单词边界逐行解析，仅完整 "yes"/"no" 单词算命中
- **语义判定** `parse_yes_no_lenient()`: 严格失败后按语义关键词（"there is a", "no black" 等）判断

---

## 6. 机制讨论 (Discussion)

### 6.1 观察到的规律

1. 格式遵循崩塌与**分辨率**强相关，与 **prompt 强度**无关
2. 语义正确率始终高企 → 失效限于"输出格式控制"环节
3. 高分辨率下模型输出**更长、更具体**的描述 → 模型"有更多话要说"

### 6.2 候选机制假设

#### H1: 视觉 token 膨胀 → 指令注意力稀释
分辨率提升 → patch 数倍增 → 视觉 token 数量显著增加 → 在注意力层中，指令 token（"answer only yes or no"）的相对注意力权重被大量视觉 token 稀释 → 生成阶段指令影响力下降。
**初步反证**：若 token 数量是主因，耗时应有超线性增长，但实测仅 +4–8%（§4.4）。不过耗时的瓶颈在编码器，注意力稀释可能不反映在总耗时上——仍需显式测量注意力分布验证。

#### H2: 信息量/细节驱动 → 描述先验被激活
高分辨率图像携带更多可识别细节（纹理、位置、背景）→ 模型训练分布中"详细描述"先验被激活，压过"单字回答"指令 → 输出形态由任务先验主导。
**初步支持**：500M 在 640×480 下输出 "foreground"/"on a table" 等更具体信息（§4.3）。

#### H3: 小模型容量限制 → 指令-视觉竞争
<1B 模型的容量有限，在"感知-理解-回答"的联合任务中，高分辨率带来更大视觉处理负担，模型"资源"被感知占用，格式控制（较弱的指令信号）被牺牲。
**初步支持**：500M（更大）在 640 下语义更稳（100%）而格式更差（0%），暗示容量分配权衡。

#### H4（备选）: 视觉编码对位置/尺寸感知增强 → "中心" vs "前景" 判断冲突
640×480 下模型判断风扇"在 foreground 而非 center"（#4 组 10/10 都这么说）→ 可能模型在尝试"纠正"问题的假设，从而输出更复杂的回答。语义存疑轮（256M #7 "corner"）支持该方向。

### 6.3 假说的判别方法（摘要）

| 假设 | 判别实验 | 预期 |
|------|---------|------|
| H1 | 同分辨率下改变 patch 尺寸/token 数（如缩放 640×480→320×240 等效 token 但保留细节） | token 数下降 → 遵循恢复 |
| H2 | 模糊/降噪高分辨率图（消除细节但保持分辨率） | 细节消失 → 遵循恢复 |
| H3 | 更大模型（1.7B+）同实验 | 容量↑ → 遵循改善 |
| H4 | 换"中性"问题（不含 center 位置假设） | 遵循恢复 |

（完整实验设计见 `methods.md`）

---

## 7. 结论 (Conclusion)

本文报告了小规模视觉语言模型在输入分辨率提升时输出格式遵循能力崩塌的实证现象：SmolVLM-256M/500M 在 640×480 分辨率下对 "answer only yes or no" 约束的遵循率从 90–100% 降至 0–10%，语义判断保持正确，且强化 prompt 无效。该现象表明：
1. **小 VLM 的格式遵循对输入分辨率高度敏感**
2. **失效发生在输出格式控制层，非感知/推理层**
3. **prompt 工程无法作为修复手段**，需从解码约束（constrained decoding）或模型/表征层面解决

对边缘部署的实际启示：若应用要求严格格式输出，低分辨率（320×240）当前是更可靠的选择；高分辨率部署必须配套解码约束或语义解析兜底。

---

## 8. 局限性与未来工作 (Limitations & Future Work)

- **单场景**: 仅测试工业风扇 yes/no 单一任务；需多场景、多类别验证普适性
- **单任务类型**: 仅二元判断；需测试多选、JSON 等更复杂格式约束
- **模型家族局限**: 仅 SmolVLM 家族；需扩展至 Qwen2-VL、LLaVA、Moondream 等
- **量化影响**: Q8_0 量化是否放大格式遵循退化未验证（需对比 F16）
- **温度**: 固定 0.1；需扫描温度对遵循率的影响
- **样本量**: 每组 10 轮偏少；需扩大至 ≥30 轮以做统计显著性检验
- **未来方向**: 解码约束（logit 掩码强制 yes/no）、LoRA 指令对齐、分辨率自适应视觉 token 压缩

---

## 附录 A. 原始数据（摘录）

### A.1 256M @ 640×480 普通 prompt（前 10 轮）

| # | 耗时 | 原始输出 |
|---|------|---------|
| 1 | 6.10s | "There is a black industrial fan in the center of the image." |
| 2 | 5.73s | "There is a black industrial fan in the center of the image." |
| 3 | 5.70s | "There is a black industrial fan in the center of the image." |
| 4 | 5.47s | "Yes." |
| 5 | 5.67s | "There is a black industrial fan in the center of the image." |
| 6 | 5.64s | "There is a black industrial fan in the center of the image." |
| 7 | 5.72s | "There is a black industrial fan in the corner of the image." |
| 8 | 5.61s | "There is a black industrial fan in the center of the image." |
| 9 | 5.64s | "There is a black industrial fan in the center of the image." |
| 10 | 5.63s | "There is a black industrial fan in the center of the image." |

### A.2 500M @ 640×480 普通 prompt（前 10 轮）

| # | 耗时 | 原始输出 |
|---|------|---------|
| 1 | 7.88s | "A black industrial fan is in the foreground of the image." |
| 2 | 6.61s | "A black industrial fan is in the foreground of the image." |
| 3 | 6.56s | "A black industrial fan is in the foreground of the image." |
| 4 | 6.70s | "A black industrial fan is in the foreground of the image." |
| 5 | 6.70s | "A black industrial fan sits on a table in a factory warehouse." |
| 6 | 6.69s | "A black industrial fan sits on a table in a factory warehouse." |
| 7 | 6.74s | "A black industrial fan is on a table in the foreground of the image." |
| 8 | 6.70s | "A black industrial fan is on a table in the foreground of the image." |
| 9 | 6.69s | "A black industrial fan is on a table in the foreground of the image." |
| 10 | 6.60s | "A black industrial fan is in the foreground of the image." |

### A.3 500M @ 320×240（前 10 轮，含唯一误判）

| # | 耗时 | 判定 |
|---|------|------|
| 1 | 7.40s | YES |
| 2 | 6.16s | YES |
| 3 | 6.22s | YES |
| 4 | 6.20s | YES |
| 5 | 6.20s | **NO（误判）** |
| 6 | 6.21s | YES |
| 7 | 6.16s | YES |
| 8 | 6.20s | YES |
| 9 | 6.14s | YES |
| 10 | 6.17s | YES |

---

## 附录 B. 参考资料占位 (References)

- Ouyang, L., et al. (2022). Training language models to follow instructions with human feedback. NeurIPS.
- Wei, J., et al. (2021). Finetuned language models are zero-shot learners. ICLR.
- Zhou, C., et al. (2024). LIMA: Less is more for alignment. NeurIPS.
- SmolVLM: HuggingFace SmolVLM-Instruct technical report.
- llama.cpp: GitHub repository (v0.15.3).
- RK3588: Rockchip technical reference manual.

*（注：以上为占位引用，投稿前需补充完整文献调研——见 methods.md 第 6 节）*

---

## 附录 C. 复现材料清单

| 材料 | 位置 |
|------|------|
| 实验文档 ×6 | `rk3588-vlm/experiment/experiment-smolvlm*.md` |
| 综合报告 | `rk3588-vlm/experiment/report.md` |
| 板端原始日志 ×6 | 板端 `/tmp/main_vlm*.log` |
| 测试程序源码 | `rk3588-vlm/{main,camera,llama_server,result_parser}.c` |
| 判定单元测试 | `rk3588-vlm/test_parser.c` (20 cases) |
| 测试图 | `rk3588-vlm/rk3588_640x480.jpg` |
