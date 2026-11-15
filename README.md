# huawei-sport-migration

把第三方平台的运动记录批量迁入华为运动健康的工具链，同时可作为 WorkBuddy 技能安装。

**一句话**：GPX / TCX / FIT → 合规 FIT → 批量导入 → 服务端核验。

## 这是什么

一套脚本，两种用法：

| 用法 | 入口 | 适合 |
|---|---|---|
| 命令行工具链 | `scripts/` | 想控制每一步，或集成进自己的流程 |
| WorkBuddy 技能 | `SKILL.md` | 让 Agent 按固定流程执行，你只说「把小米记录迁到华为」 |

范围仅限**运动记录**（跑步、骑行、游泳、力量、球类等）。睡眠、步数、静息心率、体重、血氧华为没有导入通道，任何工具都做不到；修改或删除华为端已有记录也不在能力范围内。

## 它解决什么

第三方平台导出的文件直接丢进华为导入页，通常有三种结果：结构不合规直接报错、提示成功但记录不存在、重复上传出现两条记录。

工具链对每种情况各有一道处理：编码前按 FIT 规范生成，上传前先查已有记录，导入后读服务端核对。具体规则写在 `references/`。

## 先拿到原始数据

工具链的输入是导出文件，这一步得先解决。各平台的路径不同，能拿到的粒度也不同：

| 平台 | 怎么取 | 需要凭据 | 能拿到 |
|---|---|---|---|
| 小米运动健康 | **`mi_fitness_data_bridge`（推荐，一条就够）** | `user_id` + `passToken` | 每场汇总 + 逐秒心率（步频、速度部分有，海拔没有）+ 户外场次的 GPS |
| 小米运动健康 | 隐私中心导出（`account.xiaomi.com` → 隐私中心 → 管理您的数据） | 只需网页登录 | 每场汇总 + 部分记录的 GPS（GPX 为带签名的下载链接，有时效）；无单场逐秒明细 |
| OPPO / 欢太健康 | App → 单条记录 → 「⋯」→ 导出运动数据 | 无 | FIT（优先）或 TCX，只能一条条导 |
| 悦跑圈 | App 导出，或 `running_page` 的 `joyrun_sync.py` | 手机号 + 验证码（本地运行） | GPX / TCX，约 5 秒采样 |
| 佳明 | connect.garmin.com → 活动 → 导出原始文件 | 网页登录 | FIT（带 lap，需经本工具重写） |
| Strava | 单条导出，或账号整体下载 | 网页登录 | GPX / TCX / `.fit.gz` |

小米**只走桥这一条就能完成迁移**：`from_bridge.py` 直接读桥导出的 JSON，汇总、逐秒心率、轨迹都够用。但不是每个字段都满——逐点距离只有不到一半场次有，GPS 约三分之一（仅户外），海拔基本为空，速度要靠 GPS 或按距离回算；脚本会打印每场距离的来源，不想派生就加 `--no-derive`。

官方导出属于替代方案：不想交出凭据、或桥失效时用它，代价是没有单场逐秒数据。**本包不解析官方导出的 CSV**：迁记录可以用包里的 GPX 走 `convert.py`，或按 `references/input-schema.md` 手工整理；CSV 更适合拿来核对桥算出的汇总值。

**源数据没有的指标，任何转换工具都补不出来。** 左右脚平衡、触地时间、垂直振幅属于跑步动态传感器数据，手机 App 的记录里通常不存在。

小米官方导出包里有四个文件各不相同，容易看错：`sport_record.csv` 是每场一行的主表；`sport_track_data.csv` 的 `GPX` 列是**带签名的下载链接**、有时效，要尽快下载；`fitness_data.csv` 是**全天**传感器流，不能用来还原某一场的逐秒心率；`aggregated_fitness_data.csv` 是按天聚合，迁移用不上。

逐平台路径、字段含义、凭据存放与撤销方式见 **[references/source-data.md](references/source-data.md)**。

拿到数据后先数一遍条数、抽查一场的开始时间与距离，再往下走。

## 快速开始

```bash
# 0. 环境自检（Python / FIT SDK / Playwright / 浏览器）
python scripts/check_environment.py

# 1. 转换成中间格式，二选一
python scripts/from_bridge.py --input exports/mi_fitness.json --output workouts.json   # 小米桥导出
python scripts/convert.py --input <导出目录> --output workouts.json                   # GPX / TCX / FIT

# 2. 编码 + 自检
python scripts/fit_encode.py --input workouts.json --out-dir out
python scripts/fit_audit.py --fit-dir out --workouts workouts.json

# 3. 导入 + 核验
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json
python scripts/huawei_verify.py --fit-dir out --workouts workouts.json
```

第 3 步会打开浏览器并停在华为登录页，扫码一次即可；登录态保存在本地 profile 目录，之后复用。只想先把登录办好：`python scripts/huawei_upload.py --login-only`。

没有现成导出文件时，可以先用 `assets/sample_mi_fitness.json`（合成数据）跑通第 1—2 步：

```bash
python scripts/from_bridge.py --input assets/sample_mi_fitness.json --output sample.json
python scripts/fit_encode.py --input sample.json --out-dir sample_out
python scripts/fit_audit.py --fit-dir sample_out --workouts sample.json
```

只想先看要传哪些、不实际提交：

```bash
python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --dry-run
```

## 数据流

```
小米 / OPPO / 悦跑圈 / 佳明 / Strava
      │  官方导出 · 隐私中心 · 桥接工具        （references/source-data.md）
      ▼
桥导出 JSON                GPX / TCX / FIT
      │ from_bridge.py            │ convert.py
      └────────────┬──────────────┘
                   ▼
              workouts.json
                   │ fit_encode.py
                   ▼
                 *.fit ──fit_audit.py──▶ 结构与源数据一致性
                   │
                   ├── huawei_upload.py ──▶ 华为运动健康（先查后传）
                   └── huawei_verify.py ──▶ 缺失 / 重复 / 时长偏差清单
```

## 命令一览

| 脚本 | 作用 | 参数 |
|---|---|---|
| `check_environment.py` | 检查运行环境 | `--json` |
| `from_bridge.py` | 小米桥导出 JSON → `workouts.json` | `--input` `--output` `--sport` `--no-derive` |
| `convert.py` | GPX / TCX / FIT → `workouts.json` | `--input` `--output` `--sport` |
| `fit_encode.py` | `workouts.json` → FIT | `--input` `--out-dir` `--lap-mode` `--cadence` |
| `fit_audit.py` | 解码回读并与源数据逐项比对 | `--fit-dir` `--workouts` `--report` |
| `huawei_upload.py` | 幂等批量导入 | `--fit-dir` `--workouts` `--dry-run` `--batch` `--delay` `--state` `--since` `--login-only` |
| `huawei_verify.py` | 服务端核验 | `--fit-dir` `--workouts` `--report` `--json` `--since` |
| `make_probe.py` | 生成只差运动类型的探针文件 | `--input` `--out-dir` `--sports` `--index` `--date` |

中间格式的字段定义见 `references/input-schema.md`。

## 作为技能安装

```bash
# 方式一：目录方式
~/.workbuddy/skills/huawei-sport-migration/

# 方式二：安装打包好的 zip（Release 里下载，或本地打）
huawei-sport-migration-<version>.zip
```

装好后对 Agent 说「把小米运动健康的记录迁到华为」，它会按 `SKILL.md` 里的七步流程执行。

## 目录

```
SKILL.md                 技能定义：适用边界、硬规则、流程与验收标准
README.md                本文件
THANKS.md                第三方项目、许可与出处
LICENSE                  MIT
scripts/                 八个可执行脚本
references/              取数路径、输入格式、FIT 编码规则、平台限制、核验方法、排查表、安全说明
assets/                  合成示例数据（workouts / GPX / 桥导出各一份，不含真实个人信息）
skill-dependencies.json  依赖与降级路径
```

## 平台兼容性（实测于 2026-11）

| 项目 | 结论 |
|---|---|
| 华为导入页 | 单批 ≤ 50 个文件，单文件 ≤ 5 MB，导入后不能改运动类型，不做去重 |
| FIT 可导入 | 跑步、步行、骑行、力量训练、羽毛球 |
| FIT 实测拒收 | 游泳、乒乓球、电竞、划船机、攀岩 |
| TCX | 仅跑步与骑行 |

平台会变。拿不准时用 `make_probe.py` 造一组只差运动类型的最小文件自己复测一次，比相信任何文档都可靠。探针会作为真实记录入库，测完在 App 里删掉。

生成的 FIT 里写的是 Garmin 设备标识（一组实测可被华为接受的组合），不是真实设备；华为侧可能把它显示成对应设备。记录本身的时间、距离、心率都来自你的源数据。

## 依赖

- Python 3.10+
- `garmin-fit-sdk`：FIT 编解码，必需
- `playwright`：可选，用于自动导入与核验；没有就手动上传

```bash
pip install garmin-fit-sdk playwright
playwright install chromium
```

## 隐私与安全

- 不读取、不保存账号密码与验证码，登录在真实浏览器里由你完成
- 运动数据只在你本机与你的华为账号之间流动，没有中间服务器
- 登录态存放于 `~/.huawei-sport-migration/browser-profile/`，删除即退出
- 不删除、不修改华为端已有记录；未核验不重复上传

## 致谢

FIT 编解码用的是 Garmin 官方 SDK；小米与悦跑圈的数据导出站在社区项目 `mi_fitness_data_bridge`、`Mi-Fitness-Sync`、`running_page` 之上。逐项说明与许可见 **[THANKS.md](THANKS.md)**。

## 许可

本仓库代码以 MIT 发布；依赖与数据来源的许可各不相同，见 [THANKS.md](THANKS.md)。
