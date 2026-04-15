# 项目完成计划 (CS150-01 Final Project)

> 基于 `mid-report.docx` 的架构设计，结合当前仓库状态（STS2_MCP mod + MCP server + LLMProxy 客户端）整理的落地计划。

---

## 0. 当前已有资产

- **STS2_MCP mod (C#)**：已编译，暴露 `localhost:15526` REST API，提供完整游戏状态和动作接口。
- **mcp/server.py**：将 REST API 包装成 MCP tools（`get_game_state`, `combat_play_card`, `map_choose_node` 等）。
- **LLMProxy-main/py**：课程提供的 LLM 调用代理（`client.generate(model, system, query, ...)`）。需通过 `.env` 配置 `LLMPROXY_API_KEY` 和 `LLMPROXY_ENDPOINT`。
- **mid-report**：已确定 3 个专业 agent + 1 个 Coordinator 的 MAS 架构。

## 1. 架构落地（与 mid-report 对齐）

```
            +---------------------+
            |    Coordinator      |   <-- get_game_state(json)
            +----------+----------+
                       |  (filter local state)
       +---------------+---------------+
       |               |               |
  +----v-----+   +-----v-----+   +----v------+
  | Combat   |   | Strategic |   | Economy   |
  | Agent    |   | Agent     |   | Agent     |
  +----+-----+   +-----+-----+   +-----+-----+
       |               |               |
       +---------------+---------------+
                       | (action, confidence, justification)
            +----------v----------+
            |   Arbitration       |  --> MCP tool call --> REST API --> Game
            +---------------------+
```

**关键变更**：原报告写用 Anthropic Claude API via MCP。实际实现时，**LLM 调用全部走 LLMProxy**（课程要求），MCP 只作为“游戏动作执行层”。即：
- LLMProxy → 负责 agent 的思考 / 决策（文本输入输出）。
- MCP server / REST API → 负责读取游戏状态、执行最终动作。

## 2. 代码组织（新建目录 `agents/`）

建议在仓库根目录新建：

```
agents/
├── .env                     # LLMPROXY_API_KEY / LLMPROXY_ENDPOINT
├── requirements.txt         # llmproxy, httpx, python-dotenv, matplotlib, pandas
├── runner.py                # 入口：跑一局完整 run，循环 get_state → decide → act
├── game_client.py           # 封装 REST API 调用 (替代 MCP，直接 HTTP 更易脚本化)
├── coordinator.py           # Coordinator：路由 + 仲裁
├── agents/
│   ├── base.py              # Agent 基类 (统一 prompt 模板 + 解析 JSON 返回)
│   ├── combat.py            # Combat Agent
│   ├── strategic.py         # Strategic Agent (deck building, map routing)
│   ├── economy.py           # Economy Agent (shop, gold)
│   └── baseline.py          # 单 agent baseline (对照组)
├── prompts/                 # system prompt 文本文件，便于版本化和调参
│   ├── combat.md
│   ├── strategic.md
│   ├── economy.md
│   ├── coordinator.md
│   └── baseline.md
├── state_filter.py          # 把 full state 裁剪成各 agent 的 local view
├── logger.py                # 每步决策落盘 JSONL（供后续分析）
└── experiments/
    ├── run_batch.py         # 批量跑 N 次 seed (多组实验)
    └── analyze.py           # 读 log → 生成图表 / 指标表
```

## 3. 阶段任务

### Stage A — 基础设施（1-2 天）

1. **LLMProxy 冒烟测试**：在 `agents/` 下 `pip install ../LLMProxy-main/py`；写 `test_proxy.py` 调一次 `generate` 确认 API key 工作。
2. **REST 客户端封装**：用 `httpx` 直接封装 `http://localhost:15526/api/v1/singleplayer` 的 GET / POST，不必通过 MCP 进程（脚本化更方便）。参考 `mcp/server.py` 里每个 tool 对应的 body。
3. **Runner 主循环**：`while not run_over: state = get_state(); action = coordinator.decide(state); execute(action);` 先跑个 dummy agent（永远点第一个选项）把端到端链路跑通。

### Stage B — 单 Agent Baseline（1 天）

4. 写 `baseline.py`：一个 agent 看完整 state，决定所有动作。这是对照组，**必须先完成**，否则无法对比。
5. 设计 baseline system prompt：包含游戏规则摘要 + 输出格式规范（`{action_type, params, reasoning}`）。
6. 跑 3-5 局验证稳定性（不崩溃、不无限循环、能通关至少若干层）。

### Stage C — 多 Agent 系统（3-4 天）

7. **State filter**：按 screen type 把 full JSON 裁成 local view：
   - Combat Agent: `hand, energy, enemies, player_hp, draw_pile_count, relics`
   - Strategic Agent: `deck, map, current_floor, relics, act_boss`
   - Economy Agent: `gold, shop_contents, potion_slots, relics`
8. 实现三个专业 agent，统一返回格式：
   ```json
   {"action": {...}, "confidence": 0.0-1.0, "justification": "..."}
   ```
9. **Coordinator 仲裁**：
   - 单 agent 场景（战斗 → 只问 Combat Agent）直接执行。
   - 多 agent 场景（card reward → Strategic + Combat 都有意见）按 confidence 加权，冲突时取 max confidence，并记录 agreement / conflict。
10. 并行调用：用 `asyncio.gather` 或 `concurrent.futures` 让多 agent 同时访问 LLMProxy，减少 wall-clock 时间。
11. **Session id 策略**：每个 agent 用独立 `session_id`（利用 LLMProxy 的 `lastk` 做短期记忆，比如 `lastk=3`，让 agent 记得最近几回合的战术上下文）。

### Stage D — 日志与指标（1 天）

12. `logger.py` 每步写一行 JSONL：
    ```json
    {"step": 42, "state_type": "card_reward", "agent_proposals": [...], "chosen_action": {...}, "floor": 7, "hp": 45, "gold": 120, "ts": "..."}
    ```
13. Run 结束时写一条 summary：`{seed, final_floor, won, final_score, total_steps, total_tokens}`.
14. `analyze.py` 从日志聚合：
    - 平均 floor / 胜率 / 平均分（均值 ± 标准差）
    - Agreement rate / conflict rate（只对多-agent run 有意义）
    - 每类动作的分布直方图

### Stage E — 实验（2-3 天，最花时间）

15. **固定实验设定**：同一 character（建议 Ironclad-类角色，上手简单）、同一难度、**同一组 seeds**（如 seed 1-20），baseline 与 MAS 各跑一遍以消除方差。
16. 目标：mid-report 承诺 20-50 runs。先做 **20 runs × 2 (baseline vs MAS)**，看 token 成本和时间预算。如果每次 run 成本允许再加到 30+。
17. 并行度：STS2 同一时刻只能跑一局，**runs 之间无法并行**（除非开多游戏实例）。估算时间：一局 15-30 分钟 × 40 = 10-20 小时，务必尽早开跑。
18. 记录总 token 消耗，放进报告的 cost 分析。

### Stage F — 分析与报告（2 天）

19. 用 `matplotlib` 生成 mid-report Planned Outputs 中要求的图：
    - Floor reached 对比（折线 / 小提琴图）
    - 胜率 bar chart
    - Agreement / conflict 随 floor 变化曲线
    - 动作分布饼图 / 热力图
20. 写 final report：补充实验结果、讨论 MAS 是否真的跑赢 baseline、失败案例分析、token cost 对比。

## 4. 里程碑与时间表（建议，共约 10-12 天）

| 日期（从今天 2026-04-15 起） | 里程碑 |
|---|---|
| Day 1-2 | Stage A 完成，端到端链路跑通 dummy agent |
| Day 3   | Stage B baseline 能跑完整局 |
| Day 4-6 | Stage C MAS 上线，跑通 2-3 局 demo |
| Day 7   | Stage D logger / analyzer 就绪 |
| Day 8-10 | Stage E 批量实验（同时可以写 report 初稿） |
| Day 11-12 | Stage F 图表 + final report 定稿 |

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLMProxy 速率限制 / 超时 | 实验被卡 | 批量跑时在 agent 调用间加 backoff；保留 `session.Retry` |
| Token 预算超支 | 跑不完 40 局 | 先在 baseline 上测 1 局 token 消耗 × 40 估算，必要时砍到 20 局 |
| 游戏 UI 卡住 / MCP disconnect | Run 失败 | Runner 加 try/except + 状态保存，允许断点续跑 |
| Agent 输出不是合法 JSON | 崩溃 | 用 regex 兜底 + 重试 1 次 + fallback 到随机合法动作 |
| MAS 没跑赢 baseline | 结论反转 | 这本身是合法的研究结论，在 report 里诚实讨论原因（specialization overhead, LLM 本身已够强等） |

## 6. 一些关键的设计决定（避免踩坑）

- **不走 MCP 进程内通信**：agent 主循环直接 HTTP 打 `localhost:15526`。MCP server 留给 Claude Desktop 用户，脚本化跑实验用裸 REST 更稳。
- **LLMProxy 的 `session_id` 不是“agent 身份”而是“会话上下文”**：不同 run / 不同 agent 要用不同 id，避免串味。建议格式 `f"{run_id}-{agent_name}"`。
- **Prompt 里必须给 JSON schema 示例**，并在解析失败时重试 + 记日志。
- **Seed 固定很重要**：baseline 和 MAS 必须跑同一批 seed 才有可比性。在 STS2 里通过启动命令 / mod 接口设定 seed；如果 mod 不暴露，至少记录下来。

## 7. 立刻可以做的第一件事

```bash
# 1. 安装 LLMProxy
cd LLMProxy-main/py && pip install -e .

# 2. 在 agents/.env 放 key
cp LLMProxy-main/py/examples/.env agents/.env   # 如果还没有，手动创建

# 3. 跑通冒烟测试
python -c "from llmproxy import LLMProxy; print(LLMProxy().generate(model='4o-mini', system='hi', query='say hello'))"

# 4. 启动游戏 + mod，确认 curl 能拿状态
curl http://localhost:15526/api/v1/singleplayer
```

以上跑通之后，就按 Stage A → F 推进即可。
