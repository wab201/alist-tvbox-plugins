# 发布与部署状态

## 当前发布

| 项目 | 状态 |
| --- | --- |
| 仓库索引 | `spiders_v2.json` 已登记并启用 |
| 插件 ID | `douban_tmdb_follow_single` |
| 发布版本 | `63`（公开测试版） |
| 源码格式 | 明文 `.py` |
| AList-TVBox 最低兼容基线 | `1.42.0` |
| AList-TVBox 当前验证环境 | `1.44.0` |
| 源码文件 | `py/豆瓣TMDB追更单入口_v63.py` |
| 源码大小 | `589500` 字节 |
| 源码 SHA256 | `7AFF8689CA62E1F3CBC45FF1279C70BBF8EAB72E1262B60EC1840A9AA63D718B` |
| 自动化回归 | `251` 项通过（含 3 项真实 loopback HTTP 联调） |
| ATVP 合同 | direct-play / upstream-1.25-raw 通过 |
| 双运行时合同 | FongMi TV 5.6.0 官方 HEAD `1a19fee278fa2234da725d61a53bf59b69fe9127` 通过 |
| FongMi 分类合同 | TypeFragment、SiteApi、Chaquopy 与 Atvp 参数链通过 |
| 广域网 History | 当前订阅 HTTPS 入口已实测登录、读取、写入、跨 LAN 可见和删除清理通过 |
| 仓库部署 | 公开测试版 |
| 回退基线 | v57，源码 SHA256 `A992254BDC0A2AC4AFB32DD6A1C6A6ED5B78158848C539BAEC11356F0C68D077` |
| 容器部署方式 | 仅通过仓库导入拉取，不在仓库保存容器凭据 |

`公开测试版` 只表示仓库入口和源码可访问，不代表已部署到任何 AList-TVBox 容器。容器部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 执行。

## 2026-08-12 广域网实测结论

- 当前公网 HTTPS 订阅与插件 416 均可访问，公网登录返回成功。
- 匿名 History 请求仍会触发 AList-TVBox 1.44.0 用户编号转换错误；使用插件 EXT 中的 `USER`/`ADMIN` 账号登录后，公网与内网均读取到同一组 `99` 条 History。
- 从公网 HTTPS 写入临时记录后，公网和内网 HTTP 均能立即读取同一记录，证明反代完整转发 History 路由和 `Authorization` 请求头。
- AList-TVBox 1.44.0 的 `DELETE /history/{token}?key=...` 实测返回服务端错误；V61 严格核对 key 与记录 ID 后回退到认证管理删除接口，公网实测删除成功，最终记录数恢复为 `99`，没有遗留测试数据。
- 使用当前公网订阅实际下发的完整 EXT 对照运行 V60 与 V61，两版均能通过 HTTPS 冷启动登录、首次读取 `99` 条并完成空数组写入。因此 V60 客户端首次详情缺少进度不是 HTTP/HTTPS 反代失败，修复重点是 V61 的首次详情同步时序和客户端状态刷新。
- V61 本地真实 HTTP 联调覆盖 History 登录、上传、读取、服务端 key 删除失败后的认证管理接口回退，以及签名播放地址首次失活后重新 `/play` 获取新地址，3 项均通过。
- History 上传边界现在按 key 去重并只保留本机最近 `2048` 条；插件不会按此策略删除其他设备记录，云端总量仍由服务端管理。
- 播放线路切换状态已按作品、季集和 flag 识别；FongMi 真实多线路使用不同播放 ID 时仍会触发当前线路重签发，跨集播放不会误判为换源。
- FongMi 5.6.0 源码确认播放器失败后会优先切换详情已有的下一条 `vodFlags` 线路，并重新调用对应 `playerContent`；若详情只有单线路，则 Python 不会收到播放器底层错误回调。
- 2026-08-12 使用 FongMi 5.6.1 ARM64 APK 和公网订阅实测确认：V60 线上版本的 History 失败根因是后台路径调用 `_HistoryCoordinator.sync_once`，而该委托方法缺失；V61 已补齐委托并增加回归测试。此次实测的 `检测通讯` 已成功读取云端 `99` 条记录，证明 HTTPS 订阅、登录和 History GET 链路正常。
