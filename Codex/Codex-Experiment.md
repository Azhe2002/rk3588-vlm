# 下一阶段板端实验与代码实施规格

> 日期：2026-08-12  
> 适用仓库：`rk3588-vlm`，基线提交 `1b42a9a`  
> 关联审阅：`Codex-preview.md`  
> 目标读者：下一阶段代码实现者与 RK3588 板端实验执行者  
> 状态：实施建议稿；在收到后续命令前不修改现有程序、不运行板端实验、不推送 GitHub。

## 1. 下一阶段的核心目标

下一阶段不应继续简单增加分辨率、温度或模糊档位。当前更重要的目标是建立一条**可配对、可追踪、不可覆盖、可自动复算**的实验链路，然后用它回答三个问题：

1. 先前观察到的静态图/在线相机差异，是否来自请求 payload、图文顺序、缓存或 server 生命周期差异？
2. 轻微模糊导致输出变成 yes/no 单词，究竟来自模糊本身，还是 `videoconvert`、JPEG 重编码等管线变化？
3. 当模型输出必须供程序消费时，受限解码能否在不损害正负样本语义准确率的前提下保证格式合规？

推荐把下一阶段的论文主线收敛为：

> 在统一请求路径和配对图像条件下，测量 SmolVLM 的 yes/no 单词格式率对输入扰动、问题模板和解码约束的敏感性，并量化跨 session 变异。

## 2. 代码审阅后的关键判断

### 2.1 必须先修复：同一实验存在两个 `llama-server` 所有者

当前 `experiment/board_exp_run.sh` 会先启动一个 `llama-server`，随后执行的 `rk3588-vlm` 又在 `llama_init()` 中启动同端口 8088 的另一个 server。

潜在过程如下：

```text
board_exp_run.sh 启动 server A，占用 8088
  -> rk3588-vlm fork server B，B 因端口占用退出
  -> llama_init() 访问 /health，实际命中 server A
  -> 程序误认为 server B 启动成功
  -> 退出时尝试管理已经退出的 B，server A 由 shell 再清理
```

这会让模型、参数、缓存状态、PID 所有权和 server 日志来源变得不清楚。下一版必须只保留一种模式：

- `managed`：`rk3588-vlm` 自己启动和停止 server；shell 不再启动 server；
- `external`：实验 runner 启动 server，`rk3588-vlm` 只连接 `--server-url`，绝不 fork/kill server。

建议默认使用 `managed` 供部署程序使用，下一阶段实验使用 `external`，方便一台 server 对同一批冻结帧运行多个随机化条件。

验收条件：

- 端口 8088 只有一个监听 PID；
- managed 模式中，子进程若在 health check 前退出，初始化必须失败，不能只凭 `/health` 成功；
- external 模式不得向 server PID 发送信号；
- manifest 记录 server PID、完整版本串与启动命令。

### 2.2 必须先复测：静态与在线路径的图文顺序不同

当前 C 客户端 `llama_server.c` 构造的 user content 顺序是：

```text
text -> image_url
```

而 `run_static_nocache.py`、`http_test.py` 和 `board_server_test.py` 使用：

```text
image_url -> text
```

多模态 chat template 可能对内容顺序敏感。因此现有“静态图不复现、在线帧才复现”的差异，至少混入了图文顺序差异。下一阶段必须先做同帧、同 payload、同参数的配对复测。

建议定义唯一枚举：

```text
--content-order text-image
--content-order image-text
```

正式主实验固定一种顺序；另一种只作为专门的顺序消融实验。每条记录保存 `request_payload_sha256`，必要时保存去除 base64 后的 canonical request JSON。

### 2.3 当前“严格解析”不是严格格式判定

`parse_yes_no()` 会在完整行中搜索 yes/no 单词，不要求整条输出只含一个词；`analyze.py` 又把程序返回 YES 的比例命名为 `strict_yes_rate`。下一阶段代码必须拆开：

```c
typedef enum {
    FORMAT_EXACT,       // 严格 "yes" 或 "no"
    FORMAT_WORD,        // 允许预注册的大小写/末尾标点
    FORMAT_NONCOMPLIANT
} format_class_t;

typedef enum {
    SEMANTIC_YES,
    SEMANTIC_NO,
    SEMANTIC_UNKNOWN
} semantic_class_t;
```

建议函数职责：

- `classify_format(raw)`：只判断输出形态；
- `classify_semantic(raw)`：只判断语义标签；
- `semantic_correct(label, ground_truth)`：结合外部真值计算正确性；
- 原 `parse_yes_no()` 若保留，应改名为 `extract_yes_no_token()`，避免继续被当作格式指标。

### 2.4 当前帧采样不能证明“这一轮推理用了哪一帧”

当前后台采样器每 2 秒复制一次 `/dev/shm/frame.jpg`，推理约每 5–7 秒一轮。采样帧与推理帧没有 round ID、时间戳或哈希关联，`frame_analysis.py` 只能按数量粗略分桶。

下一版每次推理必须：

1. 从内存取出确切 JPEG 字节；
2. 在发送请求前计算 SHA-256；
3. 可选保存为 `frames/<round_id>_<sha12>.jpg`；
4. 将文件名、SHA-256、字节数、采集序号和时间戳写入同一条 JSONL；
5. 不再用异步 2 秒采样推断对应关系。

推荐让 `camera_get_frame()` 返回数据与元信息，而不是先写固定 `/dev/shm/frame.jpg` 再由多个进程复制：

```c
typedef struct {
    unsigned char *data;
    size_t length;
    uint64_t sequence;
    int64_t captured_monotonic_ms;
} camera_frame_t;
```

如果短期不想改接口，至少在每轮把 `/dev/shm/frame.jpg` 原子复制到唯一文件后再推理，并对唯一文件计算哈希。

### 2.5 当前日志与运行器容易产生不可恢复的数据覆盖

现有脚本使用固定文件名，例如 `exp5_A_256_640_ctrl.log` 和 `exp_static_nocache.log`，重跑会覆盖旧数据。下一版必须采用不可变 run 目录：

```text
experiment/data/stage2/
  <session_id>/
    session_manifest.json
    <run_id>/
      manifest.json
      rounds.jsonl
      stdout.log
      server.log
      frames/
```

命名建议：

```text
session_id = 20260813T093000+0800_board01
run_id     = S2E2_256m_pos_blur1_b03_r02
```

规则：

- 目标目录存在时默认报错；只有显式 `--resume` 才能继续；
- 不提供 `--overwrite`；
- 每次执行结束生成 `checksums.sha256`；
- 本地拉取成功并校验哈希后，才允许清理板端临时目录；
- 旧的同名实验日志先保留，不做自动迁移或覆盖。

### 2.6 当前实验条件按固定顺序执行

温度按 0.0→0.1→0.5→1.0，措辞按 A→F，分辨率按升序运行。已观察到显著跨 session 和时间漂移后，固定顺序会把处理效应与时间效应混在一起。

下一版 runner 必须：

- 接收 `--randomization-seed`；
- 在 session 开始前生成完整运行顺序并写入 manifest；
- 支持随机区组；
- 每个关键处理使用 `A -> treatment -> A` 或平衡的 AB/BA 顺序；
- 失败重跑保留原 run ID 状态，补跑用新的 attempt ID，不改变既定条件顺序。

### 2.7 当前请求参数分散且不一致

已发现：

- C 路径 `max_tokens=16`；早期 HTTP 脚本使用 32；论文写 32；
- C 路径没有 `seed` 和 `cache_prompt` CLI；
- C 超时为 30 秒，论文写 300 秒；
- server stdout/stderr 被重定向到 `/dev/null`，无法审计预处理、token 和错误；
- `llama_version()` 已实现但没有写入实验日志；
- C 的简易 JSON 提取只返回 content，丢弃了完整响应、usage/timings 和可能的概率信息。

建议将生成参数集中为一个结构体：

```c
typedef struct {
    float temperature;
    int max_tokens;
    int64_t seed;
    bool cache_prompt;
    int n_probs;
    constraint_mode_t constraint;
    content_order_t content_order;
} generation_options_t;
```

正式实验禁止依赖隐藏默认值，manifest 必须完整记录所有字段。

### 2.8 板端连接信息不应硬编码在公开仓库

`experiment/board.py` 当前写有固定主机、用户名和密码，并自动信任未知 host key。下一版建议：

- 优先 SSH key；
- 从环境变量或未跟踪的本地配置读取 host/user/key；
- 使用已知 host key，避免 `AutoAddPolicy()`；
- 公开仓库不保存密码；
- 如果该密码仍在其他网络入口有效，应更换。

建议环境变量名：

```text
RK3588_HOST
RK3588_USER
RK3588_SSH_KEY
RK3588_PORT
```

## 3. 推荐的下一版实验架构

不要把所有实验功能继续塞进部署用 C 主程序。建议拆成三层：

```text
层 1：采集/部署程序（C）
  - 在线相机采集
  - 可选保存精确推理帧
  - managed/external server 模式

层 2：统一实验 runner（Python）
  - server 生命周期
  - 冻结帧回放
  - 请求 payload 构造
  - 条件随机化
  - manifest / JSONL / 校验和

层 3：分析器（Python）
  - 格式、语义、真值三个维度
  - 汇总 CSV
  - 置信区间、配对检验、session 汇总
  - 论文表格和图一次性生成
```

### 3.1 建议新增文件

| 文件 | 责任 |
|---|---|
| `experiment/request_client.py` | 唯一 HTTP payload 构造器；图文顺序、seed、cache、约束、完整响应 |
| `experiment/run_stage2.py` | 读取实验矩阵、随机化、运行/恢复、SFTP 与校验 |
| `experiment/capture_stage2.py` | 从板端捕获并冻结带元数据的帧集 |
| `experiment/transform_stage2.py` | 对冻结帧生成 sham/blur/JPEG/缩放变体及特征清单 |
| `experiment/analyze_stage2.py` | JSONL→CSV→统计汇总；不再从 emoji 人类日志取主数据 |
| `experiment/schema.py` | 共享字段、格式分类、语义分类、manifest 校验 |
| `experiment/configs/stage2.json` | 预注册的实验矩阵和随机化 seed |
| `experiment/tests/test_metrics.py` | 格式与语义指标测试 |
| `experiment/tests/test_payload.py` | C/Python 等价 payload 与图文顺序测试 |
| `experiment/tests/test_no_overwrite.py` | 防覆盖和 resume 行为测试 |

继续保留现有 `run_exp*.py` 作为历史复现脚本，不要直接在上面叠加所有新逻辑。

### 3.2 建议修改文件

| 文件 | 推荐改造 |
|---|---|
| `main.c` | `--rounds`、`--save-frames`、`--jsonl`、`--run-id`、`--session-id`、`--server-mode`、`--server-url` |
| `llama_server.c/h` | 单一 server 所有权、request options、完整响应、timings/usage、请求哈希、显式 cache/seed/max_tokens |
| `camera.c/h` | 精确帧 sequence/time/hash 关联；最好返回内存帧结构 |
| `result_parser.c/h` | 独立 `format_class` 与 `semantic_class`；增加单元测试 |
| `board_exp_run.sh` | `set -euo pipefail`、唯一目录、拒绝覆盖、只选择一种 server 模式、可靠 trap 清理 |
| `CMakeLists.txt` | 构建 `test_parser`，启用 CTest；可增加 request builder 单元测试 |
| `README.md` | 修正 strict 定义、参数和实验模式，不再把 token 搜索称为严格格式 |

### 3.3 每轮 JSONL 最小字段

```json
{
  "schema_version": 1,
  "session_id": "20260813T093000+0800_board01",
  "run_id": "S2E1_256m_order_text_image_r01",
  "round_id": 1,
  "condition_id": "text_image_cache_off",
  "timestamp_utc": "2026-08-13T01:31:02.123Z",
  "frame_id": "pos_s01_f0007",
  "frame_sha256": "...",
  "frame_bytes": 42381,
  "source_width": 640,
  "source_height": 480,
  "ground_truth": "yes",
  "question_id": "A",
  "question": "...",
  "content_order": "text-image",
  "temperature": 0.0,
  "seed": 17001,
  "max_tokens": 16,
  "cache_prompt": false,
  "constraint": "none",
  "request_payload_sha256": "...",
  "http_status": 200,
  "latency_ms": 5581,
  "raw_output": "Yes.",
  "format_exact": false,
  "format_word": true,
  "semantic_label": "yes",
  "semantic_correct": true,
  "prompt_tokens": null,
  "cached_tokens": null,
  "completion_tokens": null,
  "error": null
}
```

注意：若板端锁定版本不返回 usage/timings，字段保留为 null，并在 session manifest 写明“不支持”，不要用耗时猜 token 数。

### 3.4 session manifest 最小字段

- schema version；
- session/run ID 与开始结束时间；
- Git commit 与工作树是否干净；
- RK3588 OS/kernel/CPU/RAM；
- `rk3588-vlm`、`llama-server`、模型和 mmproj 的 SHA-256；
- llama.cpp 完整 commit/version；
- server 完整启动参数和 PID；
- 相机设备、caps、FPS、曝光/白平衡/对焦状态；
- 实验矩阵、随机化 seed 和实际运行顺序；
- 每个输入文件和输出文件的 SHA-256；
- 中断、补跑、相机重启和 server 重启事件。

## 4. 实施阶段与验收门

## 阶段 S0：实验基础设施修复

### S0.1 统一 server 生命周期

实施：

- 删除 `board_exp_run.sh` 和 C 内部同时起 server 的行为；
- 实现 managed/external 二选一；
- server 日志保存到 run 目录；
- health check 同时检查预期 PID 仍存活。

验收：

- `ss -ltnp` 显示一个 8088 listener；
- 故意占用 8088 时 managed 模式明确失败；
- external 模式退出后 server 仍存活；managed 模式退出后 server 被清理；
- Ctrl+C、timeout 和异常路径均无遗留进程。

### S0.2 统一请求构造

实施：

- Python 只保留一个 `build_payload()`；
- C 增加与之对应的显式参数；
- 保存 canonical payload 或其哈希；
- 不再让 `run_static_nocache.py` 自己维护一份不同逻辑。

验收：

- 同一图片、prompt 和参数经 C/Python 产生相同语义 payload；
- 图文顺序可显式选择并写入记录；
- `max_tokens`、temperature、seed、cache 不出现隐式默认差异；
- 完整响应保存，可解析 usage/timings 时不得丢弃。

### S0.3 修复指标和结构化日志

实施：

- 增加格式分类器；
- 语义分类与真值分离；
- JSONL 为主数据，人类可读日志仅作诊断；
- 旧 `analyze.py` 标为 legacy，新分析器读取 JSONL。

最低测试用例：

| 输出 | `format_word` | `semantic_label` |
|---|---:|---|
| `Yes.` | true | yes |
| `No.` | true | no |
| `There is a fan.` | false | yes |
| `No fan is visible.` | false | no |
| `Yes, there is a fan.` | false | yes |
| `If there is a fan, answer yes.` | false | unknown |
| `yes no` | false | unknown |
| 空字符串 | false | unknown |

验收：所有测试通过，且 σ=7 历史日志重算为 `format_word=30/30`、`yes_rate=0/30`。

### S0.4 不可变数据目录与校验和

验收：

- 同名 run 再次启动直接失败；
- 中断后 `--resume` 从缺失 round 继续，并保留已写 JSONL；
- SFTP 后本地/板端 SHA-256 一致；
- 任何失败都写入 manifest，而不是静默跳过。

只有 S0 全部通过后，才开始正式板端实验。

## 5. 下一阶段实验矩阵

## 实验 S2-E0：能力探测与冒烟测试

### 目的

确定板端锁定版 llama.cpp 实际支持哪些请求字段，避免按最新版文档盲目实现。

### 能力探测

对单张测试图分别发送：

1. `seed`；
2. `cache_prompt=false`；
3. `n_probs=5`；
4. request-level `grammar`；
5. chat `response_format` JSON schema；
6. 检查 response 中 `usage`、`timings`、`cached_tokens`。

最新版 llama.cpp 官方 server 文档列出了 `response_format`、usage/timings 等能力，grammar 文档说明 completion endpoint 可接受 request-level `grammar`；但**本实验只以板端锁定版本的实测响应为准**：

- <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- <https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md>

### 样本

- 1 张正样本 + 1 张负样本；
- 每个能力 2 次请求；
- 不用于论文效应估计。

### 通过标准

- 每个字段被标记为 supported / ignored / rejected；
- 保存 HTTP 状态和完整响应；
- 形成 `capabilities.json`，后续 runner 只使用已确认能力。

## 实验 S2-E1：同帧请求路径与图文顺序消融（最高优先级）

### 研究问题

先前静态/在线差异是否可由内容顺序或客户端路径解释？

### 数据

- 从在线相机一次性冻结 20 张 640×480 图像：10 张目标存在、10 张目标不存在；
- 每张图人工记录真值；
- 同一组 JPEG 字节用于所有条件，不重新编码；
- 正式确认可扩到 30+30。

### 条件

| 因子 | 水平 |
|---|---|
| 客户端 | C / Python |
| content order | text→image / image→text |
| cache | false |
| temperature | 0.0 |
| constraint | none |

总请求数（pilot）：20 图 × 4 条件 = 80 次，256M 先跑；若发现客户端主效应，再用 500M 复核。

### 设计

- 每张图的四个条件随机排序；
- 相同 server session；
- 每个条件 payload 字段完全一致，只有客户端或顺序按设计变化；
- C/Python 路径必须发送同一个系统 prompt；
- 不允许使用历史静态图片替代配对帧。

### 主要指标

- `format_word`；
- `semantic_correct`；
- C/Python 在相同 order 下的逐图一致率；
- 两种 order 的逐图转移表。

### 判断标准

- 若 C/Python 在同 payload 下仍不同，优先查请求序列化、chat template、server slot 或缓存；
- 若只有 order 不同，则旧静态/在线结论暂不成立，后续所有实验固定 order；
- 若均无差异，才能进入“固定图 vs 帧序列”实验。

## 实验 S2-E2：固定图、真实帧序列与受控微扰

### 研究问题

输出变化来自“图像逐帧不同”，还是来自缓存/序列状态？多大的输入变化会改变输出形态？

### 输入集合

选择一张高细节基准帧 `I0`，生成：

- 完全相同字节重复；
- 仅 JPEG 重编码：quality 100/95/90/80；
- 轻微像素噪声：预定义幅度 1/2/4；
- 从同一在线 session 采集的真实连续帧 20 张；
- 真实帧的随机打乱序列。

每个变体记录：字节哈希、解码像素哈希、JPEG 大小、平均亮度、清晰度、相对 I0 的 MAE/SSIM（若依赖允许）。

### 条件

主分析：

- 256M；
- temperature=0；
- cache_prompt=false；
- 固定 content order；
- server 在每个大条件前重启；
- 无受限解码。

缓存消融：

- 只对“固定字节重复”和“真实连续帧”增加 cache_prompt=true；
- 从 usage/timings 验证是否真的缓存；若版本不返回指标，则每个条件独立重启 server，并将缓存结论降级。

### 关键对比

1. 相同 I0 重复 vs 真实连续帧；
2. 相同图像像素、不同 JPEG 编码；
3. 真实顺序 vs 打乱顺序；
4. cache off vs on。

### 可支持的结论

- 若 cache off + temp 0 下真实顺序与打乱顺序一致，序列历史不是主要解释，差异更可能由每张图像本身造成；
- 若仅 JPEG 重编码即可翻转输出，结论应表述为“编码/像素微扰敏感”，而不是“实时性必要”；
- 若相同图片在不同 server 状态下改变，需进一步查 server slot/cache，不应解释为视觉机制。

## 实验 S2-E3：模糊与 `videoconvert` sham 配对实验

### 研究问题

σ=1 的效果来自 blur，还是来自双 `videoconvert`/重编码管线？

### 数据

- 256M 主实验；
- 至少 30 张正样本 + 30 张负样本；
- 图像来自至少 5 个独立采集 session，每个 session/类别约 6 张；
- 使用冻结图像离线生成所有变体，保证每个条件共享同一源帧。

### 变体

| 条件 | 处理 |
|---|---|
| RAW | 原 JPEG 字节不变 |
| REENCODE | jpegdec → jpegenc，无额外处理 |
| SHAM | jpegdec → videoconvert → videoconvert → jpegenc |
| B1 | 与 SHAM 相同 + gaussianblur σ=1 |
| B2 | σ=2 |
| B3 | σ=3 |
| B5 | σ=5，作为语义退化边界 |
| DOWN320 | 下采样 320 后再放大回 640 |
| DOWN160 | 下采样 160 后再放大回 640 |

要求显式固定 JPEG quality、色彩格式、输出 640×480 和插值方式。不要再把实际输出为 320×240 的条件描述成“显示 640”。

### 参数

- temperature=0 主分析；
- content order 固定；
- cache=false；
- 无 constraint；
- 每张图的变体顺序随机；
- 同一 server session 内完成一个区组，区组间可重启 server。

### 指标

- 主要：`format_word`；
- 共同主要安全指标：`semantic_correct`；
- 次要：yes/no/unknown、延迟、输出长度；
- 图像指标：亮度、颜色均值、清晰度、JPEG 大小、相对原图 MAE。

### 判断规则

- RAW vs REENCODE：JPEG 重编码效应；
- REENCODE vs SHAM：色彩转换/管线效应；
- SHAM vs B1：轻微模糊的净效应；
- B1→B5：格式与语义的剂量响应；
- 只有 SHAM vs B1 显示稳定差异，才可以把 σ=1 的变化归因于 blur。

## 实验 S2-E4：探测式措辞的语义门槛

### 研究问题

措辞 D 是否仅改变输出格式，还是也改变正负样本的判定阈值？

### 数据与设计

- 使用 S2-E3 的冻结正负帧；
- 每张原图离线生成 320、480、640 三档；
- 问题只比较 A 与 D，暂不扩展 B–F；
- 256M 主实验，500M 作为后续验证；
- temperature=0、cache=false、无 constraint；
- 同一帧的 A/D 顺序随机且配对。

### 条件数

```text
60 张图 × 3 分辨率 × 2 措辞 = 360 次推理
```

若板端时间有限，pilot 用 10 正 + 10 负，共 120 次；通过后再扩展。

### 主要结果

- 每个分辨率下 A vs D 的 `format_word`；
- 正样本敏感度、负样本特异度；
- A→D 的逐帧 yes/no 转移；
- 不再只用一个正场景的 yes_rate 推断“判定门槛”。

### 解释边界

- 若 D 同时减少假阳性和真阳性，可称其提高了经验判定阈值；
- 若只改变格式不改变正确性，可称其主要改变输出模板；
- 若结果只在单一分辨率出现，不应称为“全分辨率普适”。

## 实验 S2-E5：受限解码工程基线

### 目的

验证格式问题是否能由生成端硬约束稳定解决，同时保留语义准确率。

### 实现顺序

依据 S2-E0 能力探测选择：

1. 优先 request-level grammar，允许 `Yes/No/yes/no` 中预注册的形式；
2. 若 chat endpoint 不支持 grammar，尝试板端版本支持的 `response_format`/JSON schema；
3. 若都不支持，再评估 `/completion` + chat template + GBNF；
4. `max_tokens=2` 只作消融，不作为可靠约束方案，因为可能截断为 `There` 等无效输出；
5. `logit_bias` 只能作为探索，不等价于保证输出空间只有 yes/no。

### 条件

| 模型 | 分辨率 | 解码 |
|---|---|---|
| 256M | 320/640 | unconstrained / constrained |
| 500M | 320/640 | unconstrained / constrained |

数据至少包含 30 正 + 30 负冻结帧。所有条件同帧配对，temperature=0；若需要测试采样鲁棒性，再追加 temperature=0.1 + 固定 seed。

### 成功标准

- constrained 条件 `format_word=100%`；
- `semantic_correct` 的配对下降不超过预注册容忍度（建议绝对值 2 个百分点，样本较小时报告全部转移而不只看百分比）；
- 不增加 unknown；
- 延迟增量可接受；
- 记录 grammar/schema 的原文和 server 版本。

如果成功，这应成为工程推荐的第一选择；模糊、降采样和 prompt 改写只作为模型行为研究或无 grammar 环境下的备选。

## 实验 S2-E6：跨 session 在线复现

### 目的

量化 9%–67% 这类基线漂移，确认离线配对发现能否回到在线相机链路。

### 建议设计

- 至少 5 个独立 session，最好跨不同时段；
- 每个 session 同时包含目标存在与目标不存在场景；
- 每个场景运行平衡区组：A-control、D、SHAM、B1、constrained；
- 每个处理前后插入 A-control，或使用随机 AB/BA；
- 每个小区组 10–20 个精确关联帧；
- temperature=0 主分析；
- 自动记录曝光、亮度、帧差、JPEG 大小和相机重启事件。

实验单位以 session 为主，不把同一 session 的相邻帧当作完全独立重复。

## 6. 统计分析预注册建议

### 6.1 主要与次要终点

- 主要终点：`format_word`；
- 共同主要安全终点：`semantic_correct`；
- 次要：semantic yes/no/unknown、输出长度、延迟、首 token 概率（若支持）；
- 工程成功必须同时看格式和语义，不能把全部输出 `No.` 的条件称为成功恢复。

### 6.2 实验单位

- 冻结帧配对实验：frame 是配对单位，session 是聚类单位；
- 在线实验：session 是主要重复单位，相邻帧是 session 内观测；
- 对同一固定图的重复采样不能被称为 30 个独立图像样本。

### 6.3 建议检验

- 两条件同帧二元指标：McNemar 或配对置换；
- 多条件：二项混合效应模型，至少含 `(1 | session)`，必要时 `(1 | frame)`；
- session 少时：展示每个 session 原始比例 + 聚类 bootstrap，不依赖复杂模型；
- 多个措辞/σ 对比使用 Holm 校正；
- 报告效应量、95% CI 和转移计数，不只报告 p 值。

### 6.4 随机性

- temperature=0 为机制隔离的主分析；
- temperature>0 时每条请求显式记录 seed；
- 如果板端版本忽略 seed，必须在能力探测中标明，并把重复输出视为随机抽样而非可复现序列；
- 随机化运行顺序的 seed 与模型采样 seed 分开记录。

## 7. 推荐的代码开发顺序

### 第一个提交：正确性修复

1. 修复双 server 所有权；
2. 增加 managed/external 模式；
3. 修复 strict 指标，补 CTest；
4. 统一 max_tokens/seed/cache/content order 参数；
5. 将 server 日志从 `/dev/null` 改为 run 文件。

### 第二个提交：实验数据协议

1. JSONL 轮次记录；
2. manifest + SHA-256；
3. 精确帧保存与 round 关联；
4. 唯一 run 目录、防覆盖、resume；
5. SSH 配置移出仓库。

### 第三个提交：统一 runner

1. `request_client.py`；
2. `run_stage2.py`；
3. 条件 JSON 配置、随机区组；
4. SFTP 校验与 trap 清理；
5. 能力探测 S2-E0。

### 第四个提交：分析器

1. JSONL schema 校验；
2. 自动生成 round CSV、run CSV、session CSV；
3. Wilson CI、配对转移、Holm 校正；
4. 历史日志导入器单独放在 `legacy` 路径；
5. 一条命令重建论文表格。

### 第五个提交：正式实验

按 S2-E1 → E2 → E3 → E5 → E4 → E6 顺序进行。E5 排在 E4 前，是因为受限解码对工程价值更直接；若时间紧，措辞细化可以后置。

## 8. 板端正式运行前检查表

- [ ] `git status`、Git commit 和二进制哈希写入 manifest；
- [ ] 模型/mmproj 哈希与预注册配置一致；
- [ ] 8088 只有一个监听 server；
- [ ] server log 可读且记录版本；
- [ ] 正/负样本真值已经人工确认；
- [ ] content order 明确；
- [ ] temperature、seed、max_tokens、cache、constraint 全部显式；
- [ ] run 顺序由 seed 生成并已冻结；
- [ ] 目标目录不存在，防覆盖检查生效；
- [ ] 每轮 frame SHA 与推理记录一一对应；
- [ ] pilot 结果经过新分析器复算；
- [ ] 板端剩余存储空间足够；
- [ ] 中断与清理演练不会遗留 server/GStreamer；
- [ ] 拉取后校验 SHA-256，再决定是否清理板端副本。

## 9. 暂时不建议做的工作

在 S0 和 S2-E1 完成前，不建议：

- 继续增加更多 σ 档位；
- 直接用历史 36%/45%/67% 做新的帧级 Fisher 检验；
- 继续用固定文件名覆盖日志；
- 用静态旧图与在线新帧直接比较；
- 把 `No.` 计为格式失败；
- 把 `yes_rate` 直接称为准确率；
- 依据两个模型尺寸推断规模规律；
- 在没有 sham control 时把 σ=1 的效果归因于模糊；
- 在没有正负样本时声称某措辞提高或降低感知阈值；
- 在没有直接 token/usage 记录时用延迟证明视觉 token 恒定。

## 10. 最小可行下一轮

如果开发和板端时间有限，最小闭环应包含：

1. 修复双 server、指标、JSONL 和防覆盖；
2. 冻结 10 张正样本 + 10 张负样本；
3. 完成 S2-E1：同帧 C/Python × 两种 content order；
4. 完成 S2-E3 的 RAW/REENCODE/SHAM/B1 四条件；
5. 完成 S2-E5 的 unconstrained/constrained；
6. 所有比较使用 temperature=0、cache=false、同帧配对；
7. 自动生成格式率、语义正确率、逐帧转移和 manifest。

这个最小组合能一次性回答：旧静态/在线结论是否受请求顺序影响、σ=1 是否受管线混杂、以及受限解码能否成为可靠工程解法。完成后再决定是否投入多 session 大样本实验。

## 11. 阶段完成定义

下一阶段只有同时满足以下条件才算完成：

- 任意论文数字可由原始 JSONL 一条命令重建；
- 任意 round 可定位到确切 JPEG SHA-256、request 参数和 raw response；
- 同名运行不会覆盖数据；
- 格式合规与语义正确完全分开；
- 静态/在线比较使用同帧、同 payload；
- 模糊结论包含 sham control；
- 工程建议包含 constrained decoding 的实测结果；
- 至少完成一次正负样本、跨 session 的在线复现；
- 所有强机制结论均能对应到明确的对照实验，否则保留为假设。
