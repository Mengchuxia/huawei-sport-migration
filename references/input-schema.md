# workouts.json 输入格式

所有脚本都用这一份中间格式。`convert.py` 从 GPX/TCX/FIT 生成它，`from_bridge.py` 从小米桥导出生成它；也可以自己从任何平台的数据构造。各平台的取数路径见 `source-data.md`。

## 顶层

```json
{"workouts": [ {...}, {...} ]}
```

也接受直接给数组。

## 单条记录

| 字段 | 必填 | 说明 |
|---|---|---|
| `sport` | 是 | `running` / `walking` / `cycling` / `swimming` / `strength` / `badminton` / `pingpong` / `rowing_machine` / `climbing` / `e_sports` 等，见 `fit_encode.py` 的 `SPORT_MAP` |
| `start_time` | 是 | ISO8601。带时区如 `2024-05-01T07:30:00+08:00`；不带时区按运行机器的本地时间解释 |
| `duration_s` | 是 | 有效运动时长（秒），即「计时器」时间，不含暂停 |
| `elapsed_s` | 否 | 墙钟总时长（秒），含暂停。缺省等于 `duration_s` |
| `distance_m` | 否 | 总距离（米）。没有就写 0 或省略 |
| `calories` | 否 | 总消耗（千卡） |
| `avg_hr` / `max_hr` / `min_hr` | 否 | 心率汇总。缺省时用采样点回算 |
| `avg_cadence_spm` / `max_cadence_spm` | 否 | 跑步/步行用步/分；骑行可给踏频（转/分） |
| `max_speed_mps` | 否 | 最大速度（米/秒）。缺省时用采样点回算 |
| `ascent_m` / `descent_m` | 否 | 累计爬升/下降（米） |
| `sub_sport` | 否 | 覆盖默认子类型（跑步默认 2=户外，室内跑步填 1） |
| `tz_offset_min` | 否 | 时区偏移（分钟）。缺省按运行机器的本地时区推算，不写死 480 |
| `id` | 否 | 用于文件名的稳定标识；缺省用开始时间 |
| `samples` | 是 | 逐点采样，见下 |

## samples

按时间递增，`t` 是相对 `start_time` 的秒数：

| 键 | 单位 | 说明 |
|---|---|---|
| `t` | 秒 | 必填，相对开始时间 |
| `hr` | 次/分 | 心率 |
| `cad` | 步/分（跑步/步行）或 转/分（骑行） | 编码时按运动类型换算成 FIT 的 rpm |
| `speed` | 米/秒 | 瞬时速度 |
| `dist` | 米 | **累计**距离 |
| `alt` | 米 | 海拔 |
| `lat` / `lon` | 十进制度 | 纬度 / 经度 |

缺哪个字段就不写对应的 FIT 字段，工具不会插值、不会补造。

`from_bridge.py` 有一个例外：源数据完全没有逐点距离、但有总里程时，会按总里程与时间轴线性还原，并打印「距离来源：derived」；加 `--no-derive` 则只保留 GPS 采样与源数据，缺什么留什么。海拔在桥导出里拿不到，`alt` 会整段缺失，这是正常现象。

## 示例

```json
{
  "id": "morning-run",
  "sport": "running",
  "start_time": "2024-05-01T07:30:00+08:00",
  "duration_s": 600,
  "elapsed_s": 640,
  "distance_m": 1921.9,
  "calories": 95,
  "avg_hr": 138,
  "max_hr": 156,
  "avg_cadence_spm": 170,
  "samples": [
    {"t": 0, "hr": 120, "cad": 168, "speed": 3.1, "dist": 0, "alt": 3200.0, "lat": 32.0, "lon": 97.0},
    {"t": 1, "hr": 121, "cad": 169, "speed": 3.12, "dist": 3.1, "alt": 3200.1, "lat": 32.0000045, "lon": 97.0000052}
  ]
}
```

完整可运行样例见 `assets/sample_workouts.json`。

## 质量要求

- `samples` 覆盖整段时间：首点接近 `t=0`，末点接近 `elapsed_s`
- 只有汇总、没有逐点数据的记录也能编码，但华为侧可能判定「无有效细节」而不显示
- 距离必须是累计值；分段递增的距离会被当成累计值使用，导致总里程离谱
- `start_time` 不带时区时按**运行机器的本地时间**解释。`convert.py` 写出的就是本机本地时间，所以 `workouts.json` 不要在时区不同的机器之间搬运，否则整批记录会偏移
