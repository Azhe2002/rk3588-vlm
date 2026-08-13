# S2-E0 能力探测实验记录

- 状态：**complete**
- 实验日期：2026-08-13（本地时间），板端 21:53-22:05（板端时钟慢约 2.5 月）
- 板端：192.168.1.8（uptime 20min 后运行，无残留 server）
- Git commit：1b42a9a（实验脚本未提交，位于 experiment/run_s2e0.py + s2e0_probe.py）
- 模型：SmolVLM-256M-Instruct-Q8_0.gguf + mmproj-SmolVLM-256M-Instruct-Q8_0.gguf
- server 版本：`version: 1 (7af4279)`, GNU 10.2.1, aarch64
- server 模式：**external**（Python 驱动自起自清，单一 owner，规避双 server 问题）
- 请求：24/24 全部 HTTP 200

## 本次改动

- 新增 `experiment/s2e0_probe.py`（板端运行，2 图 × 6 条件 × 2 重复）
- 新增 `experiment/run_s2e0.py`（本地驱动：上传→起 server→跑→拉回→清理）
- 修复：`pkill -f llama-server` 会误杀命令自身 shell → 改 `pkill -x`

## 实际执行命令

```bash
# 板端 (run_s2e0.py 内)
LD_LIBRARY_PATH=/userdata/llama/bin llama-server -m .../SmolVLM-256M-Instruct-Q8_0.gguf \
  --mmproj .../mmproj-SmolVLM-256M-Instruct-Q8_0.gguf --port 8088 -t 8 > /tmp/s2e0/server.log 2>&1
python3 /tmp/s2e0/probe.py   # 24 请求
```

## 样本与失败

- 样本：正样本 = rk3588_640x480.jpg（真实 640 采集、风扇在画面）；负样本 = 本地生成纯灰 640×480 JPEG
- 失败：0/24（全部 200；探测脚本此前两轮因 cwd/pkill 问题启动失败，已修复，与探测结果无关）
- 请求参数：content order = text→image（与 C 客户端一致）；temperature=0.0（seed 组 0.5）；max_tokens=16

## 主要结果（capabilities.json 摘要）

| 能力 | 判定 | 证据 |
|------|------|------|
| seed | **supported** | temp=0.5 seed=17001 ×2 → 输出逐字节一致 |
| cache_prompt=false | **supported** | cached_tokens=0，两轮均 ~6.2s（默认时 rep2 0.3s/147 cached） |
| n_probs=5 | **supported** | choices[0].logprobs.content[].top_logprobs 每 token 5 候选+logprob |
| grammar (GBNF, chat) | **supported** | 输出被约束为 "Yes."/"No."，finish=stop |
| response_format json_schema | **supported** | 输出切换为 JSON；但 max_tokens=16 会截断（finish=length） |
| usage / timings | **supported** | 含 prompt_tokens_details.cached_tokens（缓存状态直接可观测） |

## 意外发现（对后续实验影响重大）

1. **静态图 + text→image 顺序 + t=0.0 → 描述句**："A industrial fan is on the corner of a shelf."
   历史结论"静态图 10/10 Yes."是用 image→text 顺序（Python 脚本）测的——**图文顺序很可能是
   静态/在线差异的主要混杂**。S2-E1（顺序消融）优先级升至最高。
2. 负样本（纯灰图）→ "No."：模型对无内容图像诚实回答，与 160×120/σ≥7 的"感知失败→No"一致。
3. 系统提示词跨图部分缓存（neg baseline rep1 cached_tokens=78）——同 server 内跨请求缓存行为正常。

## 结论边界

- 探测只验证"字段被接受并产生可观察行为变化"，不代表行为与最新版 llama.cpp 文档完全一致
- grammar 只在单一 GBNF（yes/no 枚举）上验证；复杂 grammar 未测
- seed 只在 temp=0.5 验证；temp=0.0 下 seed 无意义（greedy）

## 后续建议（下一实验 S2-E1 直接可用）

- **受限解码（S2-E5）可走 request-level grammar**——这是板端 7af4279 实测可用路径，无需改 C
- S2-E1 图文顺序消融可直接用本实验的 probe 脚本改造（同帧 × 2 顺序 × cache=false × t=0.0）
- 所有实验建议显式 cache_prompt=false + 记录 cached_tokens（该版本可直接观测缓存命中）
- 冻结帧数据集 + 正负样本需用户配合摆场景（负样本：风扇移出画面）
