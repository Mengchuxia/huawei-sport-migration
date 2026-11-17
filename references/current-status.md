# 当前状态快照（只读核验）

**核验时间**：2026-11-18 01:02（北京时间）
**方式**：登录华为运动健康网页导入页后，只读读取页面文案与 `activityRecords` 返回结构；**未导入任何文件、未写入账号记录**。
**对照**：与同日 00:25 的本地服务端快照逐字段比对。

本文件是**一次单账号、单时间点的观察**，用于给 `README.md`、`SKILL.md` 与各 `references/` 文档里的「最近核验」提供时间基准。它不构成官方承诺，也不保证后续版本行为一致。执行迁移前请按 `references/api-compat-probe.md` 自行复核；导入页当时显示的文案优先于本文件。

## 1 导入页当前文案（原文摘录）

| 项目 | 页面显示 |
|---|---|
| 数据约束 | 「仅支持导入 (包括) 之后的运动记录数据」——括号处为页面动态日期，本次渲染为空；以页面当时显示为准 |
| 统计口径 | 「本次导入的运动记录数据不计入华为运动健康运营相关统计、个人成就统计、周月年报统计与运动能力评估等」 |
| FIT 支持类型 | 跑步、骑行、游泳、步行、铁三、力量训练 |
| TCX 支持类型 | 跑步、骑行 |
| 批量与体积 | 「当前最多支持 50 个文件、文件大小不超过 5 MB」 |
| 格式选择 | 页面上 FIT / TCX 为单选 |

文件输入元素：`<input type="file" name="file" multiple accept=".tcx,.fit">`。`multiple` 为真，一次提交可带多个文件；上限以页面文案为准。

## 2 服务端返回结构

`activityRecords` 中每条记录的 `activitySummary`：

| 结构 | 本次观察 |
|---|---|
| 顶层键 | `paceSummary`、`performanceSummary`、`dataSummary` 出现在全部返回记录；`sectionSummary` 只出现在部分记录（本次仅跑步类型） |
| `paceSummary` 键 | `avgPace`、`bestPace`、`paceMap`、`partTimeMap`、`sportHealthPaceMap`（后者由服务端派生，并非全部记录都有） |
| `performanceSummary` 键 | 主要为 `heartRateZoneStatistics`；个别记录另有 `aerobicLoadPeak` / `anaerobicLoadPeak` |
| `sectionSummary` | 分段数组；单段键为 `sectionNum`、`sectionTime`、`startTime`、`endTime`、`sectionDataList` |
| `dataSummary` | `SamplePoint` 数组，键为 `dataTypeName` 与 `value`；是统计点，不是时间序列 |

本次出现的 `dataTypeName` 全集（10 类）：

```
com.huawei.continuous.altitude.statistics
com.huawei.continuous.calories.burnt.total
com.huawei.continuous.distance.total
com.huawei.continuous.exercise_heart_rate.statistics
com.huawei.continuous.heart_rate.statistics
com.huawei.continuous.speed.statistics
com.huawei.continuous.steps.rate.statistics
com.huawei.continuous.steps.total
com.huawei.resting_calories.statistics
com.huawei.steps.stride.statistics
```

与 00:25 快照比对：**顶层键集合、`dataTypeName` 全集、按运动类型的字段覆盖均无差异**。字段含义与官方文档链接见 `references/field-reference.md`。

## 3 按运动类型的统计字段覆盖

「✓」表示本次返回的记录中出现该统计类型，「—」表示未出现。只描述字段覆盖，不代表任何账号的数据规模或健康数值。

| 统计类型 | 跑步 (56) | 步行 (90) | 骑行 (13) | 力量训练 (79) |
|---|---|---|---|---|
| 距离 `distance.total` | ✓ | ✓ | ✓ | — |
| 速度 `speed.statistics`（avg / max） | ✓ | ✓ | ✓ | — |
| 步数 `steps.total` | ✓ | ✓ | — | — |
| 步频 `steps.rate.statistics` | 部分 ✓ | — | — | — |
| 步幅 `steps.stride.statistics` | ✓ | — | — | — |
| 心率 / 运动心率 / 卡路里 | ✓ | ✓ | ✓ | ✓ |
| 分段 `sectionSummary` | ✓ | — | — | — |

要点：

- **步行**：即使 FIT 中同时存在逐点 `record.cadence` 与 `session.avg_cadence`，服务端回读也不保留步频/步幅统计。官方「健走」数据类型页列出了这些字段，说明差异发生在导入通道的落库口径，而非规范不支持。
- **骑行**：服务端保留速度统计的 avg 与 max，但导入记录没有逐点速度采集通道；App 侧通常只显示平均值，没有速度曲线。
- **分段**：本次只在跑步类型上观察到 `sectionSummary`；非跑步类型带分段会被拒收。

以上为展示与落库口径的边界，向 FIT 增加字段不改变结果。相关排查见 `references/troubleshooting.md`。

## 4 写入语义的最近一次核验

2026-11-18 00:35，用两份**同一开始时间、同一运动类型、内容不同的合成 FIT** 做 A/B 探测，回读结论：

| 观察项 | 结果 |
|---|---|
| 距离 / 时长 / 分段数 / 卡路里 | 第二份覆盖第一份 |
| 记录条数与 id | 保持 1 条，id 不变，未观察到新增记录 |
| 派生统计 | 哨兵未写 `total_cycles`，服务端按逐点步频自行生成步数 |

推论：**同一开始时间与运动类型的再次导入按整条覆盖处理**，因此不必先清空账号再重传。但该行为不是官方承诺，且派生统计由服务端按采样点自算——采样点不变的重传不会带来可见变化。仍应先核验、失败不自动重传。

哨兵导入后是账号内的真实记录，删除接口不可用，需使用者在 App 内自行删除。

## 5 如何自行复现本次只读检查

1. 运行 `python scripts/check_api_compat.py`，选择「1 只读检查」。
2. 打开导入页，记录第 1 节的文案项与文件输入属性。
3. 在已登录页面上下文读取 `activityRecords`，记录第 2 节的字段名集合（脚本与判据见 `references/api-compat-probe.md`、`references/verification.md`）。
4. 与本文件、`references/huawei-limits.md`、`references/field-reference.md` 比对，输出差异清单；不导入任何文件。

若需验证覆盖语义，再单独确认「2 合成哨兵探测」，并接受它会写入账号记录这一影响。

## 6 使用约定

- 仓库内所有「最近核验」表述以本文件的核验时间为基准；发现差异时以**实时探测结果**为准，并更新文档。
- 本文件不记录账号标识、令牌、轨迹、心率数值或任何真实健康记录。
- 页面文案、内部接口路径、字段结构与错误码可能变化；本项目不对其稳定性作保证。见 `DISCLAIMER.md`。
