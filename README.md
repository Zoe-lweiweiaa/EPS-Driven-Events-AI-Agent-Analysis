# EPS 事件驱动量价 Multi-Agent 试点

本项目借鉴中金研报的“量价数值 Agent → 图表 Agent → 决策 Agent”三角色结构，用本地 `gangtise.ashare_prffrcaststat` 的分析师 EPS 预测修订统计替代“分析师观点”。研究区间为 2025-01-01 至 2026-09-15，日频，基准为中证全指 `000985.CSI`。目前已完成全区间 **EPS 事件基线** 远端回测；三 Agent 已完成策略优化前 30 条匿名事件的工程与决策流程试点，尚不能称为全量 Multi-Agent 回测。

## 冻结的 MVP 信号

- MySQL 取 `cycle_typ='日'`、`cycle_period=60`，仅使用 FY0（`est_report_y=year(end_date)`）与 FY1。所用 `eps_add`/`eps_reduce` 是每股收益预测的调高/调低次数，**不是 EPS 数值变动幅度**；`eps_orgnum` 是预测机构数。`eps_num` 未作为分母，因为抽检发现它不总等于调高、调低、维持等次数之和。
- 单预测年度 `revision_score=(eps_add-eps_reduce)/max(eps_add+eps_reduce,3)`；合成 `forecast_score=0.6×FY0+0.4×FY1`。只有一个预测年度时将权重归一到该年度。
- `forecast_score≥0.5`、FY0/FY1 至少一年的 `eps_orgnum≥3`、相对前次快照的 FY0+FY1 `eps_add` 总增量≥1，且是首次越过 0.5。每股 10 个交易日冷却。`end_date` 当日及非交易日快照最早映射至下一交易日开盘集合竞价。
- 股票池为沪深 A 股；排除 ST、停牌、上市不足 120 天、涨停无法买入。最多 20 只、每只目标权重 5%、持有 20 个交易日、剩余资金留现金。信号强度降序排序，同分按证券代码排序。

本地 `sql/export_eps60.sql` 只读导出；`src/build_events.py` 使用 SuperMind 交易日历生成派生事件 CSV，并在信号生成时严格保留沪深 A 股代码。原始分析师逐行数据与 MySQL 凭据不上传远端。`eps_event_baseline.py` 是 SuperMind 策略代码。

## 数据与回测核验

- 沪深 A 股 60 日 EPS 快照 3,114,982 行，覆盖 2024-12-01 至 2026-09-15；2024-12 用于事件判定预热。
- 股票-日期记录 1,599,711 个；首次越阈值候选 1,080 条，冷却后 1,016 条，涉及 535 只股票、308 个交易日。全部满足交易日严格晚于信号 `end_date`、事件唯一与冷却条件。
- 完整事件基线回测：初始资金 1,000 万元，区间收益 26.56%，中证全指 20.48%，年化收益 15.28%，最大回撤 20.41%。366 笔买入均能对应事件，352 笔卖出均在买入后第 20 个交易日；最多持仓 20 只，期末 14 只未平仓，无北交所成交。详见 `eps_event_baseline_回测结果_20260927_224653/回测报告.md`。先前含北交所的 25.13% 结果只作为修正审计记录，不作为正式基线。

这些收益不是预测能力的证明：这是样本内、未做显著性检验的探索性回测，组合暴露与基准不完全相同。历史 MySQL 行的 `update_time` 对旧日期存在 2026 年批量导入痕迹，故只能以 `end_date` 作为“假设当时可得”的快照日期，**无法证明历史真实可得性**。此回填风险可能显著高估效果，实盘前必须取得可靠的原始发布时间或历史归档验证。

## 三 Agent 验证路径

1. 对每条事件，以 `end_date` 为截止取前 60 个交易日的量价数据。数值 Agent 仅见匿名表格/特征；图表 Agent 仅见匿名 K 线、成交量和 MACD 图；二者相互独立，不见 EPS、股票名称、证券代码或实际日期。
2. 决策 Agent 仅见 EPS 事件摘要和前两 Agent 的冻结输出，分别给 5 日、20 日方向分数（[-1,1]），预先锁定 `score_20d≥0.4` 且 `score_5d>-0.2` 才入选。缺失评分一律拒绝，不能用零分或确定性因子伪装为 Agent 判断。
3. `export_agent_poc.py`、`export_agent_extension.py` 及 `src/` 中的 prepare/assemble/finalize 脚本，已冻结 30 条按时间网格补充的、互不重复的沪深 A 股匿名事件，含量价数字、K 线/成交量/MACD 图、分角色评分及输入哈希。三位 Codex 角色各自独立给出双期限评分；30 条中 11 条通过预先锁定的门槛。`artifacts/agent_30/` 保存了 46 个派生输入、图片、角色评分、信号及 SHA-256 清单，不含 MySQL 原始记录或凭据。先前 12 条试运行只验证链路，结果不用于正式比较。
4. SuperMind 配对诊断：对**同一 30 条事件**，`eps_baseline_30.py` 不加过滤，区间净收益 -4.78%；`eps_multiagent_poc.py` 仅交易 11 条通过事件，区间净收益 -0.81%，差 3.97 个百分点。11 条均如期买入并在第 20 个交易日卖出。按对照组的成交价计算，已完成的通过组 11 笔平均 20 日毛收益 -1.32%，未通过组 17 笔为 -4.57%；另 2 笔临近回测结束，未走完 20 日。样本量小、筛选后大部分资金闲置，以上差异**不是**显著性或全量增益证据。报告分别见 `eps_baseline_30_回测结果_20260927_225603/回测报告.md`、`eps_multiagent_poc_回测结果_20260927_225641/回测报告.md`。
5. 正式效果检验须冻结**全部**事件评分，再在同一事件全集、同一撮合和费用下比较 EPS-only 与三 Agent 过滤，并另设暴露匹配对照。

全量 1,016 条事件至少需要 3,048 份独立角色评分和 1,016 张图。用户选择先做的 30 条匿名试点已完成；未经全量完成与核验，不公布“全量 Multi-Agent 回测收益”。

## 仓库文件导航

本仓库按“EPS 事件生成 → AI Agent 独立评分与综合判断 → 量化回测”组织材料，方便审阅策略逻辑、AI 决策依据及对应结果。以下 Agent 档案是策略优化前的 30 条匿名事件试点，展示 AI 参与决策时读取的资料和生成的输出；它们不是优化后策略的全量 Agent 回测。

### 核心策略与数据处理代码

| 文件 / 目录 | 用途 |
| --- | --- |
| `eps_event_baseline.py`、`eps_event_recent.py` | EPS 修订事件基线与近期事件策略代码。 |
| `eps_full5_hold20_partial_20260915.py` | 最多持有 5 只、持有 20 个交易日的部分区间策略；使用截至 2026-09-15 的 EPS 快照。 |
| `eps_full5_hold20_nocooldown.py`、`eps_baseline_30.py`、`eps_multiagent_poc.py` | 无冷却版本以及 30 条事件基线 / Agent 过滤的配对诊断策略。 |
| `export_agent_poc.py`、`export_agent_extension.py`、`export_eps_recent.ps1` | 导出 Agent 试点与近期 EPS 事件所需数据。 |
| `build_eps_events_2026_nocooldown.py`、`analysis_eps_snapshot.py`、`analysis_live_epsdt.py` | EPS 快照、事件构建与相关指标分析脚本。 |
| `src/` | 事件生成、匿名化、Agent 输入准备、评分汇总和信号整理脚本；用于追踪从事件到 Agent 输出的处理过程。 |
| `sql/` | EPS 快照相关只读查询。SQL 文件不包含数据库凭据。 |
| `EPS指标统计分析_截至2026-09-15.md` | EPS 指标统计分析说明。 |

### AI Agent 参考材料与输出

`artifacts/agent_30/` 整个目录保留策略优化前 30 条匿名事件的处理档案：

- `numeric_inputs.json`、`numeric_extension_inputs.json`：数值 Agent 使用的匿名量价特征输入。
- `EV001.png` 至 `EV030.png`：图表 Agent 使用的匿名 K 线、成交量与技术指标图。
- `numeric_scores*.json`、`chart_scores*.json`：数值 Agent 与图表 Agent 的期限评分、置信度和依据。
- `decision_inputs*.json`：综合决策 Agent 获得的 EPS 事件摘要和前序 Agent 评分。
- `final_scores*.json`：综合决策 Agent 对 5 日、20 日方向的最终评分及文字理由。
- `unfiltered_signals.csv`、`scored_signals.csv`：未过滤事件和应用 Agent 门槛后的信号。
- `manifest*.json`、`*mapping.json`：输入输出文件校验值及匿名事件映射记录，用于追踪档案版本与事件对应关系。

打分流程和入选门槛见上文“三 Agent 验证路径”。30 条是工程与决策流程试点，样本较小，不能代表全量 Agent 筛选效果。

### 回测结果

| 目录 | 内容与口径 |
| --- | --- |
| `eps_event_baseline_回测结果_20260927_224653/` | 完整 EPS 事件基线回测报告、成交记录、净值曲线和运行日志；作为 EPS-only 参照。 |
| `eps_baseline_30_回测结果_20260927_225603/` | 30 条 Agent 试点事件的未过滤基线结果。 |
| `eps_multiagent_poc_回测结果_20260927_225641/` | 同一组 30 条事件经 Agent 门槛筛选后的配对诊断结果。 |
| `eps_full5_hold20_partial_20260915_回测结果_20261019_152141/` | 近期 EPS 快照覆盖受限条件下的部分区间回测报告、交易记录、净值曲线和日志。 |

**日期口径：** `eps_full5_hold20_partial_20260915` 回测实际开始于 2026-06-01、结束于 2026-10-16；可用 EPS 快照仅截至 2026-09-15。9 月 15 日之后的区间属于数据受限延续，不应表述为“回测于 2026-09-15 结束”。

### 未纳入仓库的数据

`.deps/`、`tmp/`、`__pycache__/`、DuckDB 数据库、原始 EPS 导出和大体量中间行情文件不纳入版本控制。原始分析师逐行数据和数据库凭据不上传。部分脚本依赖 SuperMind / MindGo 运行环境及其文件接口，仓库主要用于审阅研究流程和已保存结果。

