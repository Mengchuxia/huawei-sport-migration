# 端到端示例：一条合成跑步记录从仓库到华为

本文用仓库自带的**合成数据**走完整条链路，不需要先准备自己的导出文件。所有命令在仓库根目录执行。

- 示例数据：`assets/sample_workouts.json`（1 条跑步，600 s，1921.9 m，含逐点心率/步频/速度/累计距离/GPS）
- 本地链路（环境检查 → 转换 → 编码 → 自检）实跑核验：2026-11-18 01:04
- 导入页与服务端字段结构只读核验：2026-11-18 01:02，见 `references/current-status.md`

导入页和它使用的接口不是公开承诺稳定的 API。**执行前先看 `references/current-status.md`，并运行 `scripts/check_api_compat.py`**；本文中的输出样例只描述一次观察，不构成兼容性保证。详见 `DISCLAIMER.md`。

---

## 第 0 步 确认环境与当前状态（只读，不写入账号）

```bash
python scripts/check_api_compat.py
python scripts/check_environment.py
```

第一个脚本会询问是否做接口兼容性探测，并列出三种方式的影响；选「1 只读检查」时不写入账号。第二个脚本输出：

```
总体状态：ready
  ✓ python           3.13.14（需要 3.10+）
  ✓ garmin-fit-sdk   21.221.0
  ✓ playwright       1.65.2
  ✓ browser          ...（系统浏览器）
```

- `ready`：继续
- `partial`：转换、编码、自检可用；自动上传与核验不可用，需按 `references/verification.md` 的降级路径人工核对
- `needs_setup`：按 `references/setup-guide.md` 补齐依赖后重跑，不要跳过

版本号只是本机当时的取值，不是最低要求；最低要求以 `check_environment.py` 与 `references/setup-guide.md` 为准。

## 第 1 步 准备中间格式

最短路径：直接把仓库自带的合成数据当作 `workouts.json` 使用（本文后续步骤都用它）。

```bash
# Windows
copy assets\sample_workouts.json workouts.json
# macOS / Linux
cp assets/sample_workouts.json workouts.json
```

如果要从「原始导出文件」开始，用同一套脚本转换：

```bash
# 小米桥导出 JSON（仓库自带合成样例）
python scripts/from_bridge.py --input assets/sample_mi_fitness.json --output workouts.json
# GPX / TCX / FIT 导出目录
python scripts/convert.py --input <导出目录或文件> --output workouts.json
```

`from_bridge.py` 对合成样例的实跑输出：

```
· 读取 2 场，输出 2 条，跳过 0 条
· 类型：running 1、有逐点 2、strength 1
· 逐点距离来源：cumulative 1、none 1
```

注意：这条路径会生成 **2 条**记录（含 1 条力量训练），后续命令与本文的「1 个文件」预期不同。想严格照本文预期走，请保留第 1 步最短路径的版本。

转成自己的数据后先扫一眼：距离是否为 0、采样点数量是否合理、开始时间是否正确。距离为 0 且无轨迹的记录，导入后大概率不显示。

## 第 2 步 编码 FIT

```bash
python scripts/fit_encode.py --input workouts.json --out-dir out
```

实跑输出：

```
  ✓ 20240501_0730_running_sample-run.fit  18.7 KB

· 生成 1 个文件 → out
```

默认 `--lap-mode auto`：跑步按公里分段（本例 2 段），其它运动类型不写分段。非跑步类型带分段会被平台拒收，见 `references/huawei-limits.md`。

## 第 3 步 自检

```bash
python scripts/fit_audit.py --fit-dir out --workouts workouts.json --report audit.json
```

实跑输出：

```
  ✓ 20240501_0730_running_sample-run.fit  601 点 / 2 段

· 1 个文件，0 个有问题 → audit.json
```

自检覆盖必需消息、时间轴闭合、分段求和、非跑步是否误写分段、坐标范围、时区偏移、与源数据的时长/距离偏差、单文件 5 MB 上限。**`problems` 非空就停止**，按 `references/troubleshooting.md` 修源文件后重新编码。

## 第 4 步 试运行（只读服务端，不上传）

```bash
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --dry-run
```

输出形态如下（本示例未实跑该步骤，形态依据 `huawei_upload.py` 的实现）：

```
· 服务端已有 N 条记录（查询起点 ...）
· 待导入 1 个（已存在或已完成 0 个）
    20240501_0730_running_sample-run.fit
· 预演结束，没有上传任何文件
```

- `--workouts` 必填：脚本靠它判断哪些记录已入库，缺失时会拒绝运行
- 首次运行会打开浏览器并停在登录页，需手动完成一次登录；登录态随后保存在本地浏览器配置中
- 若服务端已有同开始时间 + 同时长的记录，该文件会被列为「已存在」，不会重复提交
- 想只准备登录态：`python scripts/huawei_upload.py --login-only`

## 第 5 步 上传（**这一步会写入账号**）

> ⚠️ 执行后这条合成记录会成为账号内的一条真实运动记录。仓库不提供删除能力（删除接口不可用），需使用者在华为运动健康 App 内自行删除。若只想验证到「能不能生成合规文件」，在第 4 步停止即可。

```bash
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --batch 50
```

输出形态如下（本示例未实跑上传，形态依据 `huawei_upload.py` 的实现）：

```
[1] 上传 1 个文件…
    → ...
      ✓ 20240501_0730_running_sample-run.fit 已入库
· 本次入库 1 个，失败 0 个
```

`--batch` 默认 10，上限 50；导入页的文件输入支持 `multiple`，页面文案写明一次最多 50 个文件。文件数量多时用 `--batch 50` 可以减少提交次数。批量结果弹窗只给汇总、不指出具体失败文件，处理方式见 `references/operational-notes.md`。

脚本每批结束都会重新读取服务端记录来判断是否真的入库；页面弹窗「成功」不作为判据。

## 第 6 步 核验

```bash
python scripts/huawei_verify.py --fit-dir out --workouts workouts.json
```

生成 `verify-report.md` 与 `verify-report.json`。本例的通过形态：

| 项目 | 期望 |
|---|---|
| 本地待导入 | 1 |
| 已入库 | 1 |
| 缺失 | 0 |
| 重复 | 0 |
| 时长不一致 | 0 |
| 无法确认 | 0 |

「无法确认」指同一分钟已有多条记录且时长都对不上，此时不要判成功，也不要直接重传；去 App 里人工看一眼。核验口径与降级方式见 `references/verification.md`。

## 第 7 步 结果解读与已知边界

按当前只读核验（`references/current-status.md`）：

- 页面原文写明：导入数据**不计入运营统计、个人成就统计、周月年报统计与运动能力评估**。导入记录属于降级数据。
- `activitySummary` 的顶层结构为 `paceSummary` / `performanceSummary` / `dataSummary`，部分记录另有 `sectionSummary`；分段结构只在跑步类型上观察到。
- 服务端按采样点计算部分派生统计；写入的汇总字段不一定被采用。
- **骑行**：服务端保留速度的平均值与最大值，但导入记录没有逐点速度采集通道，App 里通常只有平均值，没有速度曲线。
- **步行**：即使 FIT 里写了逐点步频与汇总步频，服务端回读也不保留步频/步幅统计。
- 部分运动类型在 FIT 解析层被拒收，需由使用者在 App 内手动补录，清单见 `references/huawei-limits.md`。

这些是展示层与落库口径的边界，**不是「往 FIT 里再加字段」能解决的**。

## 第 8 步 换成自己的数据

把第 1 步的 `workouts.json` 换成 `from_bridge.py` / `convert.py` 的输出，第 2—6 步不变。开始前确认：

- 单批 ≤ 50 个文件、单文件 ≤ 5 MB（以导入页当时文案为准）
- 页面会显示可导入的最早日期；早于该日期的记录会被拒（`activity.time.exceed`）。合成样例的日期较早，如遇到该提示，把 `start_time` 调整到页面允许的范围后重新编码
- 先跑 `--dry-run`，确认待传清单没有已入库的文件
- 不支持的类型单独列清单，不并入成功数

## 附：常见分支

| 现象 | 处理 |
|---|---|
| 环境检查 `partial` | 本地链路照跑；导入改为手动，核验按 `verification.md` 降级 |
| 自检有 `problems` | 停止上传，修源数据后重新编码 |
| 试运行显示「待导入 0 个」 | 服务端已有对应记录，不必再传 |
| 上传后核验报「缺失」 | 先看 `troubleshooting.md`，不要直接重跑原文件 |
| 出现验证码 / 安全验证 / 操作过于频繁 | 立即停止自动化，手动完成本次导入 |

本示例只使用合成数据；任何真实导出文件、登录态、核验报告都保存在本地，不应提交到公开仓库。见 `references/security-privacy.md` 与 `DISCLAIMER.md`。
