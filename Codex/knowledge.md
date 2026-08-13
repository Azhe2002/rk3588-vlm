# VLM 研发学习路线：从 RK3588 板端实验到独立模型研发

> 适用对象：已经能运行本仓库，希望系统学习视觉语言模型（VLM），最终能够独立完成数据、训练、评测、压缩和板端部署的人。
>
> 主线项目：RK3588 + Linux + 摄像头 + llama.cpp/llama-server + SmolVLM + C/Python 实验工具。
>
> 建议周期：24～32 周。不要把“看完资料”当成完成；每一阶段都必须留下代码、实验记录和结论。

---

## 1. 最终要获得什么能力

完成这条路线后，你应当能够独立回答并验证下面的问题：

1. 一张摄像头图像经过哪些步骤，才会变成 VLM 输出的文字？
2. Vision Encoder、Connector、LLM、Chat Template 和解码器分别做什么？
3. 为什么相同图片、相同提示词，仅改变 image/text 顺序就可能得到完全不同的结果？
4. 如何区分模型失败、提示词失败、解析器失败和实验设计失败？
5. 如何构造训练集，使用 SFT/LoRA 微调 VLM，并避免数据泄漏？
6. 如何比较 FP16、Q8、Q4 模型的语义精度、速度、内存和功耗？
7. llama.cpp 的 CPU/GPU 路径与 RKNN/RKLLM 的 NPU 路径有什么区别？
8. 如何把一个现象转化为假设、对照实验、统计检验和可复现论文结论？
9. 如何阅读一个新 VLM 的配置、模型代码、处理器、模板和部署实现？
10. 如何设计一个自己的轻量 VLM 研究课题，而不只是调用现成模型？

建议把能力目标分成四级：

| 等级 | 能力 | 可验证产出 |
|---|---|---|
| L1 使用者 | 能正确调用 VLM | 一套可复现推理命令和请求样例 |
| L2 工程者 | 能定位全链路问题 | 带日志、指标和故障注入的推理程序 |
| L3 研究者 | 能设计有效对照实验 | 数据、脚本、统计结果和实验报告 |
| L4 研发者 | 能训练、压缩并部署模型 | 自建数据集、适配器/模型、评测表、板端程序 |

---

## 2. 先建立一张完整地图

VLM 不是“一个会看图的 LLM”这么简单。一次端到端推理至少经过以下链路：

```text
现实场景
  ↓
摄像头 / 图片文件
  ↓  解码、裁剪、缩放、颜色归一化
图像张量 [B, C, H, W]
  ↓
Vision Encoder（例如 SigLIP/ViT）
  ↓  patch 特征
Connector / Projector / Pixel Shuffle
  ↓  视觉 token
Multimodal Chat Template
  ↓  [图像 token + 文本 token] 序列
Decoder-only LLM
  ↓  logits
采样器 / Grammar / JSON Schema
  ↓
文本或结构化结果
  ↓
业务解析、统计评测、控制动作
```

本仓库又在模型链路外增加了一个嵌入式系统链路：

```text
V4L2 摄像头
  → GStreamer 抓帧
  → JPEG 文件
  → Base64 / HTTP JSON
  → llama-server
  → llama.cpp + GGUF + mmproj
  → JSON 响应
  → C 解析器
  → 终端输出或后续控制
```

以后排查问题时，永远先问“故障属于哪一层”，不要直接把所有异常归因于模型。

| 层 | 常见问题 | 最小验证方法 |
|---|---|---|
| 采集 | 曝光、模糊、旧帧、颜色错误 | 保存原图并人工查看 |
| 预处理 | 拉伸、裁剪、通道顺序错误 | 输出张量形状和像素统计 |
| 模板 | image/text 顺序、特殊 token 错误 | 打印最终消息结构 |
| 模型 | 能力不足、量化退化 | 用高精度模型做同样请求 |
| 解码 | 随机性、格式漂移 | 固定 seed，使用 grammar |
| 解析 | `No` 被当成失败 | 保存原始响应后离线重放 |
| 统计 | 样本不独立、结论过度外推 | 使用配对设计和置信区间 |

---

## 3. 学习方法：每一阶段都走完整闭环

每个知识点使用同一个六步循环：

1. **概念**：能用自己的话解释它解决什么问题。
2. **形状**：能写出输入、输出 tensor 的形状。
3. **最小代码**：不用大框架封装，写一个可以观察中间结果的版本。
4. **仓库映射**：指出它在本仓库哪个文件、哪个请求字段或哪个实验中出现。
5. **破坏实验**：故意改变一个变量，预测并观察结果。
6. **归档**：记录环境、输入、输出、失败原因和下一步。

推荐学习笔记模板：

```markdown
# 主题

## 我能解释的概念
- 

## 输入和输出形状
- input:
- output:

## 最小代码
- 文件：
- 运行命令：

## 我修改的唯一变量
- 

## 结果
- 预期：
- 实际：
- 原始数据路径：

## 结论边界
- 能说明什么：
- 不能说明什么：

## 下一个问题
- 
```

这段模板的作用是阻止“只记结论、不记证据”。VLM 的输入模板、库版本和图像处理差异很大，缺少这些信息时，结果很难复现。

---

# 第一部分：工程基础

## 4. 阶段 0：先读懂当前仓库（1～2 周）

### 4.1 学习目标

- 能在 Linux 上通过 SSH 操作 RK3588。
- 能读懂 C 程序的模块边界、资源生命周期和错误码。
- 能理解 HTTP JSON 请求以及 Base64 图像的代价。
- 能读懂 Python 实验脚本、JSONL 数据和统计输出。
- 能画出本仓库从 `main()` 到最终解析结果的调用图。

### 4.2 推荐阅读顺序

1. `README.md`：先理解项目目标和运行方式。
2. `main.c`：找到主流程和资源生命周期。
3. `camera.h` / `camera.c`：理解抓帧、子进程和文件输出。
4. `llama_server.h` / `llama_server.c`：理解 server 管理、HTTP 请求和响应。
5. `result_parser.h` / `result_parser.c`：理解业务结果与原始模型文本的边界。
6. `test_parser.c`：理解怎样把解析器变成可独立验证的单元。
7. `experiment/metrics.py`：理解实验指标为什么不能只看一个 `success` 字段。
8. `experiment/run_s2e1.py` 与 `experiment/s2e1_analyze.py`：理解采集和分析为什么要分离。
9. `experiment/paper/main.tex`：从论文反向寻找每个结论对应的数据和脚本。

### 4.3 C 语言必须真正掌握的内容

- 指针、数组、字符串终止符和缓冲区边界。
- 栈与堆，`malloc/free` 的所有权。
- `FILE *`、文件描述符、管道、进程和信号。
- `fork/exec/waitpid` 或等价的子进程管理思想。
- 返回值、`errno`、超时与清理路径。
- 头文件声明、源文件实现、链接过程。
- CMake、交叉编译、动态库搜索路径。

最小资源清理模式：

```c
int run_once(void) {
    char *response = NULL;
    int rc = -1;

    response = request_vlm();
    if (response == NULL) {
        goto cleanup;
    }

    if (parse_response(response) != 0) {
        goto cleanup;
    }

    rc = 0;

cleanup:
    free(response);
    return rc;
}
```

代码作用：

- `response` 初始化为 `NULL`，使得任何失败路径都可以安全调用 `free`。
- `rc` 默认表示失败，只有所有步骤成功后才改为 `0`。
- `goto cleanup` 在 C 的资源管理中是合理用法，它把释放逻辑集中到一个出口。
- 以后增加文件、CURL handle 或子进程时，也应在同一清理区按相反顺序释放。

### 4.4 Linux 与 Git 必须掌握的命令

```bash
# 查看系统与 CPU 架构
uname -a
uname -m

# 查看进程、内存和动态库
ps aux | grep llama-server
free -h
ldd ./rk3588_vlm

# 查看视频设备和格式
v4l2-ctl --list-devices
v4l2-ctl --device /dev/video0 --list-formats-ext

# 查看 Git 当前状态与最近提交
git status --short --branch
git log --oneline --decorate -10
git diff
```

代码作用：

- `uname -m` 可确认程序应编译为 `aarch64`，避免把 x86_64 可执行文件复制到板端。
- `ldd` 用于定位“文件存在但无法运行”的动态库问题。
- `v4l2-ctl` 先确认摄像头能力，再设计 GStreamer pipeline。
- `git status` 和 `git diff` 应在每次实验前后运行，保证结果能映射到明确代码版本。

### 4.5 阶段验收

你需要提交一份自己的调用链说明，其中至少回答：

- 谁启动和关闭 `llama-server`？
- 摄像头帧写到哪里？什么时候可能读到旧帧？
- 图像怎样进入 JSON？
- 原始 HTTP 响应在哪里第一次被解析？
- `No`、`No.`、一段描述文本分别会被当前指标怎样分类？
- 程序异常退出时有哪些资源可能未释放？

---

## 5. 阶段 1：Python、数据与可复现实验（1～2 周）

### 5.1 需要掌握

- Python 类型、函数、类、异常和上下文管理器。
- `argparse` 命令行接口。
- `dataclasses` 表达实验配置。
- JSON/JSONL、CSV、路径和时间戳。
- NumPy、Pandas、Matplotlib 的基础使用。
- 虚拟环境、依赖锁定和随机种子。

实验程序不要把配置散落在代码中。先建立明确的配置对象：

```python
from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class RunConfig:
    model: str
    content_order: str
    resolution: int
    seed: int
    temperature: float = 0.0


cfg = RunConfig(
    model="SmolVLM-500M-Instruct-Q8_0",
    content_order="image_text",
    resolution=512,
    seed=42,
)

Path("runs").mkdir(exist_ok=True)
Path("runs/config.json").write_text(
    json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
    encoding="utf-8",
)
```

代码作用：

- `frozen=True` 防止实验运行途中悄悄修改配置。
- 把模型、内容顺序、分辨率和随机性都写入配置，避免只靠文件名猜测条件。
- `asdict` 让配置可以直接持久化；分析脚本应读取配置，而不是依赖记忆。

### 5.2 为什么选择 JSONL

JSONL 每一行是一个独立 JSON 对象，适合长时间实验：即使中途断电，已经写入的行仍可读取。

```python
import json
import time


def append_record(path: str, record: dict) -> None:
    record = {
        "timestamp": time.time(),
        **record,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


append_record(
    "runs/raw.jsonl",
    {
        "sample_id": "negative_001",
        "image_sha256": "...",
        "request": {"seed": 42, "cache_prompt": False},
        "raw_response": {"content": "No"},
        "latency_ms": 1832.5,
    },
)
```

代码作用：

- 保存 `raw_response`，以后修复解析器时可以离线重算，不必重新跑板端。
- 保存 `image_sha256`，证明不同记录是否真的使用同一张图。
- `flush()` 降低断电时丢失已完成样本的风险；更严格时还可以调用 `os.fsync()`。

### 5.3 阶段验收

- 写一个脚本扫描 `experiment/` 下的 JSONL。
- 输出每个实验的样本数、模型、场景、内容顺序、分辨率、seed 和响应类别。
- 故意插入一条损坏 JSON，程序应报告行号并继续或明确终止，不能静默忽略。

---

# 第二部分：数学与深度学习基础

## 6. 阶段 2：只学 VLM 真正会用到的数学（2～3 周）

### 6.1 线性代数

重点理解：

- 标量、向量、矩阵、张量。
- shape、广播、转置和矩阵乘法。
- 点积代表相似性的直觉。
- 范数、归一化、余弦相似度。
- 线性层 `y = xW + b`。
- 特征值/SVD 只需理解其与低秩近似、LoRA 的关系。

必须形成“先看形状，再看数值”的习惯。例如自注意力中：

```text
X: [batch, sequence, hidden]
Wq, Wk, Wv: [hidden, head_dim]
Q, K, V: [batch, sequence, head_dim]
Q @ K^T: [batch, sequence, sequence]
attention @ V: [batch, sequence, head_dim]
```

### 6.2 概率与统计

重点理解：

- 条件概率与最大似然。
- 离散分布、均值、方差。
- softmax、log、log probability。
- 交叉熵和负对数似然。
- 抽样误差、置信区间、假设检验。
- 配对样本和独立样本的区别。

手写稳定 softmax：

```python
import torch


def stable_softmax(logits: torch.Tensor) -> torch.Tensor:
    shifted = logits - logits.max(dim=-1, keepdim=True).values
    exp = shifted.exp()
    return exp / exp.sum(dim=-1, keepdim=True)


logits = torch.tensor([[2.0, 1.0, -1.0]])
print(stable_softmax(logits))
```

代码作用：

- softmax 把任意 logits 转成和为 1 的概率。
- 先减最大值不会改变 softmax 结果，却能避免 `exp(大数)` 溢出。
- VLM 生成下一个 token 时，模型输出的就是整个词表的 logits。

交叉熵最小示例：

```python
import torch
import torch.nn.functional as F

logits = torch.tensor([[2.0, 1.0, -1.0]], requires_grad=True)
target = torch.tensor([0])

loss = F.cross_entropy(logits, target)
loss.backward()

print("loss:", loss.item())
print("dL/dlogits:", logits.grad)
```

代码作用：

- `target=0` 表示正确类别是第 0 类。
- 交叉熵会提高正确类别相对概率、压低其他类别相对概率。
- `backward()` 计算梯度；优化器随后用梯度更新参数。
- 语言模型训练只是把“类别”扩大为词表，并在许多 token 位置重复这一过程。

### 6.3 微积分与优化

无需先学完整高等数学，但必须理解：

- 导数是局部变化率，梯度是多变量方向。
- 链式法则让误差从输出逐层传播到参数。
- SGD、Momentum、AdamW 的区别。
- learning rate、warmup、weight decay、gradient clipping。
- 欠拟合、过拟合以及训练/验证曲线。

### 6.4 阶段验收

不用查资料，解释以下问题：

- 为什么 attention score 要除以 `sqrt(d_k)`？
- 为什么不能直接对很大的 logits 调用 `exp`？
- temperature 变小时概率分布为什么更尖锐？
- LoRA 为什么被称为低秩更新？
- 20/20 成功为什么仍不等于真实成功率必然为 100%？

---

## 7. 阶段 3：PyTorch 与神经网络训练（2～3 周）

### 7.1 学习顺序

1. Tensor 创建、dtype、device、shape。
2. `nn.Module`、参数和前向传播。
3. autograd 和计算图。
4. loss、optimizer、训练循环。
5. `Dataset`、`DataLoader`、batch 和 shuffle。
6. `train()`、`eval()`、`no_grad()`。
7. checkpoint、恢复训练和混合精度。

### 7.2 一个必须逐行看懂的训练循环

```python
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

torch.manual_seed(42)

x = torch.randn(256, 8)
y = (x[:, 0] + 0.5 * x[:, 1] > 0).long()

loader = DataLoader(
    TensorDataset(x, y),
    batch_size=32,
    shuffle=True,
)

model = nn.Sequential(
    nn.Linear(8, 32),
    nn.ReLU(),
    nn.Linear(32, 2),
)
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
criterion = nn.CrossEntropyLoss()

for epoch in range(20):
    model.train()
    total_loss = 0.0

    for features, labels in loader:
        optimizer.zero_grad()
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * features.size(0)

    mean_loss = total_loss / len(loader.dataset)
    print(f"epoch={epoch:02d} loss={mean_loss:.4f}")
```

代码作用：

- `manual_seed` 固定参数初始化和数据打乱的随机源之一。
- `DataLoader` 把 256 条样本拆成 batch；batch 是训练吞吐和梯度噪声的重要变量。
- `zero_grad()` 必须在每次更新前清空旧梯度，否则 PyTorch 默认累加梯度。
- `loss.backward()` 只计算梯度，`optimizer.step()` 才真正修改参数。
- `loss.item() * batch_size` 后再除总样本数，可得到按样本加权的 epoch loss。

验证阶段：

```python
model.eval()
correct = 0

with torch.no_grad():
    logits = model(x)
    pred = logits.argmax(dim=-1)
    correct = (pred == y).sum().item()

print("accuracy:", correct / len(y))
```

代码作用：

- `eval()` 切换 Dropout、BatchNorm 等层的行为，但不会自动关闭梯度。
- `no_grad()` 才会减少验证阶段的计算图和内存开销。
- 训练指标不能代替验证指标；以后微调 VLM 时必须分开记录。

### 7.3 阶段项目

用你自己采集的板端图片做一个二分类器。此时先不要使用 VLM：

- 任务可以是“目标存在/不存在”。
- 固定 train/validation/test 划分。
- 输出混淆矩阵，而不只输出 accuracy。
- 找出 10 张最有信心但预测错误的图。

这个项目会让你理解监督学习最基本的闭环，并为以后判断“是否真的需要 VLM”建立基线。

---

# 第三部分：Transformer、视觉与 VLM

## 8. 阶段 4：Transformer 与 LLM（3～4 周）

### 8.1 Tokenizer 与自回归生成

LLM 不直接读取字符串。基本过程是：

```text
文本 → tokenizer → token ids → embedding → Transformer blocks
     → 下一个 token 的 logits → 采样 → 新 token → 重复
```

需要掌握：

- BPE/SentencePiece 的基本思想。
- BOS/EOS/PAD 和模型自定义特殊 token。
- prompt token 与 generated token。
- causal mask：当前位置不能看未来 token。
- teacher forcing 与 next-token prediction。
- context length 与位置编码。
- prefill 与 decode 的性能差异。
- KV cache 为什么能加速逐 token 解码。

### 8.2 手写缩放点积注意力

```python
import math
import torch


def scaled_dot_product_attention(q, k, v, causal=False):
    # q/k/v: [batch, heads, sequence, head_dim]
    scores = q @ k.transpose(-2, -1)
    scores = scores / math.sqrt(q.size(-1))

    if causal:
        seq_len = q.size(-2)
        future = torch.triu(
            torch.ones(seq_len, seq_len, dtype=torch.bool),
            diagonal=1,
        )
        scores = scores.masked_fill(future, float("-inf"))

    weights = torch.softmax(scores, dim=-1)
    output = weights @ v
    return output, weights
```

代码作用：

- `q @ k^T` 计算每个 token 对其他 token 的相关性。
- 除以 `sqrt(head_dim)` 避免维度增大后点积幅度过大，softmax 过早饱和。
- causal mask 把未来位置设为负无穷，softmax 后权重为 0。
- `weights @ v` 汇总被关注位置携带的信息。
- 多头注意力让不同 head 学习不同类型的关系。

### 8.3 解码参数

| 参数 | 作用 | 实验建议 |
|---|---|---|
| `temperature` | 缩放 logits | 语义对照实验先设 0 或极低 |
| `top_k` | 只保留概率最高的 k 个 token | 创作任务使用，严格分类少用 |
| `top_p` | 保留累计概率达到 p 的候选 | 与 temperature 一起影响随机性 |
| `seed` | 固定伪随机序列 | 只有其他条件相同才有比较意义 |
| `max_tokens` | 限制生成长度 | 二分类应非常小，描述任务应足够大 |
| `stop` | 遇到指定序列终止 | 防止多余解释，但不能保证语义正确 |

温度的数学形式：

```text
p_i = softmax(logit_i / T)
```

- `T < 1`：分布更尖锐，输出更确定。
- `T > 1`：分布更平坦，输出更多样。
- `T → 0`：趋近选择最大 logit，但具体 API 对 `temperature=0` 的实现要查文档。

### 8.4 为什么内容顺序会影响 VLM

本仓库的 S2-E1 发现非常适合作为 Transformer 课程案例：在同一图像和同一问题下，`text → image` 与 `image → text` 的行为显著不同。

对 decoder-only 多模态模型，可以用下面的简化序列理解：

```text
方案 A: [问题 token] [图像 token] [回答起始 token]
方案 B: [图像 token] [问题 token] [回答起始 token]
```

最终回答位置理论上能看到此前所有 token，但两种顺序仍不等价：

- 训练时更常见的模板顺序会得到更匹配的条件分布。
- 位置编码改变了图像和问题的相对位置。
- Processor/Chat Template 可能在不同内容项间插入不同分隔 token。
- 视觉特征与文字指令的融合路径会改变。
- 模型小、量化强或图像细节弱时，模板偏差更容易放大。

因此“请求 JSON 都包含同一张图和同一句话”并不等于“模型接收到同一个条件”。模板本身就是模型的一部分。

### 8.5 阶段验收

- 给定 `[B, H, S, D]` 的 Q/K/V，写出每一步形状。
- 用 4 个 token 打印 causal attention matrix。
- 改变 temperature，画出 3 个候选 token 的概率曲线。
- 用模型自带 Processor 打印 `image_text` 与 `text_image` 模板的 token ids，并定位差异。

---

## 9. 阶段 5：计算机视觉基础（2～3 周）

### 9.1 必须理解的图像概念

- RGB/BGR/YUV 与颜色空间转换。
- 图像宽高、stride、通道排列 `HWC`/`CHW`。
- uint8 到 float 的归一化。
- resize、crop、letterbox、插值算法。
- JPEG 压缩、模糊、噪声、曝光和动态范围。
- 卷积的局部感受野。
- ViT 如何把图像切成 patch token。
- 数据增强何时保持标签，何时破坏标签。

### 9.2 手写 patchify

```python
import torch


def patchify(images: torch.Tensor, patch_size: int) -> torch.Tensor:
    # images: [B, C, H, W]
    b, c, h, w = images.shape
    assert h % patch_size == 0
    assert w % patch_size == 0

    patches = images.unfold(2, patch_size, patch_size)
    patches = patches.unfold(3, patch_size, patch_size)
    # [B, C, H/P, W/P, P, P]

    patches = patches.permute(0, 2, 3, 1, 4, 5)
    # [B, H/P, W/P, C, P, P]

    return patches.reshape(
        b,
        (h // patch_size) * (w // patch_size),
        c * patch_size * patch_size,
    )


x = torch.randn(2, 3, 224, 224)
tokens = patchify(x, patch_size=16)
print(tokens.shape)  # [2, 196, 768]
```

代码作用：

- `unfold` 从高、宽两个维度提取不重叠窗口。
- `224 / 16 = 14`，所以每张图产生 `14 × 14 = 196` 个 patch。
- 每个 patch 展平后有 `3 × 16 × 16 = 768` 个值。
- 实际 ViT 会再使用线性层把每个 patch 映射到 hidden size，并加入位置编码。

### 9.3 分辨率不是一个简单数字

必须区分至少四种分辨率：

1. 摄像头原始分辨率。
2. 保存 JPEG 的分辨率。
3. API/模板交给 Processor 的图像尺寸。
4. Vision Encoder 实际看到的 patch/grid 尺寸。

例如输入 JPEG 是 160×160，并不一定意味着 encoder 只计算 160×160。Processor 可能把它放大到固定尺寸。仓库实验观察到固定 512×512 预处理时，原图低分辨率的影响主要变成“插值后细节是否还存在”，而不是 token 数一定减少。

### 9.4 图像质量审计

可先实现简单、可解释的指标：

```python
from PIL import Image
import numpy as np


def image_stats(path: str) -> dict:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    gray = rgb.mean(axis=2)

    dx = np.abs(gray[:, 1:] - gray[:, :-1]).mean()
    dy = np.abs(gray[1:, :] - gray[:-1, :]).mean()

    return {
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "mean_luma": float(gray.mean()),
        "contrast": float(gray.std()),
        "edge_strength": float((dx + dy) / 2),
    }
```

代码作用：

- 宽高检测错文件或异常 resize。
- 平均亮度和对比度可发现黑帧、过曝和场景变化。
- `edge_strength` 是很粗糙的细节代理，不能直接等同于“语义清晰度”。
- 这些指标用于数据审计，不应替代人工查看或任务指标。

### 9.5 阶段项目

对同一张板端图像生成以下受控版本：

- 160、224、320、384、512、640 分辨率。
- 高斯模糊 3 个等级。
- JPEG quality 3 个等级。
- 亮度 3 个等级。

分别保存图像质量指标和 VLM 响应。只改变一个因素，禁止把分辨率、压缩率和内容顺序一起改。

---

## 10. 阶段 6：VLM 架构（3～4 周）

### 10.1 三个核心模块

#### Vision Encoder

把像素变成视觉特征。常见实现基于 ViT、CLIP/SigLIP 系列。

```text
[B, 3, H, W]
  → patch embedding
  → vision transformer
  → [B, N_visual, D_vision]
```

#### Connector / Projector

把视觉特征映射到 LLM 能接收的 hidden size，并可能压缩 token 数。

```text
[B, N_visual, D_vision]
  → projection / resampler / pixel shuffle
  → [B, N_image_tokens, D_text]
```

#### Language Model

把视觉 token 和文本 token 放入统一上下文，逐 token 生成答案。

```text
[image tokens, question tokens]
  → decoder blocks
  → vocabulary logits
  → answer tokens
```

### 10.2 需要对比的架构家族

| 架构思想 | 代表方向 | 研究时关注 |
|---|---|---|
| 视觉编码器 + 线性投影 + LLM | LLaVA 类 | 简单、容易微调，视觉 token 较多 |
| 查询 token / Q-Former | BLIP-2 类 | 用少量查询压缩视觉信息 |
| Resampler / Perceiver | Flamingo、Idefics 类 | 多图与可变视觉输入的压缩 |
| 原生统一多模态 token | 新一代统一模型 | 训练复杂，模态边界更弱 |

学习时不要只记模型名。对任何新 VLM，都回答：

- 视觉编码器是什么？是否冻结？
- 输入图像怎样 resize/crop？
- 一个图像产生多少视觉 token？
- Connector 是线性层、MLP、Q-Former 还是 resampler？
- 视觉 token 在对话模板的什么位置？
- LLM 是 decoder-only 还是 encoder-decoder？
- 预训练、指令微调分别用了哪些类型的数据？

### 10.3 SmolVLM/Idefics3 的学习重点

本仓库使用 SmolVLM 256M/500M 的 GGUF 变体。你应同时阅读：

- Hugging Face 原始模型的 `config.json`。
- `preprocessor_config.json`、`processor_config.json`。
- `chat_template.json`。
- llama.cpp 转换后的 GGUF 元数据。
- 独立 `mmproj` 文件的来源和量化类型。

配置探索代码：

```python
from transformers import AutoConfig, AutoProcessor

model_id = "HuggingFaceTB/SmolVLM-500M-Instruct"

config = AutoConfig.from_pretrained(model_id)
processor = AutoProcessor.from_pretrained(model_id)

print(config)
print(processor)
print("image token id:", getattr(config, "image_token_id", None))
print("scale factor:", getattr(config, "scale_factor", None))
```

代码作用：

- `AutoConfig` 只加载配置，不加载全部权重，适合先理解架构。
- `image_token_id` 表示视觉占位符怎样进入文本 token 序列。
- `scale_factor` 等字段需要结合模型实现阅读，不能仅凭名称猜行为。
- 原始 Hugging Face 配置是理解 GGUF 转换结果的重要参照物。

查看真实多模态模板：

```python
from transformers import AutoProcessor

processor = AutoProcessor.from_pretrained(
    "HuggingFaceTB/SmolVLM-500M-Instruct"
)

messages = [
    {
        "role": "user",
        "content": [
            {"type": "image"},
            {"type": "text", "text": "Is the target present?"},
        ],
    }
]

prompt = processor.apply_chat_template(
    messages,
    add_generation_prompt=True,
    tokenize=False,
)
print(prompt)
```

代码作用：

- 不要手写猜测模型模板；应优先调用模型 Processor。
- `tokenize=False` 便于观察插入了哪些特殊标记。
- 再分别构造 `text_image` 和 `image_text`，比较模板差异，这正对应仓库 S2-E1。

### 10.4 视觉 token 预算

上下文预算可粗略表示为：

```text
context_used = system_tokens
             + text_tokens
             + image_tokens
             + generated_tokens
```

多图、视频或高分辨率输入会快速增加 image tokens。需要记录：

- 单图视觉 token 数。
- 最大上下文长度。
- 最大生成长度。
- KV cache 内存。
- prefill 时间与 decode 时间。

### 10.5 阶段验收

任选两个轻量 VLM，写出结构对比表，并用代码打印：

- 模型总参数量与可训练参数量。
- vision hidden size、text hidden size。
- image token id 和模板。
- 输入 1 张 512×512 图片后的 token 数。
- vision encoder、connector、LLM 各自的输出形状。

---

# 第四部分：推理系统与实验方法

## 11. 阶段 7：llama.cpp、HTTP 与结构化解码（2～3 周）

### 11.1 认识两种 server 所有权模式

#### Managed 模式

应用负责启动、健康检查和停止 `llama-server`。

适合单进程演示，但必须处理：

- server 启动超时。
- 端口冲突。
- 子进程异常退出。
- 主程序收到 SIGINT/SIGTERM 后的清理。

#### External 模式

server 由 systemd、Docker 或运维脚本管理，应用只发请求。

适合生产环境，优点是：

- 模型不用每次应用启动都重新加载。
- 多个客户端可复用服务。
- 日志、重启和权限边界更清楚。

### 11.2 image-first 请求的最小结构

下面强调的是内容项顺序，而不是 JSON 键顺序：

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,BASE64_DATA"
          }
        },
        {
          "type": "text",
          "text": "Is the target object present? Answer Yes or No."
        }
      ]
    }
  ],
  "temperature": 0,
  "seed": 42,
  "cache_prompt": false,
  "max_tokens": 4
}
```

字段作用：

- `content` 数组先 image 后 text，对应当前仓库实验中更可靠的顺序。
- data URL 把图像嵌入请求，简单但会使数据体积约增加三分之一。
- `temperature` 与 `seed` 控制解码随机性，但不能修复错误模板。
- `cache_prompt=false` 适合优先保证多图实验的隔离性；开启缓存前必须做正确性验证。
- `max_tokens=4` 限制二分类任务输出长度，减少无关解释。

Python 请求示例：

```python
import base64
import requests


def as_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


payload = {
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": as_data_url("frame.jpg")},
                },
                {
                    "type": "text",
                    "text": "Is the target present? Answer Yes or No.",
                },
            ],
        }
    ],
    "temperature": 0,
    "seed": 42,
    "cache_prompt": False,
    "max_tokens": 4,
}

response = requests.post(
    "http://127.0.0.1:8080/v1/chat/completions",
    json=payload,
    timeout=60,
)
response.raise_for_status()
body = response.json()

print(body["choices"][0]["message"]["content"])
print(body.get("usage"))
```

代码作用：

- `raise_for_status()` 把 HTTP 失败和模型语义失败分开。
- 整个 `body` 应写入原始日志，终端只打印 content 不足以审计。
- `timeout` 是嵌入式系统必须显式设计的参数，不能无限等待。
- `usage` 可帮助统计 prompt/image token 和生成 token，但字段支持要以所用 llama.cpp 版本为准。

### 11.3 Prompt、解析器与 Grammar 是三个不同层次

```text
Prompt:    “请只回答 Yes 或 No”       → 软约束
Grammar:   只允许生成 Yes/No          → 解码硬约束
Parser:    把最终字符串映射为布尔值    → 业务解释
```

GBNF 示例：

```gbnf
root ::= "Yes" | "No"
```

代码作用：

- grammar 可保证输出格式来自有限集合。
- grammar 不能保证模型选择的答案在语义上正确。
- parser 仍需处理 HTTP 错误、空内容和协议变化。
- 不要再用“是否包含 Yes”作为唯一成功标准；正确答案可能是 `No`。

如果需要 JSON：

```json
{
  "present": false,
  "confidence": 0.82
}
```

应优先使用 server 支持的 JSON Schema/grammar 约束，并对范围、缺失字段和类型进行验证。注意：模型自己输出的 `confidence` 通常没有经过校准，不能直接当成真实概率。

### 11.4 解析分层

建议把结果分成以下字段：

```python
from dataclasses import dataclass
from typing import Literal


@dataclass
class ParsedResult:
    transport_ok: bool
    protocol_ok: bool
    format_class: Literal["yes", "no", "other", "empty"]
    predicted_label: bool | None
    semantic_correct: bool | None
    raw_text: str
```

代码作用：

- `transport_ok` 只描述 HTTP/进程是否成功。
- `protocol_ok` 描述响应 JSON 是否符合接口结构。
- `format_class` 描述输出形式，不等于答案正确性。
- `semantic_correct` 必须结合 ground truth 才能得到。
- 分层以后，`No` 不会再被误记为“推理失败”。

### 11.5 阶段验收

- 对同一图像分别发送 image-first 和 text-first 请求。
- 保存完整请求、完整响应、server commit、模型 SHA256 和时间。
- 为 Yes/No 添加 grammar。
- 注入 HTTP 500、超时、空响应、格式外文本，验证分类是否正确。

---

## 12. 阶段 8：实验设计与统计（3～4 周）

### 12.1 先写问题，再跑模型

一份合格实验卡必须包含：

```yaml
experiment_id: S3-E0
question: image-first 是否在新场景中仍优于 text-first？
hypothesis: image-first 的语义正确率更高
primary_metric: paired_semantic_accuracy
unit: unique_scene_image
factors:
  content_order: [image_text, text_image]
controlled:
  model: SmolVLM-500M-Instruct-Q8_0
  prompt: fixed
  resolution: 512
  temperature: 0
  cache_prompt: false
ground_truth:
  negative_scenes: 20
  positive_scenes: 20
stopping_rule: exactly 40 paired images
```

字段作用：

- `unit` 决定统计独立性；同一张图重复 20 次不等于 20 个独立场景。
- `primary_metric` 必须在看结果前确定，避免挑选最有利指标。
- `controlled` 明确哪些变量不能随条件一起变化。
- `stopping_rule` 防止看到显著结果就提前停止。

### 12.2 变量类型

- 自变量：研究者主动改变，如 content order。
- 因变量：观察结果，如 semantic correctness。
- 控制变量：模型、图像、prompt、seed、温度。
- 混杂变量：与自变量同时变化且也能影响结果，如分辨率和顺序同时变化。
- 中介变量：自变量通过它影响结果，如模板改变视觉 token 的相对位置。

### 12.3 配对设计

内容顺序实验应让同一张图片分别走两种顺序：

```text
image_001 → image_text → result A
image_001 → text_image → result B
image_002 → image_text → result A
image_002 → text_image → result B
```

这样可以消除不同图片难度带来的大量噪声。运行顺序最好随机化或 AB/BA 交替，避免温度、后台负载和设备热状态总偏向某个条件。

### 12.4 指标要分层

推荐至少报告：

| 指标 | 回答的问题 |
|---|---|
| transport success | 请求是否完成？ |
| protocol success | 响应结构是否可解析？ |
| exact format | 是否严格为目标格式？ |
| format word | 是否能识别 Yes/No？ |
| semantic correctness | 与真值是否一致？ |
| latency / TTFT / tok/s | 系统是否足够快？ |
| peak RSS | 内存是否可接受？ |
| power / temperature | 板端是否可持续运行？ |

二分类语义指标：

```python
def classification_counts(rows: list[dict]) -> dict:
    tp = fp = tn = fn = 0

    for row in rows:
        truth = row["ground_truth"]
        pred = row["predicted_label"]

        if truth and pred:
            tp += 1
        elif not truth and pred:
            fp += 1
        elif not truth and not pred:
            tn += 1
        else:
            fn += 1

    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
```

代码作用：

- confusion matrix 会揭示模型是偏向全答 Yes 还是全答 No。
- accuracy 在类别不平衡时会误导，因此还应计算 precision、recall、specificity 和 F1。
- 格式无法解析的样本不能偷偷删除；应单独报告或按预注册规则计错。

### 12.5 Wilson 置信区间

当成功数为 20/20 时，点估计是 100%，但真实成功率仍有不确定性。可计算 Wilson 区间：

```python
import math


def wilson_interval(successes: int, total: int, z: float = 1.96):
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            p * (1 - p) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return center - margin, center + margin


print(wilson_interval(20, 20))
```

代码作用：

- 区间表达有限样本下的估计不确定性。
- 它比简单的正态近似更适合成功率接近 0 或 1 的小样本情况。
- 区间仍不解决样本不独立问题；20 次重复同一静态图像不能替代 20 个独立场景。

### 12.6 McNemar 配对检验

比较同一批样本上的两个方法时，关键是“不一致对”：

```text
b = A 正确、B 错误的样本数
c = A 错误、B 正确的样本数
```

精确 McNemar 的二项形式可以这样计算：

```python
from math import comb


def exact_mcnemar_p(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0

    tail = sum(comb(n, k) for k in range(0, min(b, c) + 1))
    return min(1.0, 2.0 * tail / (2 ** n))
```

代码作用：

- 只分析两种方法结论不同的样本。
- 小样本时使用精确版本，不依赖渐近卡方近似。
- 显著性不等于效应大小；必须同时报告配对差值和原始计数。

### 12.7 从本仓库学到的研究方法

本仓库已有实验形成了一条非常重要的方法论：

1. 早期现象看起来像“低分辨率导致语义崩溃”。
2. S2-E0 先确认 server 的 grammar、seed、cache 和 usage 能力。
3. S2-E1 单独改变 content order，发现 text-first 与 image-first 有显著差异。
4. S2-E2 在更可靠的 image-first 条件下重新做分辨率消融。
5. 结果显示此前的“分辨率崩溃”包含明显交互/混杂，不能只归因于像素数量。
6. 数据审计又发现旧解析逻辑把合法的 `No` 与失败混为一谈。

这里最重要的不是某个模型最终答了什么，而是：

- 先验证测量工具，再验证科学假设。
- 原始响应永远保留，派生指标允许重算。
- 一个异常现象可能同时来自模板、图像和解析器。
- 新结论要写清适用范围，不能从少量固定场景外推到所有 VLM。

### 12.8 阶段验收

设计一次全新的多场景复现实验：

- 至少 20 个正样本场景、20 个负样本场景。
- 每张图对两种内容顺序做配对。
- 运行次序随机或 AB/BA 平衡。
- 预先写 primary metric 和 stopping rule。
- 输出原始 JSONL、审计报告、置信区间、McNemar 检验和失败图库。

---

# 第五部分：训练与模型研发

## 13. 阶段 9：数据集设计（2～3 周）

### 13.1 先定义任务分布

训练集不是“图片越多越好”。先写目标分布：

- 设备：哪些摄像头、焦距和图像格式？
- 场景：室内/室外、白天/夜晚、背景复杂度。
- 目标：大小、遮挡、姿态、材质。
- 负样本：相似物体、空场景、局部物体、文字干扰。
- 指令：中文、英文、同义问法。
- 输出：二分类、描述、框坐标或多轮对话。

### 13.2 防止数据泄漏

不能把相邻视频帧随机分到 train 和 test。它们几乎是同一张图，会制造虚假的高分。

正确做法是按以下更高层级切分：

```text
按拍摄 session 切分
  > 按场景切分
    > 按视频切分
      > 最后才是按单张图片
```

推荐记录数据 lineage：

```json
{
  "sample_id": "warehouse_cam2_20260813_00142",
  "image": "images/warehouse_cam2_00142.jpg",
  "session_id": "warehouse_cam2_20260813",
  "scene_id": "warehouse_shelf_07",
  "device_id": "rk3588_cam2",
  "label": {"target_present": false},
  "annotation_source": "human_double_checked",
  "sha256": "...",
  "split": "test"
}
```

字段作用：

- `session_id` 和 `scene_id` 支持按组切分，避免泄漏。
- `annotation_source` 区分人工真值、模型伪标签和未复核标签。
- `sha256` 用于检测重复图像和文件漂移。
- `split` 一旦正式确定，应版本化而不是每次训练随机重分。

### 13.3 VLM 对话训练格式

```python
sample = {
    "images": ["images/negative_001.jpg"],
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {
                    "type": "text",
                    "text": "Is the target object present? Answer Yes or No.",
                },
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "No"},
            ],
        },
    ],
}
```

代码作用：

- 训练格式应尽量与部署时模板一致，尤其是 image/text 顺序。
- assistant 部分是监督目标；通常只对回答 token 计算 loss。
- 二分类数据中必须包含困难负样本，否则模型容易学到“默认 Yes”。
- 不同训练框架的字段格式不同，最终以所用 Processor/SFTTrainer 文档为准。

### 13.4 数据质量优先级

从高到低：

1. 标签正确。
2. train/validation/test 无泄漏。
3. 覆盖实际部署分布。
4. 困难负样本和边界样本充分。
5. 模板与部署一致。
6. 类别和场景平衡。
7. 样本数量。

### 13.5 阶段验收

- 建立第一版 500～2000 张领域数据集。
- 写自动审计：重复 hash、损坏图片、缺失字段、类别分布、场景分布、分辨率分布。
- 人工抽查每个 split 至少 50 张。
- 先用零样本模型跑基线并冻结测试集，再开始微调。

---

## 14. 阶段 10：SFT、LoRA 与参数高效微调（3～5 周）

### 14.1 训练方式的选择

| 方法 | 更新内容 | 优点 | 风险/代价 |
|---|---|---|---|
| Prompt/Grammar | 不改权重 | 最便宜，应先做 | 能力上限不变 |
| Connector-only | 只训练视觉连接层 | 参数少，适合域对齐 | 可能不足以改变语言行为 |
| LLM LoRA | 给语言层加低秩适配器 | 成本低、效果常较好 | 可能弱化通用能力 |
| Vision LoRA | 给视觉层加适配器 | 适应特殊视觉域 | 数据不足时容易过拟合 |
| Joint LoRA | 视觉/连接/语言共同适配 | 能力更全面 | 更难调参与诊断 |
| Full fine-tuning | 更新全部权重 | 最大自由度 | 显存、数据和灾难性遗忘风险高 |

推荐递进顺序：

```text
零样本基线
  → prompt/template 修正
  → grammar/解析修正
  → connector-only 或 LLM LoRA
  → joint LoRA
  → 有充分证据后才考虑全量训练
```

### 14.2 LoRA 的数学直觉

原权重 `W` 冻结，只学习一个低秩增量：

```text
W' = W + ΔW
ΔW = B A

A: [r, in_features]
B: [out_features, r]
r << min(in_features, out_features)
```

因此新增参数量约为：

```text
r × (in_features + out_features)
```

而不是原矩阵的：

```text
in_features × out_features
```

### 14.3 最小 LoRA 配置

```python
from peft import LoraConfig


peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    bias="none",
    task_type="CAUSAL_LM",
)
```

代码作用：

- `r` 控制适配器容量；不是越大越好。
- `lora_alpha/r` 影响更新缩放。
- `target_modules` 必须与实际模型模块名匹配，不能从其他模型照抄。
- 是否把 vision encoder 或 connector 加入 target，需要通过 `named_modules()` 确认。

打印候选模块：

```python
for name, module in model.named_modules():
    if name.endswith(("q_proj", "k_proj", "v_proj", "o_proj")):
        print(name, module.__class__.__name__)
```

代码作用：

- 先检查真实模块名，避免“训练正常运行但实际没有适配目标层”。
- 创建 PEFT 模型后还应打印 trainable parameter 数量。

### 14.4 使用 TRL 组织 VLM SFT

下面是结构示意，具体参数随 Transformers/TRL 版本变化，运行前必须锁定版本并核对官方文档：

```python
from transformers import AutoModelForVision2Seq, AutoProcessor
from trl import SFTConfig, SFTTrainer

model_id = "HuggingFaceTB/SmolVLM-500M-Instruct"

processor = AutoProcessor.from_pretrained(model_id)
model = AutoModelForVision2Seq.from_pretrained(
    model_id,
    torch_dtype="auto",
)

training_args = SFTConfig(
    output_dir="outputs/smolvlm-domain-lora",
    learning_rate=2e-4,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=8,
    num_train_epochs=3,
    logging_steps=10,
    save_strategy="epoch",
    eval_strategy="epoch",
    max_length=None,
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=validation_dataset,
    processing_class=processor,
    peft_config=peft_config,
)

trainer.train()
trainer.save_model()
```

代码作用：

- Processor 同时负责图像处理、tokenizer 和多模态 chat template。
- `gradient_accumulation_steps` 用多次小 batch 累积出更大的有效 batch。
- VLM 训练时把 `max_length=None` 作为起点，可避免图像 token 被简单截断；之后再根据模型和显存设计长度策略。
- validation 必须按场景隔离，不能只观察 training loss。
- 保存适配器后，要在冻结的 test set 上与零样本基线做成对比较。

### 14.5 训练时必须记录

- Git commit 与依赖 lock 文件。
- 基座模型 revision/SHA。
- 数据集版本与 split hash。
- Processor/chat template 内容。
- 随机种子、dtype、设备和 GPU 数量。
- 总 batch size、learning rate、scheduler、warmup。
- 可训练模块与参数量。
- train/eval loss、领域指标、通用能力回归指标。
- 最佳 checkpoint 的选择规则。

### 14.6 不要只看 loss

训练 loss 下降可能只表示模型更会复述固定答案。应同时检查：

- 未见场景的目标识别。
- 困难负样本的假阳性率。
- 同义 prompt 鲁棒性。
- 分辨率、模糊、曝光变化。
- image/text 顺序是否仍敏感。
- 通用图像描述能力是否明显退化。
- 高精度模型和量化模型之间是否保持收益。

### 14.7 阶段验收

完成一次小规模 LoRA 微调，并提交：

- 数据卡。
- 训练配置。
- loss 曲线。
- 可训练参数列表。
- 零样本/LoRA 的冻结测试集配对结果。
- 最坏的 20 个失败样本。
- 是否值得进入板端转换的书面决策。

---

# 第六部分：量化与 RK3588 部署

## 15. 阶段 11：量化基础（2～3 周）

### 15.1 为什么量化

一个有 `P` 个参数的模型，仅权重存储可粗略估算为：

```text
FP32: 4P bytes
FP16/BF16: 2P bytes
INT8: 约 1P bytes + scale/metadata
INT4: 约 0.5P bytes + scale/metadata
```

实际运行内存还包括：

- KV cache。
- 中间激活。
- 视觉编码器与 mmproj。
- 运行时 workspace。
- 图像和 HTTP buffer。

### 15.2 需要理解的量化概念

- PTQ 与 QAT。
- weight-only 与 weight-activation quantization。
- 对称/非对称量化。
- per-tensor、per-channel、group-wise。
- scale、zero point、clipping 和 outlier。
- calibration set 与 importance matrix。
- 重新量化为什么通常比从高精度源量化更差。

最简单的对称量化示意：

```python
import torch


def symmetric_int8_quantize(x: torch.Tensor):
    max_abs = x.abs().max().clamp_min(1e-12)
    scale = max_abs / 127
    q = torch.round(x / scale).clamp(-127, 127).to(torch.int8)
    return q, scale


def dequantize(q: torch.Tensor, scale: torch.Tensor):
    return q.float() * scale
```

代码作用：

- 用一个 scale 把浮点范围映射到 int8 的 `[-127, 127]`。
- `round` 和 `clamp` 引入不可逆误差。
- 真实 GGUF/RKNN 量化常使用分组、不同 bit 数和更复杂布局，以平衡速度与精度。

### 15.3 llama.cpp / GGUF 路径

典型流程：

```bash
# 1. 从 Hugging Face 权重转换高精度 GGUF
python convert_hf_to_gguf.py \
  /path/to/hf-model \
  --outfile model-f16.gguf \
  --outtype f16

# 2. 量化语言模型
./build/bin/llama-quantize \
  model-f16.gguf \
  model-Q4_K_M.gguf \
  Q4_K_M

# 3. 多模态模型还要转换 mmproj/视觉组件
python convert_hf_to_gguf.py \
  /path/to/hf-model \
  --mmproj \
  --outfile mmproj-Q8_0.gguf \
  --outtype q8_0
```

命令作用：

- 先从 FP16/BF16 等高精度源量化，避免二次量化累积误差。
- LLM 权重可尝试 Q4/Q5/Q8；视觉 encoder/mmproj 通常更小且直接影响视觉语义，可优先保留较高精度。
- 转换脚本与 llama.cpp commit 必须记录，因为格式和模型支持会变化。

量化对比不能只测文本 perplexity。对 VLM 至少测：

- 领域语义正确率。
- 公共 VLM benchmark 子集。
- 图像描述质量。
- 视觉细节/小目标能力。
- 文件大小、峰值内存、TTFT、tok/s、端到端延迟。

### 15.4 量化实验矩阵

```text
语言模型: F16 / Q8_0 / Q6_K / Q5_K_M / Q4_K_M
mmproj:    F16 / Q8_0 / Q5
场景:      正样本 / 负样本 / 小目标 / 模糊 / 低照度
```

不要一次跑完整笛卡尔积。先固定 mmproj=高精度，筛选 LLM 量化；再固定最佳 LLM，比较 mmproj 精度。

### 15.5 阶段验收

- 从同一高精度源生成至少 3 种量化。
- 在同一冻结数据集、同一模板和确定性解码下比较。
- 输出 Pareto 图：横轴延迟或内存，纵轴语义正确率。
- 选出的模型必须说明为什么适合 RK3588，而不是只说“Q4 更小”。

---

## 16. 阶段 12：RK3588 的两条部署路线（3～5 周）

### 16.1 路线 A：llama.cpp + GGUF

特点：

- 当前仓库已经使用，工程起点最低。
- 主要依赖 CPU，也可研究可用的 GPU/Vulkan 后端。
- 模型支持和 OpenAI-compatible server 生态较成熟。
- 对不受 RKNN 支持的新模型更灵活。

需要学习：

- ARM64 编译、NEON、BLAS 和线程亲和性。
- GGUF 元数据与量化类型。
- prefill/decode profiling。
- KV cache、context size 和 batch 参数。
- server 并发、slot、超时和缓存。

### 16.2 路线 B：RKNN-Toolkit2 + RKLLM

Rockchip 官方工具链提供 RKNN Runtime 的 C/C++ 接口，并支持 RK3588。多模态部署通常要把系统拆开理解：

```text
图像
  → Vision Encoder（RKNN/NPU）
  → image embeddings
  → multimodal special tokens / embedding insertion
  → LLM（RKLLM/NPU）
  → generated tokens
```

这条路线不是把 GGUF 文件直接交给 NPU。你需要处理：

- 原模型导出与支持矩阵。
- vision encoder 的 ONNX/RKNN 转换。
- 量化校准数据。
- 动态 shape、算子支持和图切分。
- LLM 导出为 RKLLM。
- 图像 embedding 与文本 token 的正确拼接。
- PC 参考输出、转换后模拟器输出和板端输出的逐级对齐。

### 16.3 为什么先做视觉 encoder NPU 化

对新手而言，先把单独的视觉模型部署到 RKNN 更容易：

1. 输入输出 shape 固定、容易比较。
2. 可以用余弦相似度/最大误差对齐 PyTorch、ONNX、RKNN 输出。
3. 可以学习校准、算子兼容和板端 C API。
4. 成功后再处理 LLM 和多模态 embedding 拼接。

### 16.4 三端对齐程序

转换任何视觉模型时都保存同一输入的中间输出：

```text
PyTorch FP32 reference
  ↓ compare cosine / MAE / max error
ONNX Runtime reference
  ↓ compare cosine / MAE / max error
RKNN simulator
  ↓ compare cosine / MAE / max error
RK3588 board runtime
```

简单特征对齐：

```python
import numpy as np


def compare_features(reference, candidate):
    a = reference.astype(np.float64).reshape(-1)
    b = candidate.astype(np.float64).reshape(-1)

    cosine = np.dot(a, b) / (
        np.linalg.norm(a) * np.linalg.norm(b) + 1e-12
    )
    diff = np.abs(a - b)

    return {
        "cosine": float(cosine),
        "mae": float(diff.mean()),
        "max_abs_error": float(diff.max()),
    }
```

代码作用：

- cosine 衡量特征方向是否一致。
- MAE 表达平均数值偏差。
- max error 可发现少量严重异常。
- 中间特征接近不保证最终语义完全一致，但能定位偏差从哪一级引入。

### 16.5 性能测量

至少拆分以下时间：

```text
T_total = T_capture
        + T_jpeg
        + T_base64
        + T_http
        + T_vision
        + T_prefill
        + T_decode
        + T_parse
```

Linux 中使用单调时钟：

```c
#include <time.h>

static double monotonic_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}
```

代码作用：

- `CLOCK_MONOTONIC` 不受系统时间校准影响，适合计算时间差。
- 在每个阶段前后采样，才能知道优化该落在哪个模块。
- 只测 tokens/s 会忽略摄像头、视觉 prefill 和 HTTP 对短回答任务的主要开销。

还应记录：

- 冷启动与热启动。
- 首 token 延迟（TTFT）。
- decode tokens/s。
- 进程峰值 RSS。
- CPU/NPU/GPU 利用率。
- 温度、频率降档和平均功耗。
- 连续运行 30～60 分钟后的稳定性能。

### 16.6 板端生产化

需要补齐的工程能力：

- systemd 服务与自动重启。
- 健康检查和 readiness。
- 有界队列与背压。
- 请求超时、取消和重试策略。
- 模型/配置版本输出。
- 日志轮转和磁盘空间保护。
- 原图与隐私数据的保留策略。
- watchdog 和异常恢复。
- 进程权限最小化。

### 16.7 阶段验收

- llama.cpp 路径完成 1 小时持续运行报告。
- RKNN 路径先完成一个视觉 encoder 的 PyTorch→ONNX→RKNN→板端对齐。
- 若官方支持目标 VLM，再完成视觉 encoder + RKLLM 的多模态 demo。
- 两条路径比较开发成本、兼容性、语义精度、延迟、内存和功耗。

---

# 第七部分：成为 VLM 研发者

## 17. 阶段 13：评测体系（持续进行）

### 17.1 三层评测

#### 第一层：组件测试

- 图像预处理是否一致。
- 模板 token 是否一致。
- parser 是否处理所有协议分支。
- 高精度/量化中间特征是否对齐。

#### 第二层：领域评测

- 目标存在性。
- 小目标、遮挡、低照度、相似负样本。
- 不同摄像头、场景和 prompt。
- 板端端到端性能。

#### 第三层：通用 VLM 评测

- VQA、OCR、图表、文档、空间关系、幻觉。
- 使用 lmms-eval 或 VLMEvalKit 的适当任务子集。
- 保留通用能力回归集，防止领域微调只提升单一任务。

### 17.2 错误分类法

每次失败至少归入一类：

```text
PERCEPTION      看不清或没有提取目标特征
GROUNDING       看到了，但对象/区域关联错误
REASONING       视觉事实正确，推理结论错误
INSTRUCTION     没按问题或格式要求回答
HALLUCINATION   生成图中不存在的内容
CALIBRATION     极度自信但错误
SYSTEM          采集、请求、超时、解析或资源故障
ANNOTATION      ground truth 本身错误或有歧义
```

失败分类比单一准确率更能指导下一步：

- PERCEPTION 多：改善图像、视觉 encoder、分辨率或视觉微调。
- INSTRUCTION 多：检查模板、SFT 指令数据、grammar。
- SYSTEM 多：优先修工程链路，暂时不要训练模型。
- ANNOTATION 多：清洗数据，任何训练都应暂停。

### 17.3 概率与校准

若 server 能提供候选 token 的 log probability，可以比较 Yes/No：

```python
import math


def binary_probability(logp_yes: float, logp_no: float) -> float:
    m = max(logp_yes, logp_no)
    yes = math.exp(logp_yes - m)
    no = math.exp(logp_no - m)
    return yes / (yes + no)
```

代码作用：

- 在 Yes/No 两个候选中重新归一化，得到相对分数。
- 它不是天然校准后的真实概率。
- 应在独立 validation set 上做温度缩放或阈值选择，再在 test set 上一次评估。
- tokenization 可能把 `Yes`/`No` 编成不同 token 序列，必须先检查 tokenizer。

---

## 18. 阶段 14：论文阅读与研究能力（持续进行）

### 18.1 一篇 VLM 论文的阅读顺序

不要从公式第一页硬啃到最后。使用下面顺序：

1. 摘要：问题、方法、结论。
2. 图 1/架构图：输入怎样流动。
3. 主要结果表：与谁比较，提升多少。
4. 消融实验：哪个组件真正贡献提升。
5. 数据与训练细节：是否能复现。
6. 评测协议：prompt、解码和后处理是否公平。
7. 限制与失败案例。
8. 最后再读公式和相关工作。

### 18.2 论文卡片模板

```markdown
# Paper Card

- 论文：
- 一句话问题：
- 一句话方法：
- 基座 LLM：
- Vision Encoder：
- Connector：
- 视觉 token 数：
- 训练阶段：
- 训练数据：
- 主要指标：
- 最重要消融：
- 我不相信/不确定的地方：
- 与 RK3588 项目的关系：
- 我能复现的最小实验：
```

### 18.3 必读主题顺序

1. Transformer 与 causal language modeling。
2. ViT。
3. CLIP/SigLIP 式视觉语言预训练。
4. BLIP-2/Q-Former。
5. LLaVA 式投影器与视觉指令微调。
6. Flamingo/Idefics 的多图与 resampler。
7. SmolVLM/Idefics3 的轻量化设计。
8. LoRA/QLoRA。
9. PTQ、低比特量化与重要性矩阵。
10. VLM 幻觉、评测可靠性与数据污染。

---

## 19. 从“复现者”走向“独立研发者”的项目阶梯

### P0：完全解释当前系统

产出：调用图、数据流图、错误码表、资源所有权表。

验收：随机指出一个响应，你能追溯到图片、请求、模型版本和 parser 决策。

### P1：重构可靠推理协议

产出：image-first、结构化约束、完整原始响应、明确 server ownership。

验收：HTTP、协议、格式和语义四类失败不会混淆。

### P2：多场景复现内容顺序效应

产出：预注册实验卡、配对数据、统计报告、失败图库。

验收：结论不依赖同一张图重复运行。

### P3：建立领域评测集

产出：数据卡、固定 split、审计脚本、基线报告。

验收：相邻帧、重复图片和同场景泄漏均被检测。

### P4：完成 LoRA 微调

产出：适配器、训练配置、曲线、零样本/微调对比。

验收：独立 test set 有收益，通用回归集没有不可接受退化。

### P5：完成量化 Pareto 研究

产出：FP16/Q8/Q6/Q5/Q4 精度—速度—内存—功耗图。

验收：最终量化选择有领域数据支持。

### P6：完成 NPU 可行性验证

产出：vision encoder 的 PyTorch/ONNX/RKNN 对齐与板端性能。

验收：误差来源可定位，支持矩阵和版本明确。

### P7：完整 VLM 板端原型

产出：摄像头实时输入、稳定服务、结构化输出、监控和恢复。

验收：连续运行、故障注入、温度/功耗测试通过。

### P8：形成自己的研究课题

可以从以下方向选择一个：

- 多模态内容顺序对小模型和量化模型的影响。
- 视觉 token 压缩与板端延迟/精度权衡。
- 针对小目标的自适应裁剪和多尺度视觉 token。
- 视觉 encoder 与 projector 的混合精度量化。
- 领域 LoRA 对通用视觉能力的遗忘。
- 基于 log probability 的板端拒答和不确定性估计。
- 摄像头质量变化下的 VLM 鲁棒性与自动质量门控。

---

## 20. 28 周建议日程

| 周 | 学习主题 | 主要产出 | 通过标准 |
|---|---|---|---|
| 1 | Linux、SSH、Git | 命令笔记、版本清单 | 能独立拉取、构建、部署 |
| 2 | C、CMake、资源管理 | 当前 C 调用图 | 能解释失败清理路径 |
| 3 | Python、JSONL | 数据扫描器 | 损坏数据可检测 |
| 4 | 线性代数与 shape | tensor 形状练习 | 注意力形状全对 |
| 5 | 概率、softmax、CE | 手写数值实验 | 能解释 logits/概率/loss |
| 6 | PyTorch/autograd | 小分类器 | train/eval 流程正确 |
| 7 | 数据集与验证 | 图像二分类基线 | 有固定 split 与混淆矩阵 |
| 8 | Tokenizer 与 LM | token 探索脚本 | 能定位特殊 token |
| 9 | Self-attention | 最小 attention | 能展示 causal mask |
| 10 | KV cache 与解码 | 参数消融 | 能解释 TTFT/tok/s |
| 11 | 图像预处理 | 图像审计器 | 能定位分辨率链路 |
| 12 | ViT/SigLIP | patch/feature 脚本 | 能打印中间 shape |
| 13 | VLM 三模块 | 架构对比表 | 能解释 connector |
| 14 | SmolVLM 模板 | 模板/token 对比 | 能复现顺序差异 |
| 15 | llama.cpp/GGUF | 元数据与请求报告 | 版本与模型 hash 完整 |
| 16 | Grammar/协议 | 结构化推理客户端 | 四层失败可区分 |
| 17 | 实验设计 | 预注册实验卡 | 唯一变量明确 |
| 18 | 统计 | CI/McNemar 报告 | 原始计数可复算 |
| 19 | 领域数据采集 | 数据卡 v1 | 无明显泄漏 |
| 20 | 数据审计 | 审计脚本 | hash/分布/损坏全覆盖 |
| 21 | LoRA 理论与模块 | 参数清单 | 可训练层符合预期 |
| 22 | VLM SFT | 首次训练 | 配置与曲线完整 |
| 23 | 微调评测 | 基线对照 | 冻结测试集有证据 |
| 24 | GGUF 量化 | 3 种量化 | 从同一高精度源生成 |
| 25 | 板端 profiling | 延迟分解 | 冷/热、TTFT、功耗齐全 |
| 26 | RKNN 入门 | 视觉模型转换 | 四端特征对齐 |
| 27 | 系统稳定性 | 长时与故障注入 | 自动恢复、无无限增长 |
| 28 | 研究总结 | 技术报告/论文草稿 | 数据、代码、结论可复现 |

每天建议 2～3 小时：

```text
30 分钟：读官方文档或论文
60 分钟：写最小代码
30 分钟：映射到本仓库
30 分钟：故意改变一个变量
30 分钟：记录结果和问题
```

如果时间更少，降低每周范围，不要省略实验记录和验收。

---

## 21. 一个对话窗口只完成一个学习/实验单元

考虑到后续使用长上下文模型协作，每个对话窗口只处理一个明确单元。推荐提示模板：

```markdown
本窗口只完成：KXX-主题名称。

请先阅读：
- knowledge.md 对应章节
- 相关源文件
- 上一实验的 summary.md

本窗口允许修改：
- 明确列出文件

本窗口必须产出：
1. 最小代码
2. 运行命令
3. 原始结果路径
4. 结果解释
5. 失败和未完成项
6. 下一窗口所需的 summary.md

验收标准：
- 一次只改变一个核心变量
- 不覆盖原始数据
- 记录 Git commit、模型和环境版本
```

窗口结束时归档：

```text
experiment/KXX_name/
├── README.md          # 问题、假设、命令和结论
├── config.json        # 冻结配置
├── raw.jsonl          # 不可覆盖的原始结果
├── analysis.json      # 派生指标
├── figures/           # 图表
├── failures/          # 代表性失败样本
└── summary.md         # 下一窗口只需读取的交接摘要
```

---

## 22. 最先执行的 12 个学习单元

不要直接跳到训练。按以下顺序开始：

### K01：画出仓库调用链

- 阅读 `main.c`、`camera.c`、`llama_server.c`、`result_parser.c`。
- 画资源所有权与数据流。
- 不修改代码。

### K02：离线重放解析器

- 收集历史原始响应。
- 区分 transport/protocol/format/semantic。
- 验证 `No` 不再等于失败。

### K03：理解最终 chat template

- 用 Hugging Face Processor 输出模板。
- 比较 image-first/text-first token 序列。
- 标注特殊 token 和相对位置。

### K04：复现注意力

- 手写单头 causal attention。
- 用 4 个 token 打印权重矩阵。
- 解释内容顺序改变了什么。

### K05：审计图像预处理

- 记录原图、保存图、encoder 输入尺寸。
- 输出亮度、对比度、边缘强度。
- 人工查看全部测试图。

### K06：重跑内容顺序配对实验

- 使用多个独立正/负场景。
- 固定其他变量。
- 预先写停止规则。

### K07：加入 grammar

- 只允许 Yes/No。
- 证明格式成功率提高不代表语义必然提高。

### K08：拆分性能时间

- 测 capture、encode、HTTP、vision/prefill/decode、parse。
- 比较冷启动和热启动。

### K09：建立领域数据卡

- 定义部署分布和困难负样本。
- 设计 session/scene 级 split。

### K10：训练一个非 VLM 基线

- 用小视觉分类器完成相同二分类。
- 比较准确率、延迟、内存。
- 判断业务是否真的需要生成式 VLM。

### K11：第一次 LoRA

- 只使用冻结训练/验证集。
- 打印可训练层和参数量。
- 保存完整配置与曲线。

### K12：量化与板端回归

- 从同一高精度 checkpoint 生成 Q8/Q5/Q4。
- 同时比较语义精度和系统指标。
- 选出 Pareto 最优点。

---

## 23. 常见误区

1. **会调用 Transformers 就等于懂 VLM。**
   真正的理解来自 shape、模板、中间特征、训练目标和故障定位。

2. **输出格式正确就等于答案正确。**
   Grammar 解决语法空间，不解决视觉语义。

3. **20 次重复就是 20 个独立样本。**
   同一图片的重复主要测随机性，不足以证明跨场景泛化。

4. **分辨率越高一定越准。**
   Processor 可能统一 resize；高分辨率还会增加 token、噪声和延迟。

5. **模型更大一定更适合板端。**
   业务需要的是精度、延迟、内存、功耗和稳定性的 Pareto 平衡。

6. **训练 loss 下降就表示研发成功。**
   可能是模板记忆、数据泄漏或类别先验。

7. **量化后能运行就算转换成功。**
   必须与高精度基线做中间特征和任务精度对齐。

8. **只保存最终 CSV。**
   没有原始请求、响应和图片 hash，未来很难修复分析错误。

9. **把 server、客户端、模型一起改。**
   多变量同时变化会让任何改进都无法归因。

10. **一上来就全量微调。**
    很多问题先修模板、预处理、grammar 或 parser 就能解决。

---

## 24. 术语速查

| 术语 | 简明解释 |
|---|---|
| VLM/LMM | 同时处理视觉与语言等模态的模型 |
| Vision Encoder | 把像素编码为视觉特征的网络 |
| Patch | ViT 中切分图像得到的局部块 |
| Visual Token | 送入语言模型的视觉表示单元 |
| Connector/Projector | 把视觉特征映射到 LLM hidden space |
| Resampler | 压缩或重组视觉 token 的模块 |
| Chat Template | 把角色、文本、图片组织成模型训练时格式 |
| Causal LM | 只根据已有 token 预测下一个 token 的语言模型 |
| Prefill | 一次处理整个输入上下文的阶段 |
| Decode | 使用 KV cache 逐 token 生成的阶段 |
| KV Cache | 保存历史 attention K/V，避免重复计算 |
| Logits | softmax 之前的未归一化分数 |
| Grammar | 在解码阶段限制合法输出序列的规则 |
| SFT | 使用示范输入/答案做监督微调 |
| LoRA | 用低秩矩阵学习少量权重增量 |
| PTQ | 训练完成后进行量化 |
| QAT | 在训练中模拟量化误差 |
| GGUF | llama.cpp/ggml 生态使用的模型与元数据格式 |
| mmproj | llama.cpp 多模态模型中的视觉/投影组件文件 |
| RKNN | Rockchip NPU 模型格式与运行时生态 |
| RKLLM | Rockchip 面向 LLM 的转换/运行路径 |
| Calibration | 用代表数据估计量化范围或校准概率 |
| Data Leakage | 测试信息进入训练，造成虚假高分 |
| Ablation | 移除或改变一个组件以判断其贡献 |
| Confounder | 与目标变量共同变化、导致错误归因的因素 |
| McNemar test | 比较同一批样本上两个分类方法的配对检验 |
| Pareto frontier | 无法在不牺牲另一指标时继续改进的候选集合 |

---

## 25. 权威资料与阅读顺序

以下链接优先选择论文原文、官方模型卡和官方工具文档。库接口会变化，真正运行代码时应锁定版本并重新核对。

### 基础论文

1. [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
2. [An Image is Worth 16x16 Words（ViT）](https://arxiv.org/abs/2010.11929)
3. [Sigmoid Loss for Language-Image Pre-Training（SigLIP）](https://arxiv.org/abs/2303.15343)

阅读目标：不是背公式，而是能画出 Q/K/V、patch token 和图文表征的 shape 流程。

### PyTorch 与训练

1. [PyTorch Learn the Basics](https://docs.pytorch.org/tutorials/beginner/basics/intro.html)
2. [PyTorch Autograd](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html)
3. [PyTorch Optimization](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html)
4. [PEFT LoRA 指南](https://huggingface.co/docs/peft/main/conceptual_guides/lora)
5. [TRL SFTTrainer](https://huggingface.co/docs/trl/sft_trainer)

阅读目标：能解释一次训练 step，打印可训练参数，并建立无泄漏验证集。

### VLM 与 SmolVLM

1. [Transformers Image-text-to-text 指南](https://huggingface.co/docs/transformers/main/tasks/image_text_to_text)
2. [Transformers Multimodal Chat Templates](https://huggingface.co/docs/transformers/main/en/chat_templating_multimodal)
3. [SmolVLM-500M-Instruct 模型卡](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct)
4. [SmolVLM 官方介绍](https://huggingface.co/blog/smolvlm)

阅读目标：能解释 Processor、模板、视觉 token 和 Idefics3/SmolVLM 的视觉—语言连接方式。

### llama.cpp 与量化

1. [llama.cpp README](https://github.com/ggml-org/llama.cpp/blob/master/README.md)
2. [llama-server 文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
3. [GBNF Grammar 指南](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)
4. [llama.cpp quantize 文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md)
5. [importance matrix 文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/imatrix/README.md)

阅读目标：能说明 GGUF、mmproj、server 请求、grammar 和每种量化实验的边界。

### RK3588/NPU

1. [RKNN-Toolkit2 官方仓库](https://github.com/airockchip/rknn-toolkit2)
2. [RKNN Model Zoo](https://github.com/airockchip/rknn_model_zoo)
3. [RKLLM 多模态示例](https://github.com/airockchip/rknn-llm/tree/main/examples/multimodal_model_demo)

阅读目标：先完成一个视觉模型的转换和四端对齐，再研究完整 VLM 的视觉 embedding 与 LLM 拼接。

### VLM 评测

1. [lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval)
2. [VLMEvalKit](https://github.com/open-compass/VLMEvalKit)

阅读目标：学习统一任务接口、可复现生成配置、样本级结果保存和公共 benchmark 回归；领域任务仍要建立自己的冻结测试集。

---

## 26. 你的第一周行动清单

### 第 1 天

- 阅读本文件第 2、4 节。
- 画出当前仓库端到端数据流。
- 写出 10 个不理解的函数或字段。

### 第 2 天

- 逐行阅读 `llama_server.c`。
- 找到请求 JSON 中 image/text 的真实顺序。
- 找到 server 启动、健康检查和停止逻辑。

### 第 3 天

- 逐行阅读 `result_parser.c` 与 `experiment/metrics.py`。
- 用历史响应构造 Yes、No、描述、空响应、坏 JSON 五类输入。
- 写出每一类正确的分层结果。

### 第 4 天

- 学习 tensor shape、矩阵乘法和 softmax。
- 运行本文 softmax 与 cross-entropy 示例。
- 手算一个三分类 softmax 并与代码比较。

### 第 5 天

- 使用 SmolVLM Processor 打印 image-first/text-first 模板。
- 保存最终字符串和 token ids。
- 解释为什么两个请求不是等价条件。

### 第 6 天

- 阅读 `experiment/run_s2e1.py` 与分析脚本。
- 从原始数据手工复算一个场景的计数。
- 写出实验中能说明和不能说明的结论。

### 第 7 天

- 完成 K01 总结。
- 把代码、图、问题和结论归档。
- 为 K02 写一张不超过一页的实验卡。

---

## 27. 最后提醒

真正的 VLM 研发能力不是“记住模型排行榜”，而是同时具备四种思维：

1. **模型思维**：理解 token、特征、训练目标和泛化。
2. **系统思维**：理解摄像头、进程、协议、内存、延迟和故障恢复。
3. **实验思维**：理解控制变量、样本独立性、统计不确定性和结论边界。
4. **产品思维**：知道业务需要的是稳定、可解释、可维护的整体系统，而不是单次漂亮回答。

你当前仓库已经有一个很好的研究起点：它不仅部署了轻量 VLM，还暴露了内容顺序、分辨率、缓存、结构化解码和指标语义之间的真实交互。沿着这份路线推进时，建议始终保持一个原则：**先保存证据，再解释现象；先建立可靠基线，再训练新模型。**
