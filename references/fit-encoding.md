# FIT Activity 编码规则

依据 Garmin 官方 Activity 文件规范与 FIT Profile 字段定义，配合华为导入页的实际行为。
`fit_encode.py` 已实现全部规则，改动编码逻辑前先读这一页。

## 1. 必需消息与顺序

| 消息 | 号 | 要求 |
|---|---|---|
| file_id | 0 | 必须是第一条，`type=4`（activity） |
| file_creator | 49 | 记录生成工具 |
| device_info | 23 | 至少一条，`device_index=0` 表示写入设备 |
| sport | 12 | 运动类型 + 子类型 |
| event | 21 | 开始事件（event=0, event_type=0）与结束事件（event_type=4） |
| record | 20 | 至少一条，每条必须有 `timestamp` 且至少再带一个值 |
| lap | 19 | 可为零条，但只要有就必须自洽 |
| session | 18 | 汇总，必须与 lap、record 时间轴一致 |
| activity | 34 | 最后一条，必须写 `local_timestamp` |

## 2. 时间轴闭合

- `session.start_time` ≤ 所有 `record.timestamp` ≤ `session.timestamp`
- `session.total_elapsed_time` = `session.timestamp - session.start_time`（墙钟跨度，含暂停）
- `session.total_timer_time` = 有效运动时长，必须 ≤ `total_elapsed_time`
- 每个 lap 的 `total_elapsed_time` = 该段起止时间戳之差，**不要按比例缩放**
- 所有 lap 的 `total_elapsed_time` 之和 = session 的；距离同理

违反后果：华为报 `Invalid section startTime` 或 `ActivityRecord.details.time does not match`。

## 3. 分段策略

- 跑步：每 1 公里一段，尾段不足 20 米或不足 5 个点并入上一段
- 其它类型：**不写 lap**（`num_laps=0`）。华为对非跑步类型报
  `This activityType is not support section.`
- 只有一条 lap 也不等于「不分段」：要额外写 `num_laps=1` 或干脆不写 lap

## 4. 单位与缩放

| 字段 | 单位 | scale | offset |
|---|---|---|---|
| `total_distance` / `distance` | 米 | 100 | — |
| `total_elapsed_time` / `total_timer_time` | 秒 | 1000 | — |
| `speed` | 米/秒 | 1000 | — |
| `altitude` | 米 | 5 | 500 |
| `position_lat` / `position_long` | 半圆 semicircles | — | — |
| `cadence` | 转/分（rpm） | — | — |

坐标换算：`semicircles = degrees × 2^31 / 180`。

**逐点距离必须与总里程同量纲、同基准。** `record.distance` 是累计值，必须单调递增，
末条要等于 `session.total_distance`。两者差 10 倍时，华为会把逐点配速算成几秒一公里，
按「异常数据」处理，结果是 App 里只剩平均配速、没有配速曲线。
`fit_audit.py` 会直接比对末条距离与总距离；不一致就不要上传。

小米桥导出的 `workout_detail.distance_m` 是**每秒增量、单位分米**，不能直接当累计米用；
`from_bridge.py` 会先累加、再按总里程把量级压回。

## 5. 步频

- FIT 规范里跑步的 `cadence` 是 rpm，等于「步/分 ÷ 2」
- session/lap 的 `avg_cadence`、`max_cadence` 只在**存在逐点步频序列**时才写，
  否则华为报 `Mismatched value count: continuous.steps.rate.statistics`
- 逐点 `record.cadence` 始终保留

## 6. 汇总值取权威来源

设备或原厂给出的 `avg_hr`、`max_hr`、`distance`、`calories` 优先；
逐点均值只在缺失时回退。两者常差 2—3 bpm，以源系统展示值为准。

## 7. 空数据与短记录

- 没有任何采样点的记录：写一条只含 `timestamp` + `distance` 的 record，否则文件缺必需消息
- 极短记录（十几秒）仍可编码，但平台可能判定为无效而不显示，属于平台侧行为

## 8. 文件大小

华为单文件上限 5 MB。实测约 32 字节/点（时间戳 + 心率 + 距离 + 速度 + GPS），
1 秒采样下 5 MB 约合 16 万点、连续记录 45 小时；3 小时骑行约 350 KB，远没到上限。

当前版本**不含抽稀工具**。真遇到超大文件（长时间高频采样），先确认是否必须保留 1 秒粒度，
再自行降采样后重新编码；`fit_audit.py` 只会把超过 5 MB 的文件标成问题，不会自动处理。

## 9. 设备标识

`file_id` 与 `device_info` 里写的是一组实测可被华为接受的 Garmin 设备标识（manufacturer/product/serial），
不是真实设备。华为侧可能把记录显示成对应设备，这是导入能通过的前提，不影响时间、距离与心率。

## 10. 自检

`fit_audit.py` 会重新解码生成的文件并核对上述规则，包括：

- 必需消息齐全、record 时间戳递增且落在 session 区间内
- 分段时长/距离之和等于 session、`num_laps` 与实际分段数一致
- 非跑步类型没有 lap
- 坐标范围合法
- `activity.local_timestamp`（uint32，FIT 纪元 1989-12-31 起算）与结束时间之差是 15 分钟的整数倍
- 与源数据的时长、距离偏差，单文件 5 MB 上限

任何 `problems` 非空都不要上传。
