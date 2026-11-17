# 致谢

这个工具链能跑通，绝大部分功劳属于下面这些项目和人。按「用在哪一步」分类列出，并标注许可。

## 一、运行时依赖（本仓库直接调用）

### Garmin FIT SDK
- 仓库：<https://github.com/garmin/fit-python-sdk>
- 许可：Garmin FIT Protocol License Agreement（**不是** OSI 开源许可；允许用于开发与 FIT 协议兼容的产品）
- 用途：`scripts/fit_encode.py` 生成 FIT、`scripts/fit_audit.py` 解码回读
- 说明：本项目通过 `pip install garmin-fit-sdk` 依赖它，**不内嵌、不修改**其代码。FIT 协议本身归 Garmin 所有。

### Playwright
- 仓库：<https://github.com/microsoft/playwright-python>
- 许可：Apache-2.0
- 用途：`scripts/hw_common.py`、`huawei_upload.py`、`huawei_verify.py` 驱动浏览器完成导入与服务端核验

## 二、数据获取阶段用过（本仓库不含其代码，由使用者自行运行）

### mi_fitness_data_bridge —— 小米运动健康数据导出
- 仓库：<https://github.com/shkyyy18/mi_fitness_data_bridge>
- 许可：**AGPL-3.0-only**（2026-08-03 之前的版本为 MIT；其上游 `kubulashvili/mi-fitness-mcp`、`binglua/mi-fitness-mcp-cn` 为 MIT，详见该仓库 LICENSE 中的 NOTICE）
- 用途：导出小米运动健康的逐点数据（心率、步频、配速、GPS），是本项目最初的数据来源
- 边界说明：AGPL 具有传染性。本项目**只消费它导出的 JSON 文件**，没有复制、修改或链接其代码，因此本仓库仍以 MIT 发布。若你要修改并分发那个桥，请遵守 AGPL。

### Mi-Fitness-Sync
- 仓库：<https://github.com/kevinkwee/Mi-Fitness-Sync>
- 许可：MIT
- 用途：备选导出方案，用于交叉核验小米数据的完整性

### running_page —— 悦跑圈导出
- 仓库：<https://github.com/yihong0618/running_page>
- 许可：MIT
- 用途：其 `run_page/joyrun_sync.py` 提供了悦跑圈的接口路径与签名实现，数据获取阶段据此导出 GPX/TCX。该脚本**未包含**在本仓库中。

### fit-tool
- 包：<https://pypi.org/project/fit-tool/>（fork 自 <https://bitbucket.org/stagescycling/python_fit_tool>）
- 许可：BSD-3-Clause
- 用途：开发期交叉核对 FIT 字段枚举、缩放与偏移；最终实现改用 Garmin 官方 SDK

## 三、调研阶段参考（未使用其代码）

- **fitconverter**：了解过其字段映射思路。因需要把平台账号或短信验证码交给第三方服务器，最终没有采用。
- **华为运动健康服务官方文档**：字段与数据类型定义以官方页面为准，链接见 `references/field-reference.md`。
- **华为运动健康导入页**：页面限制（批次上限、单文件体积、可导入类型、分段行为）来自特定时间点的页面观察，不是官方承诺；结论可能过期，仓库提供 `scripts/make_probe.py` 与 `scripts/check_api_compat.py` 供复核。

## 四、规范来源

- Garmin FIT Protocol 与 FIT Profile（字段号、缩放、偏移、子字段规则），随 `garmin-fit-sdk` 分发
- GPX 1.1 / Garmin TrackPointExtension v1（示例数据与转换脚本使用）
- TCX（Training Center XML）结构定义

## 五、如果漏了谁

如果你认为某段实现源自你的项目而这里没有列出，请提 issue 或 PR，会补上并注明出处。
