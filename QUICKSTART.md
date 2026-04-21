# STS2MCP 快速上手

## 目录
1. [每次实验流程](#1-每次实验流程)
2. [首次安装与配置](#2-首次安装与配置)

---

## 1. 每次实验流程

### 第一步：启动游戏并开始一局

1. 打开 Steam，启动 **Slay the Spire 2**
2. 进入游戏，开始一局新游戏（选角色，进入地图或战斗界面）
3. 验证 Mod 正常运行：

```bash
curl http://localhost:15526/
# 正常响应: {"message": "Hello from STS2 MCP v0.3.3", "status": "ok"}
```

### 第二步：激活 Python 环境

```bash
cd /Users/jibingshi/Downloads/MASproject/STS2MCP/agents
source .venv/bin/activate
```

### 第三步：运行实验

**Baseline（单 Agent）**

```bash
python -u runner.py --system baseline --run-id bl_01 --verbose
```

**MAS（多 Agent）**

```bash
python -u runner.py --system mas --run-id mas_01 --verbose
```

**批量实验**

```bash
python -m experiments.run_batch --system mas --seeds 1,2,3,4,5 --model 4o-mini
```

每局开始前需在游戏中手动开启新一局，脚本自动检测游戏进入非菜单状态后开始记录。

### 第四步：查看结果

```bash
# 汇总表（所有 run 的得分）
cat runs/run_scores.md

# 对比分析（生成图表）
python -m experiments.analyze --runs-dir runs --out-dir runs/analysis
```

---

## 数据记录 / 后续分析

每次 `runner.py` 跑起来后，都会在 `agents/runs/` 下自动写入以下本地文件，可用于成功率、性能、决策行为等分析。**不需要额外开关**，只要指定 `--run-id` 就会产出。

### 产出文件

| 文件 | 写入时机 | 内容 | 典型用途 |
|------|---------|------|---------|
| `{run_id}_steps.jsonl` | 每个 agent 决策步追加一行 | `step, t, state_type, floor, hp, gold, proposals{tool,params,confidence,justification}, chosen, agreement` | 逐步复盘、分歧率、agent 贡献度、justification 文本分析 |
| `{run_id}_summary.json` | 运行结束时写入 | `run_id, system, seed, model, total_steps, wall_seconds, final{floor,act,hp,max_hp,gold,deck_size}, final_state_type, won` | 单次 run 的整体成绩 |
| `run_scores.md` | 运行结束时追加一行 | `run_id \| system \| model \| seed \| floor \| hp \| won \| eval_score \| steps \| wall_s` | 跨 run 汇总表；直接算 baseline vs MAS 的成功率 |
| `{run_id}.log` *(可选)* | 你用 `tee` 时才有 | runner 的 stdout | 查 `[runner] action rejected` 等运行期错误 |

> `eval_score = floor * 10 + (200 if won else 0)`（见 `agents/logger.py`）

### 可选：把 stdout 也存下来

```bash
python -u runner.py --system mas --run-id mas_01 --verbose 2>&1 | tee runs/mas_01.log
```
这样终端里看到的所有 `action rejected` / `forcing fallback` 都会落盘，配合 jsonl 一起看更容易定位问题。

### 成功率 / 性能的常用查询

```bash
# 成功率（按 system 分组）
python3 -c "
import json, glob
from collections import defaultdict
g = defaultdict(lambda: [0,0])
for p in glob.glob('agents/runs/*_summary.json'):
    d = json.load(open(p))
    g[d['system']][0] += 1
    g[d['system']][1] += int(bool(d.get('won')))
for k,(n,w) in g.items():
    print(f'{k}: {w}/{n} = {w/n:.1%}')
"

# 平均到达层数 / 平均步数 / 平均耗时
python3 -c "
import json, glob, statistics as s
from collections import defaultdict
agg = defaultdict(lambda: defaultdict(list))
for p in glob.glob('agents/runs/*_summary.json'):
    d = json.load(open(p))
    agg[d['system']]['floor'].append((d.get('final') or {}).get('floor') or 0)
    agg[d['system']]['steps'].append(d['total_steps'])
    agg[d['system']]['wall'].append(d['wall_seconds'])
for sys_, m in agg.items():
    print(sys_, {k: round(s.mean(v),1) for k,v in m.items()})
"

# 每 agent 的被采纳率（用 jsonl）
cat agents/runs/*_steps.jsonl | python3 -c "
import json, sys
from collections import Counter
c = Counter()
for line in sys.stdin:
    d = json.loads(line)
    win = next((n for n,p in d['proposals'].items() if p['action'] == d['chosen']), '?')
    c[win] += 1
print(c.most_common())
"
```

### 跑批量实验后汇总

```bash
python -m experiments.run_batch --system mas      --seeds 1,2,3,4,5 --model 4o-mini
python -m experiments.run_batch --system baseline --seeds 1,2,3,4,5 --model 4o-mini
cat agents/runs/run_scores.md    # 两组并列对比
```

### 已知数据盲区

- jsonl 里 `chosen` 只记录"agent 选了什么"，**不记录 Mod 是否真的执行成功**。若需区分"LLM 想对但被驳回" vs "成功落地"，目前要去看对应的 `.log`；要写进 jsonl 需要改 `runner.py + logger.py`。
- 未记录 LLM token 用量 / 单步 LLM 耗时 / 每个 agent 的 latency。如需计入成本维度的分析可以后续扩展。
- 敌方回合 skip 和 `_AUTO_ADVANCE` 跳过的 tick 不进 jsonl（这些步骤没有 agent 决策）。

---

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--system` | `baseline` 或 `mas` | 必填 |
| `--run-id` | 本次运行的唯一标识 | 必填 |
| `--model` | LLM 模型名称 | `4o-mini` |
| `--max-steps` | 最大步数上限 | `2000` |
| `--verbose` / `-v` | 实时打印决策过程 | 关闭 |

### 实时输出格式

带 `--verbose` 启动后，每步输出如下：

```
────────────────────────────────────────────────────────────
Step    5  monster             Floor 2  HP 64/80  Gold 99
system: mas
  ✓ combat       [conf=0.9]  play_card(card_index=2  target=ENEMY_0)
    Playing Strike for maximum damage while enemy is vulnerable
  · strategic    [conf=0.6]  play_card(card_index=0)
    Defend first to preserve HP
  → chosen: play_card  (disagree, picked from combat)
```

- `✓` = 被采纳的提案，`·` = 被否决的提案
- `agree` / `disagree` = 各 Agent 是否意见一致

### 单局详细分析

```bash
# 查看某次运行的每一步决策
cat runs/mas_01_steps.jsonl | python3 -m json.tool | head -60

# 统计各 Agent 的决策次数
cat runs/mas_01_steps.jsonl | python3 -c "
import json, sys
from collections import Counter
chosen = Counter()
for line in sys.stdin:
    d = json.loads(line)
    winner = next((n for n,p in d['proposals'].items() if p['action'] == d['chosen']), '?')
    chosen[winner] += 1
for k,v in chosen.most_common():
    print(f'{k}: {v} steps')
"
```

---

## 2. 首次安装与配置

### 安装 Mod

Mod 文件放在以下路径（macOS）：

```
~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/
SlayTheSpire2.app/Contents/MacOS/mods/
├── STS2_MCP.dll
└── STS2_MCP.json
```

**重新编译**（修改了 C# 源码后）：

```bash
dotnet build STS2_MCP.csproj -c Release \
  -o out/STS2_MCP \
  -p:STS2GameDir="$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources"

cp out/STS2_MCP/STS2_MCP.dll \
   "$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/mods/STS2_MCP.dll"

cp mod_manifest.json \
   "$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/mods/STS2_MCP.json"
```

### 配置 Python 环境（只需执行一次）

```bash
cd /Users/jibingshi/Downloads/MASproject/STS2MCP/agents

python3 -m venv .venv
source .venv/bin/activate
pip install python-dotenv requests httpx
pip install ../LLMProxy-main/py
```

确认 `.env` 存在并包含以下内容：

```
LLMPROXY_ENDPOINT=https://...
LLMPROXY_API_KEY=externalUserBasic-...
```

### 启用 Mod

进入游戏后：**Settings → Mods** → 确认 STS2_MCP 已启用。

验证连接：

```bash
curl "http://localhost:15526/api/v1/singleplayer?format=json" | python3 -m json.tool
```
