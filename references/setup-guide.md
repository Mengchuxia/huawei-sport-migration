# 依赖配置指南

按需配置：`check_environment.py` 报 ready 就跳过本页，只处理它标出的缺失项。

## python

- 用途：运行全部脚本
- 支持版本：3.10 及以上
- 官方主页：https://www.python.org/
- 官方文档：https://docs.python.org/3/
- 配置步骤：
  1. 安装 Python 3.10+，Windows 安装时勾选「Add python.exe to PATH」
  2. 终端执行 `python --version` 确认版本
- 验证方式：`python scripts/check_environment.py`，`python` 一项显示 ✓
- 凭据存储：不需要
- 核验日期：2026-11-15

## garmin-fit-sdk

- 用途：编码与解码 FIT 文件（官方实现，符合 FIT Profile）
- 支持版本：1.2 及以上
- 官方主页：https://pypi.org/project/garmin-fit-sdk/
- 官方文档：https://github.com/garmin/fit-python-sdk
- 配置步骤：
  1. `pip install garmin-fit-sdk`
  2. `python -c "import garmin_fit_sdk; print('ok')"`
- 验证方式：`python scripts/check_environment.py`，`garmin-fit-sdk` 一项显示 ✓
- 凭据存储：不需要
- 过期与故障：包本身不会过期；若与新版 Python 不兼容，升级到最新版
- 轮换和撤销：卸载用 `pip uninstall garmin-fit-sdk`
- 核验日期：2026-11-15

## playwright

- 用途：自动完成网页导入与结果核验（可选，缺省时可手动导入）
- 支持版本：1.40 及以上
- 官方主页：https://playwright.dev/python/
- 官方文档：https://playwright.dev/python/docs/intro
- 下载地址：https://playwright.dev/python/docs/browsers
- 配置步骤：
  1. `pip install playwright`
  2. `playwright install chromium`（本机已有 Edge/Chrome 时可跳过）
  3. `python scripts/check_environment.py` 确认 browser 一项有值（系统浏览器或 Playwright 自带 Chromium 都算）
- 验证方式：`python scripts/check_environment.py`，`playwright` 与 `browser` 显示 ✓
- 凭据存储：不需要
- 过期与故障：浏览器内核升级后若报协议错误，重跑 `playwright install chromium`
- 轮换和撤销：`pip uninstall playwright`
- 核验日期：2026-11-15

## huawei-account

- 用途：把生成的文件导入你自己的华为运动健康账号，并读取服务端记录做核验
- 官方主页：https://health.huawei.com/
- 官方文档：https://consumer.huawei.com/cn/support/
- 导入页：https://h5hosting.dbankcdn.com/cch5/healthkit/data-import/pages/oauth-callback.html
- 登录网址：https://id1.cloud.huawei.com/CAS/portal/loginAuth.html
- 登录后路径：华为运动健康导入页 →「运动数据导入」标签 → 选择 FIT → 选择文件 → 导入数据
- 权限与 scope：仅健康数据写入（页面自身申请的权限），不需要额外授权
- 配置步骤：
  1. 运行 `python scripts/huawei_upload.py --login-only`，脚本会打开浏览器并停在登录页
  2. 在弹出的窗口里用手机「设置 → 华为账号 → 扫一扫」扫码，或短信验证码登录
  3. 看到「登录态已保存」后关闭窗口即可，不需要先生成 FIT 文件
- 凭据存储：不存密码与验证码；登录态由浏览器保存在 `~/.huawei-sport-migration/browser-profile/`
- 验证方式：`huawei_upload.py --login-only` 打印「登录态已保存」；或 `huawei_verify.py` 能读出服务端记录条数
- 过期处理：登录态过期时脚本会重新打开登录页，再扫一次即可
- 轮换和撤销：删除 `~/.huawei-sport-migration/browser-profile/` 即彻底退出；
  需要远端下线时在华为账号中心「登录设备管理」里移除设备
- 账号地区：仅中国大陆账号
- 核验日期：2026-11-15
