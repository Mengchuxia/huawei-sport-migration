---
name: huawei-sport-migration
description: "把小米、OPPO、悦跑圈、佳明、Strava 等平台导出的运动记录（GPX/TCX/FIT 或小米桥导出 JSON）转成合规 FIT，批量导入华为运动健康，并以服务端记录核验是否真的入库、有没有重复。用户说「把小米运动记录迁到华为」「这批 FIT 批量导进华为运动健康」「华为导入失败了帮我看看」「怎么确认华为那边到底导进去没有」「华为支持哪些运动类型」时使用。包含取数转换、FIT 编码、导入前自检、幂等上传、服务端核验、失败排查与平台限制探针。"
version: 1.3.0
agent_created: true
---

# 运动记录迁移到华为运动健康

把第三方平台导出的运动记录（GPX / TCX / FIT 或逐点明细）转成符合 Garmin FIT 规范的 activity 文件，批量导入华为运动健康，并以服务端记录核对「到底导进去没有、有没有重复」。

## 适用与边界

适用：

- 换了华为设备，想把小米、OPPO、悦跑圈、佳明、Strava 等平台的运动记录迁过来
- 手上有一批导出文件，需要批量生成可导入的 FIT
- 已经导入过，需要确认哪些真的入库、哪些重复了

不适用：

- 睡眠、步数、静息心率、体重、血氧：华为没有导入通道，任何工具都做不到
- 华为明确拒收的运动类型：只能用「手动添加运动记录」补录
- 修改或删除华为端已有记录：本包没有这个能力

## 六条硬规则

1. **只认服务端记录。** 导入页弹窗可能残留上一次的结果，页面里的「历史记录」是当前会话缓存，重新登录就空。判断是否入库，一律读服务端活动记录。
2. **先查后传，失败不自动重传。** 上传前先查服务端已有哪些记录。最近核验显示同一开始时间与运动类型的再次导入按整条覆盖处理，但该行为并非官方承诺，仍需核验是否产生多条记录。
3. **不造数据。** 源数据没有的心率、步频、GPS 不写、不插值、不估算。速度与逐点距离在源数据缺失时，只允许按「总里程 + 时间轴」派生，并在转换输出里写明派生了几场；不想派生就加 `--no-derive`。
4. **不接触账号凭据。** 数据导出由使用者自己在平台完成；本包不代登录、不代填、不保存账号密码与验证码。登录令牌只在已登录页面内临时使用，不落盘、不外传。
5. **接口变更先询问。** 迁移前主动询问使用者是否进行接口兼容性探测，说明只读检查、合成哨兵探测与跳过三种方式的步骤及影响；未经确认，不执行会写入账号的探测。入口：`scripts/check_api_compat.py`，说明见 `@references/api-compat-probe.md`。
6. **实时状态优先。** 页面文案、类型矩阵、字段结构与限制以**执行当时的探测结果**为准；`@references/current-status.md` 只是最近一次只读核验的时间基准，仓库里的「最近核验」不能替代它。发现差异时按实时结果调整流程并更新文档。

## 流程

### 前置 接口兼容性询问

先运行 `python scripts/check_api_compat.py` 或等价询问：说明导入页与内部接口可能变化，列出三种探测方式（只读检查 / 合成哨兵探测 / 跳过）及各自影响。选择「合成哨兵探测」时须再次确认写入账号的后果，并提醒使用者在 App 内自行删除测试记录。未经确认不得执行写入账号的探测。

再读 `@references/current-status.md`，确认最近一次只读核验的时间、页面文案与服务端字段结构；把实时结果与 `@references/huawei-limits.md`、`@references/field-reference.md` 比对，差异以实时结果为准。完整流程示例见 `@examples/end-to-end.md`，操作要点见 `@references/operational-notes.md`。

### 第 0 步 环境检查

在技能根目录执行（脚本按相对路径调用，换目录会找不到文件）：

```bash
python scripts/check_environment.py
```

- `ready`：直接进入第 1 步
- `partial`：转换/编码/自检可用，自动上传与核验不可用，按手动导入执行
- `needs_setup`：按提示安装缺失项后重跑，不要跳过

### 第 1 步 拿到原始数据并转换成 workouts.json

用户手上还没有导出文件时，先按 `@references/source-data.md` 指引取数，不要凭印象给路径。取数由用户自己完成，凭据不进本流程。

拿到文件后按来源选入口，两条路都只产出 `workouts.json`：

```bash
# 小米：mi_fitness_data_bridge 导出的 JSON（推荐，一份就够）
python scripts/from_bridge.py --input exports/mi_fitness.json --output workouts.json

# GPX / TCX / FIT（含 .gz）：OPPO、悦跑圈、佳明、Strava、其它平台
python scripts/convert.py --input <导出目录或文件> --output workouts.json
```

- 桥导出：`records` 下三张表按 `workout_id` 关联；时长优先 `valid_duration_seconds`，缺失时用 `duration_minutes`。逐点速度、累计距离、海拔并非都有，脚本会标注距离来源，缺失的按规则派生或不写
- 普通导出：目录会递归扫描，认不出的扩展名会列出来（小米官方 CSV 不会被自动解析）
- 运动类型自动判断，判断错了用 `--sport running` 强制指定（`from_bridge.py` 与 `convert.py` 同名参数）

转换结果要过一眼：距离是否为 0、采样点数量是否合理、开始时间是否正确。距离为 0 且无轨迹的记录，导入后大概率不显示。

### 第 2 步 判断类型能不能导

先看 `@references/huawei-limits.md` 的类型矩阵。矩阵是特定时间点的观察记录，平台行为可能变化。

不确定时自己测，用真实记录生成只差运动类型的探针：

```bash
python scripts/make_probe.py --input workouts.json --out-dir probes
```

一次只传一个类型、传完立刻核验，才能把结果归因到类型。一次传多个只会得到「有的成有的不成」。

探针时间会被挪到样本当天凌晨并逐个错开，不会和待导入记录撞到同一分钟；但探针导入后就是一条真实运动记录，本包删不掉，**测完要在 App 里手动删除**。

### 第 3 步 编码

```bash
python scripts/fit_encode.py --input workouts.json --out-dir out
```

默认 `--lap-mode auto`：跑步按公里分段，其它类型不写分段——华为对非跑步类型带分段会直接拒收。

### 第 4 步 自检

```bash
python scripts/fit_audit.py --fit-dir out --workouts workouts.json --report audit.json
```

有任何 `problems` 都不要上传。检查项包括必需消息、时间轴闭合、分段求和、非跑步类型是否误写 lap、坐标范围、`local_timestamp` 是否为合法时区偏移、与源数据的时长和距离偏差、单文件 5 MB 上限。

### 第 5 步 上传

```bash
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --dry-run
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --batch 50
```

`workouts.json` 是必需的：脚本用它确定这批文件对应哪些运动记录，缺了会直接拒绝运行，避免不知情地导入。
`--dry-run` 只列清单不上传，但仍需登录一次以读取服务端已有记录。
只想先把登录态准备好（还没生成 FIT 时）：`python scripts/huawei_upload.py --login-only`。

- 首次运行会打开浏览器并停在登录页，手动扫码或短信登录一次，之后记住登录态
- 脚本先读服务端已有记录，只传缺的；传完逐批回查，确认记录真的出现
- 比对键是「开始时间（分钟）+ 时长（秒）」，同一分钟的两场不同运动不会被当成一条
- 目录里不在 `workouts.json` 的文件（如探针）会回读 FIT 自身取开始时间，不会盲传
- 默认 10 个一批、批次间隔 2.5 秒，上限 50 个一批；导入页文件输入支持 `multiple`，文件多时用 `--batch 50` 一次提交整批
- 批量结果弹窗只给汇总、不指出失败文件：失败批先整批复传一次，仍失败再回退逐文件定位，不要反复自动重试（见 `@references/operational-notes.md`）

### 第 6 步 核验

```bash
python scripts/huawei_verify.py --fit-dir out --workouts workouts.json
```

输出「本地待导入 / 服务端记录 / 已入库 / 缺失 / 重复 / 时长不一致 / 无法确认」七项，并列出缺失、重复与无法确认的明细。无法确认指同一分钟已有多条记录、时长又都对不上，此时不要据此判定缺失或重复。

### 第 7 步 处理失败项

按 `@references/troubleshooting.md` 对照错误提示定位。修完重新走第 3—6 步，不要直接重传原文件。

## 命令速查

| 目的 | 命令 |
|---|---|
| 接口兼容性询问 | `python scripts/check_api_compat.py` |
| 环境检查 | `python scripts/check_environment.py` |
| 小米桥导出转中间格式 | `python scripts/from_bridge.py --input mi_fitness.json --output workouts.json` |
| 导出文件转中间格式 | `python scripts/convert.py --input <路径> --output workouts.json` |
| 生成类型探针 | `python scripts/make_probe.py --input workouts.json --out-dir probes` |
| 编码 FIT | `python scripts/fit_encode.py --input workouts.json --out-dir out` |
| 自检 | `python scripts/fit_audit.py --fit-dir out --workouts workouts.json` |
| 准备登录态 | `python scripts/huawei_upload.py --login-only` |
| 试运行上传 | `python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --dry-run` |
| 正式上传 | `python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --batch 50` |
| 核验 | `python scripts/huawei_verify.py --fit-dir out --workouts workouts.json` |

## 类型决策

| 运动 | 能否导入 | 编码要求 |
|---|---|---|
| 跑步 | 能 | 可按公里分段 |
| 步行、骑行、力量训练、羽毛球 | 能 | 必须零分段 |
| 游泳 | 最近核验拒收 | 建议改用 App 手动补录 |
| 乒乓球、电竞、划船机、攀岩 | 最近核验拒收（不认运动码） | 同上 |
| 其它类型 | 未知 | 用探针复核后再决定 |

## 通过条件

一次导入只有同时满足以下三条才算完成：

1. 核验报告「缺失」为 0
2. 核验报告「重复」为 0
3. 「时长不一致」为 0（容差 5 秒）

「无法确认」不为 0 时先人工看一遍：同一分钟已有多条记录，且时长都对不上，不能直接算成功，也不能直接重传。

平台限制导致无法导入的记录，单独列成清单交付，不并入成功数。

## 停止条件

出现以下情况立即停止，不要继续上传：

- 环境检查为 `needs_setup`
- 自检存在 `problems`
- 读取服务端记录失败（此时无法判断重复，盲传会造重复）
- 出现验证码、安全验证、「操作过于频繁」
- 登录失效且无法重新登录

## 输出模板

核验报告（`verify-report.md`）结构：

```markdown
# 华为导入核验报告
生成时间：YYYY-MM-DD HH:MM

| 项目 | 数量 |
|---|---|
| 本地待导入 | N |
| 服务端记录 | N |
| 已入库 | N |
| 缺失 | 0 |
| 重复（同一分钟同一时长多条） | 0 |
| 时长不一致 | 0 |
| 无法确认 | 0 |

## 缺失（服务端没有对应记录）
| 开始时间 | 文件 |
|---|---|

## 重复（同一分钟同一时长多条记录）
| 比对键 | 条数 | 文件 |
|---|---|---|

## 无法确认（同一分钟已有多条，时长都对不上）
| 比对键 | 文件 |
|---|---|
```

## 质量自查

交付前逐条确认：

- [ ] 每条记录都写了 file_id / device_info / sport / event / record / session / activity
- [ ] 非跑步类型没有 lap，`num_laps=0`
- [ ] `total_elapsed_time` 是墙钟跨度，`total_timer_time` 是有效运动时长
- [ ] `local_timestamp` 与结束时间差是 15 分钟的整数倍（合法时区偏移）
- [ ] 步频按 rpm 写入，且只有存在逐点步频时才写汇总
- [ ] 末条 `record.distance` 等于 `session.total_distance`（差 10 倍时华为判为异常，配速曲线不显示）
- [ ] 源数据缺距离/速度时，派生过的场次已在转换输出里标明，或用了 `--no-derive`
- [ ] 自检 `problems` 为空
- [ ] 已读 `@references/current-status.md`，并用 `check_api_compat.py` 的结果复核当前页面限制与字段结构
- [ ] 上传前跑过 `--dry-run`，确认待传清单没有已入库的文件
- [ ] 核验报告 0 缺失、0 重复、0 时长不一致、0 无法确认
- [ ] 无法导入的记录有单独清单，没有混进成功数
- [ ] 用过探针的话，探针记录已在 App 里删除

## 参考资料

- `@examples/end-to-end.md`：用合成数据走通的端到端全程示例
- `@references/current-status.md`：最近一次实时只读核验状态（时间基准）
- `@references/operational-notes.md`：批量、幂等、编码口径、失败处理等操作要点
- `@references/source-data.md`：各平台取数路径、能拿到的粒度、凭据存放与撤销
- `@references/input-schema.md`：中间格式字段与样例
- `@references/fit-encoding.md`：FIT 编码规则与单位
- `@references/huawei-limits.md`：平台限制与类型矩阵
- `@references/verification.md`：服务端核验方法与降级
- `@references/troubleshooting.md`：错误提示对照表
- `@references/security-privacy.md`：数据流向与凭据边界
- `@references/setup-guide.md`：依赖安装与登录配置

## 出处与许可

FIT 编解码依赖 Garmin 官方 SDK，小米与悦跑圈的数据导出依赖社区项目。逐项说明、版本与许可见仓库根目录 `THANKS.md`；对外转述本流程时，请一并保留这些出处。
