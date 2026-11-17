# huawei-sport-migration

把第三方平台导出的运动记录编码为 FIT Activity 文件，导入华为运动健康，并以服务端记录核对结果的本地工具链。仓库同时提供一份 WorkBuddy 技能定义（`SKILL.md`）。

**范围**：仅限运动记录。睡眠、日常步数、静息心率、体重、血氧等数据没有对应的华为导入通道；本仓库不提供华为端记录的修改或删除能力。

> **到手就用**：[examples/end-to-end.md](examples/end-to-end.md) 用仓库自带的合成数据走完整条链路（环境检查 → 生成 FIT → 自检 → 导入 → 服务端核验）。
> **执行前先看**：[references/current-status.md](references/current-status.md) 记录最近一次只读核验的时间、页面文案与服务端字段结构，并运行 `python scripts/check_api_compat.py`。**导入页当时的实时状态优先于本仓库任何静态结论。**

## 工作流

```
导出文件（GPX / TCX / FIT / 小米桥导出 JSON）
    → workouts.json（统一中间格式）
    → FIT Activity（按 Garmin FIT 规范编码）
    → 华为运动健康网页导入页
    → 服务端记录核验
```

| 阶段 | 入口 | 说明 |
|---|---|---|
| 取数 | 各平台官方导出 / 社区桥接工具 | 由使用者自行完成，凭据不进入本工具链 |
| 转换 | `scripts/from_bridge.py`、`scripts/convert.py` | 输出 `workouts.json`，字段见 `references/input-schema.md` |
| 编码与自检 | `scripts/fit_encode.py`、`scripts/fit_audit.py` | 检查必需消息、时间轴、分段求和、文件体积 |
| 导入 | `scripts/huawei_upload.py` | 通过官方导入页提交，先读服务端已有记录 |
| 核验 | `scripts/huawei_verify.py` | 以服务端记录判断缺失与重复 |

快速开始见 `examples/end-to-end.md`；命令参数与降级路径见 `references/setup-guide.md`、`SKILL.md`；容易踩到的工程要点见 `references/operational-notes.md`。

## 数据来源（小米侧）

小米运动健康的数据可来自小米隐私中心导出，或社区开源桥接项目导出的 JSON。本仓库**只包含读取这些导出文件的转换脚本，不包含桥接项目源码**。

| 来源 | 许可 | 说明 |
|---|---|---|
| [shkyyy18/mi_fitness_data_bridge](https://github.com/shkyyy18/mi_fitness_data_bridge) | AGPL-3.0 | 导出每场汇总、逐点明细与部分轨迹；非官方项目，依赖非公开上游接口 |
| [kevinkwee/Mi-Fitness-Sync](https://github.com/kevinkwee/Mi-Fitness-Sync) | MIT | FDS 二进制明细与 TCX/FIT 渲染的参考实现 |
| [heshi2019/Mi-Fitness_DataAnalyze](https://github.com/heshi2019/Mi-Fitness_DataAnalyze) | — | 小米导出字段的中文注释参考 |
| [yihong0618/running_page](https://github.com/yihong0618/running_page) | — | 悦跑圈 GPX/TCX 导出路径参考 |

桥接导出常见字段包括每场的开始/结束时间、时长、距离、卡路里、心率统计、步数、逐点心率/步频/速度/累计距离，以及部分户外场次的 GPS。字段覆盖取决于设备、账户地区、固件版本与上游服务；海拔、功率、跑步动态等通道可能缺失。**源数据没有的指标，转换过程不补写、不插值。** 逐文件说明见 `references/source-data.md`。

上述项目与本仓库无隶属关系，其可用性、字段结构与许可由各自项目决定；本仓库不对其行为作保证。

## 华为接受哪些数据

以下为 2026-11-18 01:02 只读核验的记录，完整快照与核验方式见 `references/current-status.md`。页面文案、字段结构与限制均可能随平台版本变化；**以导入页当时的实时显示为准**。

| 项目 | 当前观察 |
|---|---|
| 文件格式 | FIT 或 TCX（页面单选） |
| 页面列出的 FIT 支持类型 | 跑步、骑行、游泳、步行、铁三、力量训练 |
| TCX 支持类型 | 跑步、骑行 |
| 单批文件数 | ≤ 50；文件输入为 `multiple`，一次提交可带多个文件 |
| 单文件体积 | ≤ 5 MB |
| 导入后修改运动类型 | 页面不提供该能力 |
| 重复导入 | 最近一次核验（2026-11-18）：同一开始时间与运动类型的再次导入按整条覆盖处理，未观察到新增记录 |
| 统计与分段 | 服务端按采样点计算部分统计值；分段结构本次只在跑步类型上观察到 |
| 导入数据口径 | 页面原文：导入数据不计入运营相关统计、个人成就统计、周月年报统计与运动能力评估 |

逐类型的可导入矩阵、错误码与复测方式见 `references/huawei-limits.md`；服务端返回的字段结构见 `references/field-reference.md`。

### 字段含义与外部参考

FIT 文件本身的消息与字段定义属于 Garmin FIT 规范；华为服务端运动记录的字段属于 Health Kit 数据类型体系。两者不是同一套字段，参考链接如下：

| 主题 | 链接 |
|---|---|
| FIT Activity 文件的必需消息（file_id / session / lap / record）与结构 | [Garmin: Activity File](https://developer.garmin.com/fit/file-types/activity/) |
| FIT 字段定义总表（Profile） | [Garmin FIT SDK 文档](https://developer.garmin.com/fit/) |
| 华为「锻炼记录数据」数据类型 | [developer.huawei.com: 锻炼记录数据](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/activity-record-data-0000001131649642) |
| 华为 REST 数据类型总览 | [developer.huawei.com: 数据类型](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/restful-data-type-0000001131423768) |
| 华为原子采样数据 | [developer.huawei.com: 原子采样数据](https://developer.huawei.com/consumer/cn/doc/HMSCore-Guides/atomic-sampling-data-types-0000001324971013) |
| 华为运动记录对象 | [developer.huawei.com: ActivityRecord](https://developer.huawei.com/consumer/cn/doc/HMSCore-References/activityrecord-0000001050091641) |
| 华为运动记录接口 | [developer.huawei.com: ActivityRecordsController](https://developer.huawei.com/consumer/cn/doc/HMSCore-References/activityrecordscontroller-0000001050091295) |

项目内整理的字段对照见 `references/field-reference.md`。官方文档为 SPA 页面，部分内容需在浏览器中展开目录查看；链接路径可能调整。

## 接口变化与兼容性探测

导入页及其使用的服务端接口不是公开承诺稳定的 API。为降低文档结论过期的风险，本仓库提供 `scripts/check_api_compat.py`：在执行迁移前**主动询问使用者是否进行接口兼容性探测，并说明各方式的步骤与影响**；未经使用者确认，不执行会向账号写入记录的探测。

最近一次只读状态核验（时间、页面文案原文、服务端字段结构、按类型的字段覆盖、写入语义）汇总在 `references/current-status.md`；三种探测方式与具体判据见 `references/api-compat-probe.md`。**执行顺序是先探测、再对照文档、最后导入。** 探测结果只能说明单次、单账号、单时间点的观察，不构成对接口稳定性的保证。

## 局限

- 工具链依赖华为网页导入页与其内部接口；该接口不是公开 API，路径、字段、限制与错误码可能变化。
- 不保证任何文件一定被接受或落库。导入页提示成功不等于服务端存在记录，需独立核验。
- 服务端对部分统计值按采样点重新计算；写入的汇总字段不一定被采用。
- 导入通道按运动类型落库的字段覆盖有限：本次观察中步行记录不保留步频/步幅统计，骑行记录保留速度 avg/max 但客户端通常不显示速度曲线，分段结构只在跑步类型上出现。向 FIT 增加字段不改变这些结果。
- 导入页原文写明，导入数据不计入运营统计、个人成就统计、周月年报统计与运动能力评估。
- 部分运动类型在 FIT 解析层被拒收；此类记录需由使用者在 App 内手动补录。
- 探针文件导入后即成为账号内的真实记录，仓库不提供删除能力，需使用者自行处理。
- 仅处理使用者自有账号、自有数据的本地转换，不提供凭据托管、代登录、批量注册或风控绕过。
- 输出用于数据迁移，不作为医疗、训练或体能评估依据。

更多边界见 `references/security-privacy.md`、`references/troubleshooting.md` 与 `references/operational-notes.md`。

## 隐私

仓库内 `assets/` 的示例数据为合成数据，不含真实健康记录、账号标识或凭据。运行过程中产生的导出文件、FIT、登录态与核验报告均保存在本地，不应提交到公开仓库；提交 issue 或日志前需自行检查轨迹、心率、账号与令牌。详见 `references/security-privacy.md`。

## 免责声明

本项目为非官方的第三方工具，与华为、小米、Garmin 无隶属、背书或支持关系。使用风险由使用者自行承担；详见 **[DISCLAIMER.md](DISCLAIMER.md)**。

## 致谢与许可

第三方项目、许可与出处见 [THANKS.md](THANKS.md)。本仓库代码以 MIT 许可发布，依赖与数据来源的许可各自独立。

## 目录

```
SKILL.md                            技能定义：边界、硬规则、流程与验收
README.md                           本文件
DISCLAIMER.md                       免责声明
THANKS.md                           第三方项目与许可
examples/end-to-end.md               端到端全程示例（合成数据，到手即用）
scripts/                            转换、编码、自检、导入、核验与兼容性询问脚本
references/current-status.md        最近一次实时只读核验状态（时间基准）
references/operational-notes.md     批量、幂等、编码、失败处理等操作要点
references/                        取数、输入格式、字段含义、平台限制、探测、核验、排查、隐私
assets/                             合成示例数据
skill-dependencies.json             依赖与降级路径
```
