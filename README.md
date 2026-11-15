# ThesisBreaker

> **从“让 AI 预测涨跌”到“面向个人港美股投资者的零 API 成本本地持仓复盘与估值证伪纪律官”。**

[![CI](https://github.com/SnowyLumiere/thesis-breaker/actions/workflows/ci.yml/badge.svg)](https://github.com/SnowyLumiere/thesis-breaker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-green.svg)](pyproject.toml)
[![Zero Paid API](https://img.shields.io/badge/Data%20API-%240%20Local%20CSV%20%2B%20Obsidian-orange.svg)](#)

---

## 为什么做 ThesisBreaker？

市面上 99% 的“AI 炒股项目”都在教唆用户接昂贵的 Bloomberg / Polygon 实时 API 做高频预测；而普通大模型在聊持仓时永远像一个和稀泥的老好人——满嘴“既有上涨空间也需注意宏观风险”的正确废话。

但港美股严肃个人投资者（使用 **IBKR 盈透 / 长桥 + Obsidian**）真正的痛点根本不是“缺一个看 MACD 金叉的 AI”，而是：

> **买入时写了一套极其严谨的 SOTP / FCFE 估值逻辑；但当持仓出现 15% 回撤或财报微瑕时，人类大脑会本能地自我欺骗（Thesis Creep / 逻辑漂移）——把原本的「基本面波段」硬拗成「长期价值投资」死扛，或者在不知不觉中偷偷下调了当初设定的死线容忍度。**

**ThesisBreaker** 借鉴 [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) 的 **“零付费数据 API 路径 + 仅输出风险敞口姿态（Exposure Posture）”** 与 [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) 的 **“极度冷酷电报体（零废话、零和稀泥）”**，注入 **SOTP / FCFE 确定性重算脚本 + SHA-256 死线锁 + 逻辑漂移抓包器**：

1. **零付费 API（$0/月）**：只读你本地导出的 IBKR Flex Query / 长桥交割单 CSV + 本地 Obsidian Markdown 估值卡 + 本地财报摘要表。
2. **强制 3 条可证伪死线（Falsifiable Kill-Switches）**：无 3 条明确量化死线的持仓直接判为 `UNTRACKED_NAKED_POSITION`（裸奔仓位）。
3. **SHA-256 死线锁 & 容忍度松动抓包**：一旦建仓锁死 `locked_threshold`，哪怕你事后偷偷把“阿里云增速 >=10%”改成 `>=4%` 自我安慰，系统依然按锁定原阈值判破产并抓出 **Tolerance Creep**。
4. **SOTP / FCFE 确定性估值重算**：用本地 Python 确定性代码重算分部估值与自由现金流折现安全边际（MOS），拒绝大模型口头估算。
5. **Caveman 极简冷酷三行裁决**：禁止废话与安慰，只输出事实、估值偏离、自我欺骗对比与 `ExposurePosture`（绝不直接下单）。

---

## 极简效果预览（3 行冷酷电报体）

运行内置美港股真实风格 Demo（`MU`、`9988.HK`、`0700.HK`、`SMCI`）：

```bash
PYTHONPATH=src python3 -m thesis_breaker demo
```

输出示例：

```text
[持仓：MU (Micron Technology Inc | 浮盈亏 -16.4%)] 当初假设「Q4 HBM3E 良率」已破产（实测 62% vs 死线 >=75%，偏离 -17.3%）（共 3/3 条死线击穿）；重算 SOTP 内在价值 USD 78.60（初值 159.64），当前安全边际 -25.4%（死线要求 >=25.0%，安全边际已彻底消失/高估）。
检测到你正试图用「虽然 Q4 HBM 良率不及预期且 DRAM 价格转跌，但 AI 存储超级周期才刚开始，打算把原本的波段仓位转为长期价值投资死扛，忽略短期波动并等待下个周期」掩盖「Q4 HBM3E 良率（实测 62% vs 死线 >=75%）」的失败（风格漂移: 基本面波段/周期交易 -> 长期价值死扛 | 自我合理化: 长期价值, 价值投资, 超级周期）。
建议动作：无条件执行死线砍仓/清仓（至少立即削减 50%-100% 敞口），禁止摊平 | 风险敞口姿态：[KILL_SWITCH_TRIGGERED]（仅供人类决策审查，严禁自动下单）。

[持仓：9988.HK (Alibaba Group Holding Ltd | 浮盈亏 -14.2%)] 当初假设「阿里云外部收入 YoY」已破产（实测 4.2% vs 死线 >=10%，偏离 -58.0%）；重算 SOTP 内在价值 HKD 116.43（初值 136.97），当前安全边际 +24.9%（死线要求 >=25.0%，安全边际不足）。
检测到你正试图用「短期云业务为 AI 算力做战略性投入导致增速放缓至 4.2%，忽略短期增速压力并下调观察门槛，坚持长期价值持有」掩盖「阿里云外部收入 YoY（实测 4.2% vs 死线 >=10%）」的失败（容忍度松动 | 自我合理化: 长期价值, 战略性投入, 忽略短期 | 死线锁哈希不匹配）。
建议动作：无条件执行死线砍仓/清仓（至少立即削减 50%-100% 敞口），禁止摊平 | 风险敞口姿态：[KILL_SWITCH_TRIGGERED]（仅供人类决策审查，严禁自动下单）。
```

---

## 快速开始（Zero Dependencies，Python 3.9+ 开箱即用）

无需安装任何第三方 API SDK，甚至无需联网：

```bash
git clone https://github.com/SnowyLumiere/thesis-breaker.git
cd thesis-breaker

# 1. 运行内置美港股组合 Demo（Caveman 模式）
PYTHONPATH=src python3 -m thesis_breaker demo

# 2. 运行你自己的 IBKR / 长桥 CSV + Obsidian 投研库复盘
PYTHONPATH=src python3 -m thesis_breaker audit \
  --ibkr examples/ibkr_flex_positions.csv \
  --notes examples/obsidian_vault \
  --earnings examples/earnings_q4_flash.md \
  --format markdown

# 3. 建仓时生成并锁定 SHA-256 估值死线卡（防事后偷偷改阈值）
PYTHONPATH=src python3 -m thesis_breaker init-note --symbol NVDA --name "NVIDIA" --model FCFE --output my_vault/NVDA.md
PYTHONPATH=src python3 -m thesis_breaker lock --notes my_vault/

# 4. 财报季快速抽取 3 个核心死线数字（周维护耗时 < 15 分钟）
PYTHONPATH=src python3 -m thesis_breaker extract \
  --earnings examples/earnings_q4_flash.md \
  --notes examples/obsidian_vault \
  --write
```

如需本地可编辑安装（可选）：

```bash
pip install -e .
thesis-breaker demo
```

---

## 目录结构

```text
thesis-breaker/
├── skills/thesis-breaker/
│   ├── SKILL.md                          # AI Agent Skill 规范（挂载 Caveman + Zero-API 规则）
│   └── references/
│       ├── caveman_rules.md              # 极简电报体戒律
│       └── thesis_card_schema.md         # Obsidian 估值卡 YAML Schema
├── workflows/
│   ├── weekly_postmortem.yaml            # 每周例行持仓逻辑复盘工作流
│   └── earnings_flash_audit.yaml         # 财报季 15 分钟极速抽表+证伪工作流
├── src/thesis_breaker/
│   ├── models.py                         # 核心数据模型与 5 级 ExposurePosture
│   ├── parsers/
│   │   ├── broker_csv.py                 # IBKR Flex / Activity Statement & 长桥 CSV 解析器
│   │   ├── obsidian_thesis.py            # Obsidian YAML+Markdown 逻辑卡解析器
│   │   ├── earnings_extractor.py         # 本地财报 Markdown/CSV 3 指标自动抽取器
│   │   └── simple_yaml.py                # 零依赖纯 Python YAML 子集解析器（兼容 PyYAML）
│   ├── engine/
│   │   ├── valuation.py                  # SOTP 分部估值 & FCFE 两阶段折现确定性计算器
│   │   ├── thesis_lock.py                # SHA-256 死线防篡改锁 & Tolerance Creep 检测
│   │   └── auditor.py                    # 死线击穿、风格漂移、自我欺骗句子抓包与风险定级
│   ├── formatters/caveman.py             # 三行冷酷电报体 / Markdown / JSON 渲染器
│   └── cli.py                            # CLI 入口（audit / demo / lock / extract / init-note）
├── examples/                             # MU、9988.HK、0700.HK、SMCI 实战样例
├── docs/launch_post_zh.md                # 首发实战长文模板
└── tests/                                # 完整单元测试与端到端测试
```

---

## 挂载为 AI Skill（Claude Code / Antigravity / OpenClaw）

将 `skills/thesis-breaker/` 目录复制到你的 Agent Skills 目录，并在对话中调用：

> "用 `thesis-breaker` 复盘我的 IBKR CSV 与 Obsidian 持仓笔记，开 Caveman 冷酷模式，不许说安慰话。"

---

## 测试验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

---

## 免责声明

本项目仅用于个人投研笔记与持仓纪律复盘。所有输出严格限定为 **供人类审查的风险敞口姿态（Exposure Posture）**，**绝不包含任何自动化下单指令，亦不构成投资建议**。
