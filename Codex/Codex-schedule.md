# RK3588 VLM 下一阶段实验计划书

> 文档日期：2026-08-12  
> 执行方式：一个实验只使用一个独立 Claude 对话窗口  
> 代码位置：`Codex/`  
> 实验数据位置：建议使用板端 `/userdata/rkvlm-stage2/`，归档后再同步到仓库外的数据盘  
> 关联文档：`Codex-Experiment.md`、`Codex-preview.md`

## 1. 使用原则

本计划把下一阶段工作拆成若干互不混杂的实验包。每个 Claude 对话窗口只处理一个编号实验，不在同一窗口顺便推进下一个实验。

每个实验窗口必须完成以下闭环：

1. 读取本实验所需的最小文件；
2. 检查本实验前置条件；
3. 只修改本实验允许修改的代码和配置；
4. 在 RK3588 上完成 pilot 或正式运行；
5. 生成机器可读结果和人工总结；
6. 生成校验和并封存实验目录；
7. 写出不超过 200 行的交接摘要；
8. 结束当前对话，不继续下一个实验。

单个窗口禁止：

- 同时实现两个实验；
- 使用历史日志替代本实验 JSONL 主数据；
- 修改已经归档的实验结果；
- 因某个实验失败而临时改变另一个实验的设计；
- 使用固定文件名覆盖前一次结果；
- 在未记录原因时重启相机、server 或板端；
- 把格式合规率、yes rate 和语义准确率混为一个指标；
- 实验完成后继续做“顺手优化”。

## 2. 固定目录协议

建议在 Linux/RK3588 上建立：

```text
/userdata/rkvlm-stage2/
├── code/                         # Codex 代码工作副本
├── models/                       # 模型和 mmproj，只读
├── datasets/
│   ├── source/                   # 原始冻结帧
│   └── derived/                  # 变体数据集
├── sessions/
│   └── <session_id>/
│       ├── session_manifest.json
│       └── <run_id>/
│           ├── manifest.json
│           ├── plan.jsonl
│           ├── rounds.jsonl
│           ├── server.log
│           └── checksums.sha256
└── archive/
    └── <experiment_id>/
        └── <archive_id>/
            ├── input/            # 实际使用的配置和数据集 manifest
            ├── code/             # 代码 commit、diff、版本信息
            ├── raw/              # 原始 run 目录，只读
            ├── analysis/         # CSV/JSON/图表
            ├── SESSION-REPORT.md
            ├── HANDOFF.md
            └── checksums.sha256
```

ID 规则：

```text
session_id = YYYYMMDDTHHMMSS+0800_board01
run_id     = <experiment_id>_<model>_<short-condition>_rNN
archive_id = YYYYMMDDTHHMMSS+0800_<git-short-sha>
```

正式目录已经存在时必须报错。中断后只能通过同一个 `session_id + run_id` 加 `--resume` 继续；不得删除目录后伪装成首次运行。

## 3. 每个对话窗口的固定输入

每次开始一个新对话，只给 Claude 以下材料：

- 本计划书；
- 当前实验对应章节；
- `Codex/README.md`；
- 本实验使用的 JSON 配置；
- 上一个实验的 `HANDOFF.md`；
- 必要的报错、板端版本和目录清单。

不要把所有历史终端输出和所有实验日志一次性塞进新窗口。原始结果留在归档中，Claude 需要证据时再按文件读取。

新窗口第一条指令建议使用：

```text
你本次只执行实验 <实验编号>，不要开始后续实验。
先读取 Codex/Codex-schedule.md 中对应章节、Codex/README.md、给定配置和上一阶段 HANDOFF.md。
完成代码检查、板端运行、结果分析、SESSION-REPORT.md、HANDOFF.md 和归档校验和。
若前置条件不满足，记录阻塞证据后停止，不得改做其他实验。
实验完成后结束对话。
```

## 4. 每次实验的固定输出

每个归档必须包含以下文件。

### 4.1 `SESSION-REPORT.md`

```markdown
# <experiment_id> 实验记录

- 状态：complete / partial / blocked / invalid
- session_id：
- run_id：
- 开始时间：
- 结束时间：
- Git commit：
- 工作树是否干净：
- 模型 SHA-256：
- mmproj SHA-256：
- llama-server 版本：
- server 模式：managed / external
- server PID：
- 数据集 ID：
- 数据集 SHA-256：
- 随机化 seed：

## 本次改动

## 实际执行命令

## 样本与失败

## 主要结果

## 语义安全结果

## 与预注册方案的偏差

## 结论边界

## 后续建议
```

### 4.2 `HANDOFF.md`

`HANDOFF.md` 只保存下一窗口真正需要的事实，建议不超过 200 行：

```markdown
# Handoff

## 已完成

## 未完成或无效

## 确认的接口能力

## 冻结的文件与 SHA-256

## 下一实验可直接使用的输入

## 不得重复的工作

## 当前已知风险
```

### 4.3 `checksums.sha256`

在归档根目录运行：

```bash
find . -type f ! -name checksums.sha256 -print0 \
  | sort -z \
  | xargs -0 sha256sum > checksums.sha256
sha256sum -c checksums.sha256
```

归档完成后，将整个目录改成只读：

```bash
chmod -R a-w "/userdata/rkvlm-stage2/archive/<experiment_id>/<archive_id>"
```

如果以后发现归档有问题，创建新的补充归档，不直接修改只读归档。

## 5. 总体执行顺序

| 顺序 | 对话窗口 | 实验编号 | 目标 | 是否允许进入下一项 |
|---:|---|---|---|---|
| 1 | W00 | S0-PREFLIGHT | 固化环境、数据协议和单 server 所有权 | 所有门通过 |
| 2 | W01 | S2-E0 | 探测板端 llama-server 能力 | 形成 capabilities.json |
| 3 | W02 | S2-E1 | 同帧图文顺序消融 | 确定唯一正式 payload |
| 4 | W03 | S2-E2 | 固定字节、JPEG 微扰与帧序列 | 区分输入变化和服务状态 |
| 5 | W04 | S2-E3-PILOT | RAW/REENCODE/SHAM/B1 pilot | 管线与配对无误 |
| 6 | W05 | S2-E3-FULL | 模糊/sham 正式实验 | 正负样本与 session 足够 |
| 7 | W06 | S2-E5-PILOT | 受限解码 pilot | 选定可用约束方案 |
| 8 | W07 | S2-E5-FULL | 受限解码正式实验 | 格式和语义双门通过 |
| 9 | W08 | S2-E4-PILOT | A/D 措辞与分辨率 pilot | 确认值得扩样本 |
| 10 | W09 | S2-E4-FULL | 措辞与经验阈值正式实验 | 正负样本均完成 |
| 11 | W10 | S2-E6 | 跨 session 在线复现 | 至少五个 session |
| 12 | W11 | S2-FINAL | 冻结统计表、图和论文证据索引 | 全部数字可重建 |

任何窗口被标记为 `blocked` 或 `invalid` 时，下一窗口只能是同一实验的修复/重跑窗口，不能跳到新实验。

---

## 6. W00：S0-PREFLIGHT 实验基础设施门

### 本窗口唯一目标

证明实验框架不会覆盖数据、不会启动两个 server、能够把一次推理定位到确切 JPEG、payload 和完整响应。

### 输入

- `Codex/codex_vlm/`；
- `Codex/configs/s2e1-order.example.json`；
- 一张人工确认的正样本和一张负样本；
- 板端模型、mmproj、llama-server 路径。

### 允许的代码工作

- 补齐 Linux CLI 和配置解析；
- 修正 managed/external 生命周期；
- 修正 JSONL、manifest、防覆盖、resume 和 checksum；
- 补齐 Linux 精确帧捕获命令；
- 修正明显阻止框架运行的错误。

禁止加入新的研究条件。

### 必做检查

1. managed 模式启动前若 8088 已有健康服务，必须拒绝运行；
2. external 模式结束后不得终止外部 server；
3. managed 模式异常退出后只能清理自己创建的进程组；
4. 同名 run 二次启动必须失败；
5. `--resume` 不得重复成功 round；
6. 每条 `rounds.jsonl` 必须有 frame SHA-256 和 request payload SHA-256；
7. `request_audit` 不保存 base64 图像，只保留帧哈希占位；
8. raw response、usage、timings 不得在客户端被丢弃；
9. `format_word` 与 `semantic_correct` 独立；
10. `checksums.sha256` 能通过校验。

### 完成标准

- 两张图 × 两种 content order 的 4 次请求可以形成完整 run；
- 端口上始终只有一个实际 server owner；
- 人工抽查一条记录，JPEG 哈希与实际文件一致；
- 故意中断后可以 resume；
- 归档状态为 `complete`。

### 本窗口结束时的决策

只能输出“基础设施通过”或“未通过”。未通过则下一窗口继续 W00，不进入能力探测。

---

## 7. W01：S2-E0 llama-server 能力探测

### 本窗口唯一目标

确定板端锁定版 server 对 `seed`、`cache_prompt`、`n_probs`、`grammar`、`response_format`、`usage` 和 `timings` 的实际行为。

### 输入

- W00 的 `HANDOFF.md`；
- W00 冻结的正、负样本各一张；
- `rkvlm-exp probe`；
- server 完整版本和启动命令。

### 执行设计

每张图分别发送：

1. baseline；
2. 显式 seed；
3. `cache_prompt=false`；
4. `n_probs=5`；
5. yes/no grammar；
6. JSON schema response format。

每种能力运行两次，共 2 图 × 6 条件 × 2 次 = 24 次请求。该实验只做能力判定，不做论文效应估计。

### 输出

- `capabilities.raw.json`：完整响应；
- `capabilities.json`：每项为 `supported`、`accepted_but_unverified`、`ignored` 或 `rejected`；
- `SESSION-REPORT.md`；
- `HANDOFF.md`。

### 判定规则

- HTTP 2xx 只表示 accepted，不自动等于 supported；
- 字段出现在 response 或产生可重复行为差异，才能判 supported；
- 无法证明生效时写 `accepted_but_unverified`；
- 后续配置只能使用 supported 能力；
- 若 grammar 和 JSON schema 都不可用，不阻塞 E1/E2/E3，只在 E5 前解决。

### 完成标准

所有探测项均有明确状态和原始证据，且 capabilities 文件写入后续归档。

---

## 8. W02：S2-E1 同帧图文顺序消融

### 本窗口唯一目标

判断旧实验中的静态/在线差异是否混入了 `text-image` 与 `image-text` 顺序差异，并冻结后续正式实验的唯一 payload。

### 数据

- pilot：10 张正样本 + 10 张负样本；
- 所有条件复用完全相同 JPEG 字节；
- 每张图必须有人工作出的 ground truth；
- 不重新编码图像。

### 条件

- `text-image`；
- `image-text`。

temperature=0、cache=false、max_tokens=16、constraint=none、同一 server session。

若还要比较 C/Python 客户端，必须保证两者 canonical payload 语义等价；若当前新架构已经完全替代 C 客户端，本窗口只做两个 content order，不为了复刻旧架构再引入 C。

### 请求数

```text
20 张 × 2 个顺序 = 40 次
```

### 主要输出

- 两种顺序的 `format_word`；
- 两种顺序的 `semantic_correct`；
- 逐帧 yes/no/unknown 转移；
- 完整 payload 哈希；
- 选定的正式 content order。

### 决策规则

- 若顺序显著改变格式或语义，后续固定表现更好的顺序，并把旧静态/在线结论降级；
- 若语义差异不明显但格式差异明显，优先选择格式合规更高的顺序；
- 若两者均无明显差异，默认选 `text-image`，与当前 C payload 习惯保持一致；
- 选定顺序后写入 `HANDOFF.md`，后续实验不得自行改变。

### 完成标准

40 次计划请求全部成功，或失败请求有一次独立 attempt 的补跑记录；选择唯一正式 content order。

---

## 9. W03：S2-E2 固定字节、JPEG 微扰与帧序列

### 本窗口唯一目标

区分输出变化是由图像字节/像素变化、JPEG 编码、真实帧变化还是 server 状态造成。

### 输入集合

选择一张清晰正样本 `I0` 和一张清晰负样本 `N0`，为每张构造：

- 完全相同字节重复 10 次；
- JPEG quality 100/95/90/80；
- 同一在线 session 的连续真实帧 10 张；
- 同一批真实帧随机打乱顺序。

若像素噪声工具已经可靠，再追加幅度 1/2/4；否则不要在本窗口临时扩代码。

### 固定参数

- 使用 W02 选定 content order；
- temperature=0；
- cache_prompt=false；
- constraint=none；
- 256M 模型；
- 每个大条件前重启 managed server，并记录 PID。

### 缓存消融

只在 capabilities 证明 `cache_prompt` 可用时，追加：

- 相同 I0 字节，cache=true；
- 连续帧，cache=true。

若没有 cached token 证据，只能报告请求字段行为，不得声称实际命中缓存。

### 结论规则

- 相同字节在 temp=0 和新 server 上仍变化：优先判为服务/解码非确定性；
- JPEG 重编码翻转：表述为编码或像素微扰敏感；
- 连续帧与打乱顺序一致：不支持序列历史是主因；
- 连续帧和固定图不同，但 JPEG 微扰也能复现：不得称“实时相机特有”。

### 完成标准

每种解释都对应明确对照，不能只展示输出样例。

---

## 10. W04：S2-E3-PILOT RAW/REENCODE/SHAM/B1

### 本窗口唯一目标

验证图像变体生成、`source_frame_id` 配对、GStreamer sham 和随机化流程正确，不在本窗口追求统计显著性。

### 数据

- 5 张正样本 + 5 张负样本；
- 至少来自两个采集 session；
- 每个源帧生成 RAW、REENCODE、SHAM、B1 四个变体；
- 所有变体最终为 640×480 JPEG；
- 显式固定 JPEG quality 和 subsampling。

### 请求数

```text
10 个源帧 × 4 个变体 = 40 次
```

### 必查项目

- 每个变体有唯一字节 SHA-256；
- 每组四个变体共享同一 `source_frame_id`；
- `transform_id` 为 RAW/REENCODE/SHAM/B1；
- SHAM 确实包含两次 `videoconvert`；
- B1 只比 SHAM 多 blur，不混入分辨率变化；
- 分析器能输出 RAW↔REENCODE、REENCODE↔SHAM、SHAM↔B1 的配对转移。

### 无效条件

- 输出尺寸不一致；
- SHAM 和 B1 的编码参数不同；
- 变体缺失或错误关联 source frame；
- 使用在线变化帧分别跑四个条件而非冻结源帧。

### 完成标准

数据链路无错、40 次请求完成、配对分析正确。pilot 结果仅用于判断流程和效应方向，不写成正式结论。

---

## 11. W05：S2-E3-FULL 模糊与 sham 正式实验

### 本窗口唯一目标

估计轻微模糊相对 sham 的净格式效应，并同时验证语义安全性。

### 数据

- 至少 30 张正样本 + 30 张负样本；
- 至少 5 个独立 source session；
- 每个源帧生成 RAW、REENCODE、SHAM、B1、B2、B3、B5、DOWN320、DOWN160；
- 若总板端时间不足，正式主分析至少保留 RAW、REENCODE、SHAM、B1、B3。

### 主对比

1. RAW vs REENCODE：重编码效应；
2. REENCODE vs SHAM：颜色/管线效应；
3. SHAM vs B1：轻微模糊净效应；
4. B1 vs B3/B5：剂量响应；
5. SHAM vs DOWN320/DOWN160：分辨率扰动。

### 共同主要指标

- `format_word`；
- `semantic_correct`。

所有工程成功结论必须同时报告两个指标。全部回答 No 即使格式为 100%，也不能判成功。

### 统计输出

- 每个 arm 的 n、率、Wilson 95% CI；
- 同帧转移 00/01/10/11；
- exact McNemar p 值；
- 每个 source session 的原始比例；
- 多重比较时明确标注 Holm 校正结果。

### 完成标准

只有 SHAM vs B1 在多个 session 中方向一致，且语义正确率未明显恶化，才能把变化归因于轻微 blur。

---

## 12. W06：S2-E5-PILOT 受限解码

### 本窗口唯一目标

依据 W01 capabilities，选定一个板端真正可用的 yes/no 约束实现。

### 方案顺序

1. request-level grammar；
2. chat response_format / JSON schema；
3. `/completion` + 明确 chat template + GBNF；
4. 若全部不可用，记录 blocked，不用 `max_tokens=2` 冒充硬约束。

### 数据

- 5 张正样本 + 5 张负样本；
- 320 和 640 两档；
- unconstrained 与 candidate constrained 同帧配对；
- 256M 先运行。

### 请求数

```text
10 张 × 2 分辨率 × 2 解码 = 40 次
```

### 成功门

- constrained 的 `format_word=100%`；
- 能返回 yes 和 no，而非坍缩为同一个答案；
- 无 unknown；
- 完整记录实际 grammar/schema；
- server 没有静默忽略约束；
- 记录延迟变化。

### 完成标准

选择唯一 constrained 实现并冻结配置；若无法实现，输出 `blocked` 和所有原始响应，不转做 prompt 优化。

---

## 13. W07：S2-E5-FULL 受限解码正式实验

### 本窗口唯一目标

验证受限解码能否成为工程默认解法，而非只提高格式率。

### 数据和条件

- 至少 30 正 + 30 负；
- 256M 与 500M；
- 320 与 640；
- unconstrained 与 W06 选定 constrained；
- temperature=0；
- 同帧配对。

总请求数：

```text
60 张 × 2 模型 × 2 分辨率 × 2 解码 = 480 次
```

时间不足时可拆成两个同实验窗口：W07a 256M，W07b 500M。二者仍归档在同一个实验编号下，W07a 完成后不得进入 E4，必须先完成 W07b。

### 工程成功标准

- constrained `format_word=100%`；
- 相对 unconstrained 的语义正确率下降不超过预注册的绝对 2 个百分点；
- 不增加 unknown；
- yes/no 两类都有输出；
- 延迟增量可接受且有原始数据。

### 输出结论

- 双门通过：推荐 constrained 作为工程默认；
- 格式通过、语义不通过：不得推荐；
- 只在部分模型/分辨率通过：只对通过的组合推荐。

---

## 14. W08：S2-E4-PILOT 措辞与分辨率

### 本窗口唯一目标

判断问题 A 与探测式问题 D 是否值得进入正式扩样本，不重复 B–F 的宽泛搜索。

### 数据

- 10 张正样本 + 10 张负样本；
- 每张图生成 320、480、640；
- 问题 A 与 D；
- 256M；
- unconstrained；
- temperature=0；
- 固定 W02 content order。

请求数：

```text
20 张 × 3 分辨率 × 2 措辞 = 120 次
```

### 主要判断

- A/D 是否主要改变格式；
- A/D 是否同时改变正样本敏感度和负样本特异度；
- 效应是否只出现在单一分辨率；
- 是否出现全部 yes 或全部 no 的阈值坍缩。

### 扩样本门槛

只有 A/D 在至少两个分辨率显示方向一致的格式或语义转移，才进入 W09。否则归档 pilot，取消 W09，并在总表中注明“未扩样本”。

---

## 15. W09：S2-E4-FULL 措辞与经验阈值

### 本窗口唯一目标

在正负样本和多 session 数据上估计 A/D 的格式效应与经验判定阈值变化。

### 数据

- 至少 30 正 + 30 负；
- 至少 5 source session；
- 320/480/640；
- A/D；
- 256M 主实验；
- 若 W08 显示强而稳定的效应，再追加 500M 验证。

### 结论语言

- D 同时减少假阳性和真阳性：可称提高经验判定阈值；
- 只改变格式，不改变语义转移：称改变输出模板；
- 只在单一分辨率出现：限定到该分辨率；
- 不得用单一正场景的 yes rate 推断感知阈值。

### 完成标准

报告格式率、敏感度、特异度、unknown、逐帧转移和 session 变异。

---

## 16. W10：S2-E6 跨 session 在线复现

### 本窗口唯一目标

把离线配对结论带回真实在线相机链路，并量化跨 session 漂移。

### 设计

- 至少 5 个独立 session，尽量跨不同时段；
- 每个 session 包含目标存在与目标不存在；
- 每个小区组使用同一时段冻结的精确帧；
- 条件至少包括 A-control、最佳输入处理条件、constrained；
- 每个处理前后插入 A-control，或使用平衡 AB/BA；
- 每个小区组 10–20 个精确关联帧；
- temperature=0。

### 每帧必须记录

- capture sequence；
- wall-clock UTC 与 monotonic 时间；
- JPEG SHA-256 和字节数；
- source session；
- 图像宽高；
- ground truth；
- 请求条件和 payload hash；
- server PID；
- 相机或 server 重启事件。

如依赖允许，追加平均亮度、清晰度、帧差和 JPEG 大小；这些特征是解释变量，不替代图像本身。

### 实验单位

以 session 为主要重复单位。不得把同一 session 的相邻 100 帧当成 100 个独立 session。

### 完成标准

- 至少 5 session 均有正负样本；
- 每个 session 独立展示 arm 比例；
- 报告 session 间范围和聚类置信区间；
- 明确离线结果是否在线复现。

---

## 17. W11：S2-FINAL 统计冻结与论文证据索引

### 本窗口唯一目标

不再运行新实验，只从只读归档重建所有表格、图和结论证据。

### 输入

- W00–W10 的只读 archive；
- 所有 `checksums.sha256`；
- 每个实验的 `SESSION-REPORT.md` 与 `HANDOFF.md`。

### 工作内容

1. 校验所有归档哈希；
2. 汇总有效、无效、partial 和 blocked 实验；
3. 从 JSONL 重建 round、run、session 级表格；
4. 生成论文所需格式率、语义正确率、转移表和置信区间；
5. 为每个数字建立证据索引；
6. 标注所有方案偏差；
7. 冻结最终分析版本。

### 证据索引格式

```csv
claim_id,claim_text,experiment_id,archive_id,source_file,filter,metric,value
C001,...,S2-E3,...,rounds.jsonl,...,format_word_rate,...
```

### 完成标准

- 论文中的任意数字都能定位到 archive、JSONL、filter 和计算字段；
- 不从人工日志抄录主结果；
- 没有证据索引的强结论不得进入论文；
- 最终分析目录只读并带校验和。

## 18. 阻塞与重跑规则

### 18.1 可 resume 的情况

- SSH 会话断开；
- 单个 HTTP 请求超时；
- 用户主动中断；
- 板端临时存储不足但原目录仍完整。

同 run 使用 `--resume`，失败 round 的 attempt 增加，成功 round 不重复。

### 18.2 必须新建 run 的情况

- 修改 experiment JSON；
- 修改数据集或任何图像字节；
- 修改模型、mmproj、server 启动参数；
- 修改 prompt、content order、temperature、cache 或约束；
- server commit 改变；
- 发现旧 run 使用错误实现。

旧 run 标记 `invalid`，保留原数据，新建 run_id；不得覆盖。

### 18.3 必须停在当前实验的情况

- ground truth 未确认；
- 端口存在第二个 owner；
- 无法把 round 关联到精确 JPEG；
- JSONL 丢失 raw response；
- 数据集变体无法配对；
- 校验和失败；
- 归档目录不完整。

## 19. 给每个 Claude 窗口的结束指令

```text
停止继续开发下一实验。
请只完成当前实验的：
1. SESSION-REPORT.md；
2. HANDOFF.md；
3. 原始目录和分析目录清单；
4. checksums.sha256 校验结果；
5. 当前实验状态 complete/partial/blocked/invalid；
6. 下一窗口需要读取的最小文件列表。
不要开始下一编号实验，不要推送 GitHub，等待用户命令。
```

## 20. 当前推荐起点

目前应从 W00 开始，不直接运行正式 E1/E3/E5。W00 的首要任务是把 `Codex/` 新架构在 Linux/RK3588 上跑通，并冻结以下接口：

- external/managed 单 server 所有权；
- 不可覆盖 run 目录；
- JSONL round schema；
- exact JPEG 与 payload 哈希；
- resume 行为；
- Linux 精确帧 capture 命令；
- 归档与 checksum。

W00 通过后，为 W01 新开一个 Claude 对话窗口。此后严格按表格顺序，每个实验独立对话、独立记录、独立归档。
