# 从各平台拿到原始数据

工具链的输入是导出文件。转换前需确认导出文件包含哪些粒度的数据。本文按平台说明取数路径，并标注每种方式**通常能取得什么、哪些字段可能缺失**。

## 先想清楚一件事：你需要哪种粒度

| 粒度 | 内容 | 影响 |
|---|---|---|
| 只有汇总 | 每场一行：开始时间、时长、距离、卡路里、平均/最大心率 | 能导入，但华为侧可能因「无有效细节」不显示，图上是一条平线 |
| 汇总 + GPS | 上面再加轨迹 | 有路线图，配速曲线可算，心率仍可能是平的 |
| 汇总 + 逐点 | 每秒心率、步频、速度、累计距离、海拔、GPS | 最接近原平台体验，导入后曲线完整 |

先确认源平台能给到哪一档，再决定值不值得折腾。**源数据没有的指标，任何转换工具都补不出来**——左右脚平衡、触地时间、垂直振幅属于跑步动态传感器数据，手机 App 记录里通常不存在。

## 小米运动健康

小米数据常见三条出口。路线 B 可同时提供每场汇总、逐点明细与部分轨迹，`from_bridge.py` 可直接转换；路线 A 不依赖会话凭据，适合作为替代与汇总核对，代价是缺少单场逐点明细；路线 C 提供单条导出，覆盖记录取决于客户端可读范围。

### 路线 A：官方隐私中心导出（不交凭据；桥不可用时的替代与核对手段）

1. 打开 <https://account.xiaomi.com>，登录你的小米账号
2. 进入「隐私中心」→「管理您的数据」→ 找到「小米运动健康」
3. 申请导出，等待邮件；邮件里是下载链接，压缩包**可能带密码**（密码在同一封邮件里）
4. 解压后得到一组 CSV，文件名形如 `20260101_<uid>_MiFitness_hlth_center_sport_record.csv`

| 文件 | 内容 | 对迁移的用处 |
|---|---|---|
| `*_sport_record.csv` | 每场运动一行。`Key` 是运动类型（`outdoor_running` / `outdoor_walking` / `outdoor_riding` / `badminton` / `pingpong` / `free_training` 等），`Value` 是 JSON | **主表**，一场一行，汇总字段齐全 |
| `*_sport_track_data.csv` | 轨迹表。`GPX` 列是**带签名的下载链接**（含 `Expires`、`GalaxyAccessKeyId`、`Signature`） | 轨迹来源。链接**有时效**，拿到导出包后尽快下载并本地保存 |
| `*_fitness_data.csv` | 全天传感器流，`Key` ∈ `heart_rate` / `steps` / `stress` / `spo2` / `calories` / `body_momentum` 等 | 只能做旁证，**不是**单场绑定数据，无法还原某场跑步的逐秒心率 |
| `*_aggregated_fitness_data.csv` | 按天聚合（步数、消耗、报告） | 迁移用不上 |
| `*_statistics_data.csv`、`*_sleep_*`、`*_diet_*` | 统计、睡眠、饮食 | 迁移用不上（华为没有这些数据的导入通道） |

`sport_record.csv` 的 `Value` 里能拿到：

```
start_time / end_time / timezone / version / proto_type / sport_type
duration（有效时长）  distance  calories
avg_pace / max_pace / min_pace / max_speed
steps  avg_cadence  max_cadence
avg_hrm / max_hrm / min_hrm
rise_height / fall_height
```

注意两点：

- `duration` 是有效运动时长，`end_time - start_time` 是墙钟跨度。两者经常不等（中途有暂停），转 FIT 时分别对应 `total_timer_time` 与 `total_elapsed_time`，不要混用。
- `timezone` 是编码值（如 `32` 表示 UTC+8），不是分钟数，别直接当偏移量写。

**这条路线拿不到单场逐秒明细。** `version <= 0` 的记录连 App 自己都没有明细。

**本包不直接解析这些 CSV。** 能直接喂给工具链的是 `sport_track_data.csv` 里那些 GPX：下载到本地后走 `convert.py`。只有汇总、没有轨迹的记录，需要按 `input-schema.md` 整理成 `workouts.json`——本包没有为 CSV 写适配脚本，与其猜列名，不如按上表的字段手工转一遍。

### 路线 B：mi_fitness_data_bridge（推荐；单独一条即可完成迁移）

项目地址见 `THANKS.md`。它通过小米运动健康的运动明细接口（FDS 二进制协议）取秒级样本与 GPS。

```bash
# 安装后初始化（交互式，凭据只写到本机 keyring）
mi-fitness-bridge setup      # 依次输入 user_id、passToken、地区（默认 cn）
mi-fitness-bridge doctor     # 检查配置、凭据、数据库与云端连通性

# 同步并按 JSON 导出
mi-fitness-bridge sync --type workout --start-date 2018-01-01 --end-date 2026-12-31
mi-fitness-bridge export --format json
```

导出的 JSON 顶层是 `records`，里面三张表并列，靠 `workout_id` 关联：

```json
{"records": {"workouts": [...], "workout_detail": [...], "workout_gps": [...]}}
```

本包直接吃这份文件：

```bash
python scripts/from_bridge.py --input exports/mi_fitness.json --output workouts.json
```

字段映射与可用性（字段覆盖取决于设备、账号地区、固件与上游服务）：

| 数据集 | 关键字段 | 落到 `workouts.json` | 可用性 |
|---|---|---|---|
| `workouts`（每场一行） | `activity_type` `start_at` `end_at` `distance_m` `calories_kcal` `avg/max/min_heart_rate_bpm` `rise/fall_height_m` | `sport` `start_time` `elapsed_s` `distance_m` `calories` `avg/max/min_hr` `ascent/descent_m` | 常见有值；具体覆盖随来源变化 |
| `workouts` | `valid_duration_seconds` | `duration_s` | 常为空，需按其它时长字段兜底 |
| `workouts` | `duration_minutes` | `duration_s` 的兜底 | 通常有值 |
| `workouts` | `avg_cadence` / `max_cadence` | `avg/max_cadence_spm` | 部分场次有值 |
| `workout_detail`（逐秒） | `offset_seconds` `heart_rate_bpm` | `samples[].t` `hr` | 逐点心率通常有值 |
| `workout_detail` | `cadence` / `distance_m` | `samples[].cad` / `dist` | 部分场次有值 |
| `workout_detail` | `speed_mps` / `altitude_m` | — | 该来源常见为空 |
| `workout_gps` | `latitude` `longitude` `speed_mps` | `samples[].lat/lon/speed` | 户外场次可能有轨迹；速度取决于客户端导出 |

字段单位需单独注意：`workout_detail.distance_m` 是**每秒增量、单位分米**，不是累计米。
`from_bridge.py` 会先累加，再按 `workouts.distance_m` 把量级压回；直接拿它当米用，
若按累计米解释，距离量级会偏大，配速随之异常，服务端可能判定数据无效。

以下字段特性会影响转换结果：

- **时长不要只看 `valid_duration_seconds`**，该字段可能为空。脚本按 `valid_duration_seconds` → `duration_minutes × 60` → `end_at - start_at` 依次兜底
- **逐点速度与海拔可能不在明细里**。速度可从 `workout_gps.speed_mps` 取，没有时按距离差回算；海拔缺失则不写
- **逐点距离只有部分场次有**。有就用，没有就用 GPS 算，再没有才按总里程与时间轴还原（`--no-derive` 可关掉这一步）

`from_bridge.py` 会打印每场距离的来源与派生场次数，转换后对一眼：`delta` 为源数据自带差值、`cumulative` 为源数据累计值、`gps` 为按轨迹回算、`derived` 为按总里程还原、`none` 为整场无距离。

原厂 CSV 在这里的角色是核对：拿 `sport_record` 的汇总值去比桥解析出来的数字，确认没有漏字段或单位错位。两者对不上时以原厂为准——App 显示的是它自己算的值。

两条路线可独立使用；路线 A 可用于核对汇总口径，不要求同时执行。

**凭据说明**：`user_id` 与 `passToken` 属于小米账号的浏览器会话凭据。本项目**不代取、不代登录、不代存**，也不接受把它们写进命令行或提交到任何地方。取法与安全要求以该项目自己的文档为准。

**安全边界**：

- `passToken` 等价于账号的读取权限，泄露会导致运动数据外泄
- 只存本机 keyring，不写进脚本、不进截图、不进 issue
- 用完后在小米账号的登录设备/安全设置里让该会话失效，token 立即作废
- 这类凭据通常会在下次登录时轮换；轮换后旧值自动失效

### 路线 C：Mi-Fitness-Sync（邮箱 + 密码，直出 GPX/TCX/FIT）

适用于单条记录导出、且不希望使用会话令牌的场景。

```bash
mi-fitness-sync export-activity --format fit --id <活动ID>
```

- 单条导出，没有批量命令；要批量就自己循环 `list-activities --json`
- 认证是邮箱 + 密码，手机号注册的账号可能登不上，还可能触发验证码
- 输出质量高（GPS 平滑、配速/步频/心率齐全），但覆盖面取决于客户端能读到哪些记录

### 三条路线怎么选

| 场景 | 可选路线 |
|---|---|
| 需要汇总、逐点明细与轨迹 | B；`from_bridge.py` 可直接转换 |
| 不希望提供会话凭据 | A；缺少单场逐点明细，需按输入格式手工整理 |
| 桥版本变更、接口失效，需要应急 | A；官方导出结构稳定，够先把记录迁过去 |
| 只要跑步，想直接拿到成品 GPX/TCX/FIT | C |
| 想更稳一点 | B 生成文件 + A 核对汇总值，两者按开始时间对齐 |

## OPPO / 欢太健康

App 内：运动 → 打开某条记录 → 右上角「⋯」→ 导出运动数据 → 选 FIT 或 TCX。

- **只能一条一条导**，没有批量入口
- 优先选 FIT：TCX 的运动类型常写成 `Other`，下游无法判断是跑步还是骑行
- 支持分享到 Google Fit / Health Connect / Strava，但**没有华为**，这条链路对迁入华为没用

少量记录手工导出即可，导出后放进同一个目录，`convert.py` 会一起处理。

## 悦跑圈

- App 内单条记录可导出 GPX / TCX
- 批量可以走 `running_page` 的 `joyrun_sync.py`（手机号 + 验证码登录，本地运行，凭据不出本机），见 `THANKS.md`

数据质量要先看清楚：**采样间隔约 5 秒、没有逐点时间戳**，转成 FIT 后曲线比小米粗一档。定位是兜底与交叉核验，不适合当主线。

## 佳明 / Garmin Connect

connect.garmin.com → 活动列表 → 选中记录 → 导出 → 原始文件（`.fit`）。

佳明导出的 FIT 本身就是规范产物，但**不要直接拿去传华为**：华为对非跑步类型带分段会拒收，佳明记录一律带 lap。走一遍 `convert.py` → `fit_encode.py`，由工具按目标平台规则重写。

## Strava

- 单条：活动页 → 导出 GPX / TCX
- 批量：Settings → My Account → Download or Delete Your Account → 得到 `activities.csv` + `activities/*.fit.gz`

批量包含全部历史，但只有**曾经同步到 Strava 的记录**。从小米单向同步过去的历史活动，官方明确不支持回补。

## 其它平台：GPX 是通用出口

只要平台能导出 GPX，就能接进来。GPX 的 `<trkpt>` 是公共结构，本工具读它算距离（Haversine）、取心率/步频/海拔（Garmin TrackPointExtension），再生成 FIT。很多小众 App 只给 GPX，这条路够用。

## 拿到数据后先做三件事

1. **数一遍**：导出条数与 App 里看到的记录数是否一致。少了，通常是导出范围没选全，或该平台只导出近 N 年
2. **抽查一场**：打开文件看开始时间、距离、时长、有没有轨迹点。开始时间错一小时，多半是时区；距离为 0 且无轨迹，导入后大概率不显示
3. **看有没有逐点**：只有一行的汇总记录可以导，但不要指望华为画出曲线

确认后再交给转换，按来源二选一：

```bash
python scripts/from_bridge.py --input exports/mi_fitness.json --output workouts.json   # 小米桥导出
python scripts/convert.py --input <导出目录> --output workouts.json                   # GPX / TCX / FIT
```

`convert.py` 支持 `.gpx` / `.tcx` / `.fit`，会递归扫描目录，也接受 `.fit.gz` 这类压缩包；认不出的文件会在结尾列出来，不会悄悄跳过。转换后建议看一眼条数：

```bash
python -c "import json;print(len(json.load(open('workouts.json',encoding='utf-8'))['workouts']))"
```

条数对不上，先解决取数问题，不要急着往下编码。

## 凭据与隐私对照

| 平台 | 需要凭据 | 凭据形态 | 存放位置 | 怎么撤 |
|---|---|---|---|---|
| 小米（路线 A） | 只需网页登录 | 会话 Cookie | 浏览器 | 退出登录 |
| 小米（路线 B） | 需要 | `user_id` + `passToken` | 本机 keyring（由该项目管理） | 小米账号安全设置里让会话失效 |
| 小米（路线 C） | 需要 | 邮箱 + 密码 | 该项目自己的存储 | 改密码 |
| 悦跑圈 | 需要 | 手机号 + 短信验证码 | 仅内存，本地运行 | 无需处理 |
| 佳明 / Strava | 网页登录后导出 | 会话 Cookie | 浏览器 | 退出登录 |

本仓库不接收、不转发、不保存任何平台凭据。所有取数都在你本机完成，数据不经过第三方服务器——这也是不采用「云转换服务」的原因：那类服务要求把账号或验证码交给对方服务器。
