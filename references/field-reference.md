# 字段含义与对照

本文区分两套容易混淆的字段：**FIT 文件内的消息/字段**（Garmin FIT 规范）与**华为服务端运动记录的结构/字段**（Health Kit 数据类型）。导入页接受 FIT 文件，但服务端展示与保存的是后者。

## 1. FIT 文件侧（Garmin FIT SDK）

FIT Activity 文件的结构由 Garmin FIT 规范定义：

| 消息 | 作用 |
|---|---|
| `file_id` | 文件类型、厂商、产品、序列号；应为首条消息 |
| `session` | 整场汇总：开始时间、时长、距离、卡路里、心率、步数、速度、坐标边界等 |
| `lap` | 分段汇总：每段时长与距离；规范要求至少一个 lap，且合计与 session 一致 |
| `record` | 逐点数据：时间戳、GPS、心率、步频、速度、累计距离等 |
| `device_info` / `event` | 可选，设备信息与计时事件 |

字段的数据类型、单位、枚举与子字段（例如 `total_cycles` 在 `sport` 不同取值下解释为 strides / strokes）以 FIT Profile 为准。参考：

- [Garmin: Activity File](https://developer.garmin.com/fit/file-types/activity/) — 必需消息、消息顺序与结构要求
- [Garmin FIT SDK 文档](https://developer.garmin.com/fit/) — Profile 与 SDK 下载
- [Garmin: Decoding Activity Files](https://developer.garmin.com/fit/cookbook/decoding-activity-files/) / [Encoding Activity Files](https://developer.garmin.com/fit/cookbook/encoding-activity-files/) — 编解码示例

## 2. 华为服务端运动记录侧（Health Kit）

服务端 `activityRecord` 的 `activitySummary` 近期观察到的顶层结构：

| 结构 | 内容 |
|---|---|
| `dataSummary` | 统计值数组，元素含 `dataTypeName` 与 `value`（字段值数组） |
| `sectionSummary` | 分段数组，单段键含 `sectionNum`、`sectionTime`、`startTime`、`endTime`、`sectionDataList` |
| `performanceSummary` | 训练表现，例如 `heartRateZoneStatistics` 心率区间统计 |
| `paceSummary` | 配速相关，例如 `avgPace`、`bestPace`、`paceMap`、`partTimeMap` |

`dataTypeName` 采用 `com.huawei.` 前缀的命名空间，近期一次合成数据核验中返回的统计类型包括：心率统计、距离总量、步频统计、海拔统计、卡路里总量、步数总量、运动心率统计、速度统计与步幅统计。**该清单仅为一次观察结果，不代表写入白名单，也不代表所有运动类型均可用。**

官方参考：

- [锻炼记录数据](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/activity-record-data-0000001131649642) — 运动记录数据类型说明
- [数据类型](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/restful-data-type-0000001131423768) — REST 数据类型总览
- [原子采样数据](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/atomic-sampling-data-types-0000001324971013) — 逐点采样数据说明
- [ActivityRecord](https://developer.huawei.com/consumer/cn/doc/HMSCore-References/activityrecord-0000001050091641) — 运动记录对象
- [ActivityRecordsController](https://developer.huawei.com/consumer/cn/doc/HMSCore-References/activityrecordscontroller-0000001050091295) — 运动记录接口
- [跑步运动记录（含分段）](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/running-section-scene-0000001338170765) — 分段数据示例

## 3. 两点需要注意的差异

1. **写入字段不等于展示字段。** 服务端可能按 `record` 采样点重新计算步数、心率区间、最大速度等统计值；仅修改 session 汇总值不一定改变服务端结果。
2. **单位与命名不同。** 例如 FIT `session` 使用秒、米、毫米等 FIT 单位，服务端结构使用各自字段名与取值格式；两者需按各自规范解释，不做等号对应。

官方文档为 SPA 页面，目录需展开；链接路径、字段清单与取值均可能变化，使用前应以官方文档当时版本为准。
