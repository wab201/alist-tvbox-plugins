# 发布与部署状态

## 当前发布

| 项目 | 状态 |
| --- | --- |
| 仓库索引 | `spiders_v2.json` 已登记并启用 |
| 插件 ID | `douban_tmdb_follow_single` |
| 发布版本 | `70`（公开测试版） |
| 源码格式 | 明文 `.py` |
| AList-TVBox 最低兼容基线 | `1.42.0` |
| V70 AList-TVBox 实测环境 | `1.44.0` |
| V80 当前上游合同目标 | `1.48.0`（继承 `/api/playback/*`、网盘路径与多级续播坐标；新增直播弹幕/快手修复源码合同） |
| 源码文件 | `py/豆瓣TMDB追更单入口.py`（固定入口，历史版本由 Git 提交/标签回退） |
| 源码大小 | `616699` 字节 |
| 源码 SHA256 | `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4` |
| 自动化回归 | `285` 项通过（含 V70 残缺绑定继续搜索完整线路回归） |
| ATVP 合同 | direct-play / upstream-1.25-raw 通过 |
| 双运行时合同 | FongMi TV 5.6.1 模拟器运行链与 direct-PY 门禁通过 |
| FongMi 分类合同 | TypeFragment、SiteApi、Chaquopy 与 Atvp 参数链通过 |
| 广域网 History | 当前订阅 HTTPS 入口已实测登录、读取、写入、跨 LAN 可见和删除清理通过 |
| 仓库部署 | V70 待正式仓库导入与 Android 虚拟机联调；历史版本通过 Git 提交或标签回退 |
| V70 发布故障回退点 | v57，源码 SHA256 `A992254BDC0A2AC4AFB32DD6A1C6A6ED5B78158848C539BAEC11356F0C68D077` |
| 容器部署方式 | 仅通过仓库导入拉取，不在仓库保存容器凭据 |

`公开测试版` 只表示仓库入口和源码可访问，不代表已部署到任何 AList-TVBox 容器。容器部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 执行。

## V80 开发状态

| 项目 | 状态 |
| --- | --- |
| 开发分支 | `v80-dev` |
| P1 状态 | 2026-08-13 已验收完成 |
| P2-1 状态 | 2026-08-13 已验收完成：四模型、稳定序列化、四模式纯影子映射 |
| P2-2 状态 | 2026-08-13 已验收完成：固定 Schema 检测、行分类与未知容器拒绝 |
| P2-3 状态 | 2026-08-13 已验收完成：标题、年份、季号纯归一化与 V70 等值合同 |
| P2-4 状态 | 2026-08-13 已验收完成：标题、年份、季号三态匹配判定与 V70 等值合同 |
| P2-5 状态 | 2026-08-13 已验收完成：V70 装饰标题准入、别名字符串语义与 helper 返回值等值 |
| P2-6 状态 | 2026-08-13 已验收完成：冻结 V70 单标题评分 Policy、绑定优先级与可解释分数组成 |
| P2-7 状态 | 2026-08-13 已验收完成：V70 单资源 row 标题收集、work_title 覆盖、前 32 条 links 与最高分聚合 |
| P2-8 状态 | 2026-08-13 已验收完成：预计算分数/preference 的稳定排序、provider/mode 双层轮询与完整返回 |
| P2-9 状态 | 2026-08-13 已验收完成：V70 preference 七元组、原生 dict 边界、work_title 三态与 tuple 字典序 |
| P2-10 状态 | 2026-08-13 已验收完成：V70 两行纯合并、空字段补全、资源 ID/时间戳选择与 validated 失效 |
| P2-11 状态 | 2026-08-13 已验收完成：V70 row identity、有限解码、URL/磁力/ED2K 规范化与固定字段优先级 |
| P2-12 状态 | 2026-08-13 已验收完成：V70 候选列表 identity 去重、空 identity 保留、稳定位置与顺序两行合并 |
| P2-13 状态 | 2026-08-13 已验收完成：V70 合并后 score/preference/provider 阶段顺序与 P2-8 公平排序接缝 |
| P2-14 状态 | 2026-08-13 已验收完成：纯、脱敏候选 shadow report 接缝；不接入两个 V70 调用点 |
| P2-15 状态 | 2026-08-13 已验收完成：默认关闭、稳定采样、预算准入、重复上限和即时回退策略 |
| P2-16 状态 | 2026-08-14 已验收完成：policy/report 纯组合、固定信封和调用点状态所有权边界 |
| P2-17 状态 | 2026-08-14 已验收完成：后台输入纯适配、脱敏代际采样键、独立预算和默认关闭边界 |
| P2-18 状态 | 2026-08-14 已验收完成：固定八模块 shadow 闭包的静态单文件 vendoring 证明 |
| P2-19 状态 | 2026-08-14 已验收完成：vendor 原字节追加到隔离 V80 单文件开发产物，不接运行时调用点 |
| P2 宏批次 A 状态 | 2026-08-14 已验收完成：默认关闭的后台 shadow 调用点、代际状态和独立零默认预算；不接管输出 |
| P2 宏批次 B-B1 状态 | 2026-08-14 已验收完成：四个固定 Provider Adapter、登记 Schema、V70 请求参数与现有归一化边界 |
| P2 宏批次 B-B2 状态 | 2026-08-14 已验收完成：缓存、最近成功、绑定、快速 Provider、补充 Provider 的纯分层顺序 |
| P2 宏批次 B-B3 状态 | 2026-08-14 已验收完成：注入本地候选与固定 Provider payload 的纯 shadow 分层批次 |
| P2 宏批次 B-B4 状态 | 2026-08-14 已验收完成：V70 原始候选行的 identity 分类与类型化分层适配 |
| P2 宏批次 B-B5 状态 | 2026-08-14 已验收完成：私有 helper 前缀收敛与固定十六模块 vendor closure |
| P2 宏批次 B-B6 状态 | 2026-08-14 已验收完成：默认关闭的分层搜索 shadow overlay、独立预算/代际与销毁清理 |
| P2 宏批次 C-C1 状态 | 2026-08-14 已验收完成：八项显式证据、固定失败顺序和最小 `admit/reason` 准入合同 |
| P2 宏批次 C-C2 状态 | 2026-08-14 已验收完成：阶段门禁内存证据聚合、准入 dry-run 和公开输出写入保护 |
| P2 宏批次 C-C3 状态 | 2026-08-14 已验收完成：V70 源码锁定与 V80 开发输出隔离验证、完整门禁硬化、实现树绑定与 P2 阶段封板 |
| P2 阶段状态 | 2026-08-14 已完成；未接管公开输出，未部署 V80 |
| P3 History 同步工作包 | 2026-08-14 已完成封板；不代表整个 P3 完成 |
| P3 History 上游差异 | `1.45.x` 移除旧 `/history/{token}` 服务端实现；V80 使用 `/api/playback/*`，旧容器只在 `404/405` 时受控回退 |
| P3 History 定向验证 | `46 passed`；AList-TVBox `1.45.1` 上游合同通过 |
| P3 History 隔离候选 | `714878` bytes；SHA256 `4F293BF5D62A1AC10A287B0608556C6C449FB46B98CE0F9826DF4EDBA9AC5B26` |
| P3 Reliability 工作包 | 2026-08-14 已完成实现并进入封板；只覆盖结构化失败分类、Provider HTTP/payload 异常和绝对 deadline 分配 |
| P3 Reliability 定向验证 | `259 passed / 7 skipped`；不预写完整阶段门禁结果 |
| P3 Reliability 隔离候选 | `724277` bytes；SHA256 `6D590868B80950923F44A793A515A351EC9CC8FABC631EF7DD6DE5ED860C4099` |
| P3 Reliability 明确未包含 | 端到端 TimeoutBudget、retry/backoff、Circuit Breaker、Bulkhead、Health、Chaos，以及 History/TMDB/通用网络接管 |
| P3 Retry/Backoff 工作包 | 2026-08-14 已完成实现并进入封板；复用现有 urllib3 adapter 为唯一传输重试所有者，Provider 只预留最坏 `0.8s` 退避，不新增应用层重试循环 |
| P3 Retry/Backoff 定向验证 | `278 passed / 7 skipped`；Macro A/B 各 `50000 equal / 0 different / 0 errors`；1.45.1 上游合同、ATVP direct-play、FongMi 双运行时和分类参数合同通过 |
| P3 Retry/Backoff 隔离候选 | `727368` bytes；SHA256 `3BF3D5C02A4ED67F48F852A78614528B123DE53D4C4B055D1FC588EF66C5A0AE` |
| P3 Retry/Backoff 明确未包含 | HTTP 状态重试、重定向策略、端到端硬 wall-clock cancellation、Circuit Breaker、Bulkhead、Health、Chaos，以及 History/TMDB/通用网络接管 |
| P3 Provider Reliability 工作包 | 2026-08-14 已完成实现、三路复审和封板；按 backend/mode 隔离 Circuit Breaker、Bulkhead 与有界 EWMA Health |
| P3 Provider Reliability 合同 | 连续 `3` 次瞬态失败打开 `30s`；半开单探针；每键容量 `2`；瞬态仅 timeout/DNS/TLS/transport/server/rate limit；结构化 `circuit_open`、`bulkhead_rejected` |
| P3 Provider Reliability 验证 | 窄测 `171 passed`；扩展定向 `304 passed / 7 skipped`；三路复审零问题；Macro A/B 均要求 `50000 equal / 0 different / 0 errors` |
| P3 Provider Reliability 隔离候选 | `738611` bytes；SHA256 `49106B27ED2F1824F9C9460464B200093BB243554EB4F023736FD28D7832AB76`；报告 `work/v80-stage-gate-1451-provider-reliability.json` |
| P3 Provider Reliability 明确未包含 | TMDB、History、通用网络、HTTP 状态重试、重定向、应用层 retry loop 或公开 V70 接管 |
| P3 History 事件队列工作包 | 2026-08-14 已完成实现、第二轮三路复审和封板；活动上限 `256`，批量溢出使用持久化 `deferred`，每轮最多 drain `8` 条 |
| P3 History 事件队列合同 | deferred 跨重启恢复；UID 与 `transition_pending` 隔离；delete/upsert 单调合并；重复批量不删除同水位 deferred；已有 deferred 身份可更新，新身份满队列明确拒绝 |
| P3 History 事件队列验证 | 专项 `31 passed`；P3 全域 `249 passed`；构建与阶段定向 `86 passed / 7 skipped`；第二轮三路复审 Critical/High/Medium 均为 `0` |
| P3 History 事件队列封板 | 完整门禁 `17/17 passed`；pytest `1207 passed / 7 skipped`；Macro A/B 各 `50000 equal / 0 different / 0 errors`；候选 `776229` bytes，SHA256 `9A3008A774FACE213EDC337E3B92CDBF088C4A79CB8961D04DD24F133A02C5C6` |
| P3 History 事件队列报告 | `work/v80-p3-1451-stage-gate-sealed-r2-20260814.json`；报告 SHA256 `151EEE6D0E2F9488AF66D0996040D220002513210F8116569478CD6EAE1B2580` |
| P3 Cache Health 工作包 | 2026-08-15 已完成实现、交错线程回归、集中复审和封板；只统一现有 cache stale/backoff 决策 |
| P3 Cache Health 合同 | 仅 `None` 为 miss；inclusive TTL 与 `allow_stale=False` 不变；stale 立即返回后台刷新；失败上限 `6`，退避 `1/2/4/8/16/32s` 受 `failure_ttl` 限制；旧代次不可提交 payload/health |
| P3 Cache Health 接管范围 | TMDB JSON cache、Douban JSON/text cache、Spider History 快照非阻塞刷新、通用后台 cache refresh；History 刷新失败按统一退避抑制，不影响播放 |
| P3 Cache Health 明确未包含 | Provider circuit/bulkhead、资源缓存、Filter History cache、History 持久事件队列、P4 安全范围 |
| P3 Cache Health 验证 | 聚焦 `47 passed`；构建与阶段定向 `91 passed / 7 skipped`；完整门禁 `17/17 passed`；pytest `1259 passed / 7 skipped`；Macro A/B 各 `50000 equal / 0 different / 0 errors` |
| P3 Cache Health 隔离候选 | `781140` bytes；SHA256 `50572D6304283CE39AA17AA2F25D1ED3EE9CEE88BB4DEB1C5B81D06EC6D79FBE`；报告 `work/v80-p3-1451-cache-health-stage-gate-sealed-20260815.json` |
| P3 Background Bulkhead 工作包 | 2026-08-15 已完成实现、合并回归、集中复审和封板；仅覆盖固定后台非阻塞准入 |
| P3 Background Bulkhead 合同 | `resource_completion=10`、`history=1`、`route_probe=5`；lane 独立计数；准入失败不等待、不排队、不新增 retry；代次重置隔离旧租约 |
| P3 Background Bulkhead 接管范围 | 绑定线路替换、入口资源预热、补充资源搜索；History 后台快照/同步和手工 probe/sync；后台线路预热 |
| P3 Background Bulkhead 明确未包含 | Provider bulkhead、前台搜索、History 持久事件队列、cache refresh、P4 安全范围、公开 V70 接管 |
| P3 Background Bulkhead 验证 | 聚焦 `44 passed`；受影响回归 `81 passed / 2 skipped`；包级 `163 passed / 7 skipped`；最终门禁固定要求 `17/17 passed`、pytest `1308 passed / 7 skipped`、Macro A/B 零差异及 1.45.1/ATVP/FongMi 合同通过 |
| P3 Background Bulkhead 隔离候选 | `786881` bytes；SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`；报告 `work/v80-p3-1451-background-bulkhead-stage-gate-sealed-20260815.json` |
| P3 Background Bulkhead 最终报告 | `work/v80-p3-1451-background-bulkhead-stage-gate-sealed-20260815.json`；`71535` bytes；SHA256 `01E67933BC238319ECD064FC1527D6BAF36896A86E8A3729B48A759F43E639C9` |
| P3 Chaos/Recovery 工作包 | 2026-08-15 已完成实现、包级回归和集中复审；使用虚拟时钟与完全本地故障夹具 |
| P3 Chaos/Recovery 场景 | TMDB 500/timeout stale、PanSou timeout、History 401/500、AList 502、DNS、IPv6、过期播放 URL、截断/超大 JSON、旧生命周期任务，`12/12 passed` |
| P3 Chaos/Recovery 恢复基线 | TMDB/History stale `1000ms`；Provider circuit `30000ms`；重认证、重签发、payload 与代次隔离 `0ms`；冷启动/热缓存 `250ms / 0ms` 仅为合成传输延迟 |
| P3 Chaos/Recovery 审计修正 | History 401 固定验证 `GET -> POST login -> GET`；History 401/500 使用 `1.45.1` `/api/playback/changes`；故障后验证实际 `followplay`；非预期异常不写入原文 |
| P3 Chaos/Recovery 验证 | 聚焦 `92 passed / 5 skipped`；P3 包级 `446 passed / 7 skipped`；105 个受管文件敏感信息扫描通过 |
| P3 Chaos/Recovery 边界 | 无真实网络、无真实 sleep、无生产写入、无部署；超大 JSON 只验证现有 stream 上限，统一响应安全属于 P4 |
| P3 Chaos/Recovery 隔离候选 | `786881` bytes；SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F` |
| P3 Chaos/Recovery 封板报告 | `work/v80-p3-1451-chaos-recovery-stage-gate-sealed-20260815.json` |
| P3 TimeoutBudget 工作包 | 2026-08-15 已完成实现、回归和阶段封板；覆盖端到端绝对 deadline 与生命周期硬取消 |
| P3 TimeoutBudget 合同 | 每个公开前台入口一个有限根 scope；子 deadline 只能收紧；timeout 与既有 retry/backoff 使用剩余预算；不新增 retry layer |
| P3 TimeoutBudget 生命周期 | `init()`/`destroy()` 取消旧 scope、阻止下一传输阶段、恰好一次关闭跟踪响应；旧代次不能影响新代次资源 |
| P3 TimeoutBudget 接管范围 | Douban、TMDB、Provider、播放、History/重认证和三个后台 lane；后台 lane 各自拥有独立有限 scope |
| P3 TimeoutBudget 明确未包含 | P4 URL/重定向/DNS/IP/响应/请求头/脱敏统一安全边界、真实网络性能、部署或公开 V70 接管 |
| P3 TimeoutBudget 验证 | 定向 `148 passed`；P3 全域 `379 passed / 986 deselected`；完整门禁 `18/18 passed`；pytest `1365 passed`；Golden、Macro A/B、Chaos 和外部合同全通过 |
| P3 TimeoutBudget 隔离候选 | `808647` bytes；SHA256 `9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9` |
| P3 TimeoutBudget 最终报告 | `work/v80-p3-1451-timeout-budget-stage-gate-sealed-20260815.json` |
| P3 阶段状态 | 九个隔离工作包已完成本地工程封板；未部署、未覆盖公开 V70 |
| P4-1 Security Policy 工作包 | 2026-08-15 已完成本地封板；只冻结纯网络区域、URL、重定向与请求头决策，不接管运行时调用 |
| P4-1 网络区域 | `trusted_backend`、`configured_internal`、`external_untrusted`；精确配置的内部后端可使用私网/回环/链路本地地址，外部目标全部解析地址必须为 global |
| P4-1 重定向合同 | 外部不能跳入内部区域；外部 HTTPS 不能降级为 HTTP；最多 5 跳；每跳重新提供解析地址证据；跨域固定白名单并移除凭据 |
| P4-1 明确未包含 | DNS 查询、网络请求、缓存、日志、retry、TimeoutBudget 分配、运行时拦截、JSON 深度/集合/字段统一限制、签名 URL 缓存策略 |
| P4-1 模块指纹 | `13919` bytes；SHA256 `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`；作为 P3 TimeoutBudget 输出后的叶模块 |
| P4-1 隔离候选 | `822566` bytes；SHA256 `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76` |
| P4-1 验证 | 策略专项 `42 passed`；完整门禁 `18/18 passed`；pytest `1412 passed`；Macro A/B 各 50,000 例零差异；Chaos `12/12`；112 个受管文件敏感扫描零发现 |
| P4-1 封板报告 | `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json` |
| P4-2 Route Security 工作包 | 2026-08-15 已完成媒体线路探测单调用族接入；复用现有 DNS、固定 IP、Host/SNI、重定向、TimeoutBudget 与 route executor |
| P4-2 安全合同 | 精确配置的 ATVP/History origin 可使用内部地址；外部目标全部地址必须为 global；逐跳重解析；外部不能跳入内部；HTTPS 不降级；跨域固定头白名单 |
| P4-2 明确未包含 | Provider、History、TMDB、通用 requests session、第二 retry/transport/DNS cache/executor/timeout owner，以及剩余响应/JSON/脱敏/签名 URL 策略 |
| P4-2 候选 | P4-1 输出 `822566 / A1C922...` 为固定输入；最终 `823561` bytes；SHA256 `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F` |
| P4-2 验证 | overlay `10 passed`；关键组合 `461 passed`；完整门禁目标 `18/18 passed`、pytest `1426 passed`、Macro A/B 零差异、Chaos `12/12` 与外部兼容合同通过 |
| P4-2 封板报告 | `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json` |
| P4-3 JSON Shape Policy | 2026-08-15 已完成合同收口；纯解析后结构合同，不读取响应、不解析 JSON、不接管运行时调用族 |
| P4-3 固定限制 | 容器深度 `64`；值节点 `131072`；单 list/dict `8192` 项；只接受精确 JSON 类型；拒绝 NaN/Infinity |
| P4-3 明确未包含 | 响应字节、字符串/字段长度、播放 ID/URL 长度、解析前内存限制，以及 Provider/History/TMDB/Douban/播放接入 |
| P4-3 模块指纹 | `2383` bytes；SHA256 `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`；逐字节追加在 P4-2 输出后 |
| P4-3 隔离候选 | `825944` bytes；SHA256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0` |
| P4-3 验证 | 策略专项 `12 passed`；当时 P4 专项 `64 passed`；完整合同由 P4-4 稳定门禁再次覆盖 |
| P4-3 封板证据 | 独立门禁期间共享树已进入 P4-4，不保留误标成功报告；使用 P4-4 最终报告作为包含性证据 |
| P4-4 TMDB JSON Shape | 只在 `_request_tmdb()` 成功 `200` 返回调用结构策略；保留既有非 200、解析、缓存、关闭和 TimeoutBudget 所有权 |
| P4-4 明确未包含 | 非 `200` payload shape validation、解析前响应字节、字符串/字段长度、Douban/Provider/History/播放调用族 |
| P4-4 overlay | 构建器 `7094` bytes；SHA256 `768E3E0F7FAF4B9E055AFADA4608C919302BF57F741F4C329EDFFA218A8171D5`；单一 `tmdb-json-shape` 替换 |
| P4-4 隔离候选 | P4-3 输出 `825944 / 8FB4EE...` 为固定输入；最终 `825969` bytes；SHA256 `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7` |
| P4-4 验证 | P4 专项 `74 passed`；P4-4 overlay 专项 `10 passed`；完整门禁 `18/18 passed`；pytest `1456 passed`；118 个受管文件敏感扫描零发现 |
| P4-4 封板报告 | `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json` |
| P4-5 TMDB Response Boundary | 同一 TMDB 调用族固定解析前 `2 MiB`、object key `1024` UTF-8 bytes、string value `128 KiB`；成功响应按 shape 后 field 顺序验证 |
| P4-5 所有权 | `_json_response()` 只增加可选有界模式；另外两个一参数调用不变；复用现有 reader/deadline，外层 `close_tracked()` 仍唯一关闭 |
| P4-5 非 200 | `401/403/429` 固定错误读取前优先；其他无效或超大 body 回退 `TMDB HTTP <status>`；有效 `status_message` 保留 |
| P4-5 明确未包含 | Douban、Provider、History、播放、通用 requests session、第二 retry/cache/transport/timeout/close owner |
| P4-5 策略模块 | `1735` bytes；SHA256 `C2D56B1432AB66163591953BA0ACD532A71BE0D963984EAF78C31F70DF3BD375`；P4-4 固定输入 `825969 / 4746D9...` |
| P4-5 隔离候选 | `829040` bytes；SHA256 `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4` |
| P4-5 验证 | P4 专项 `103 passed`；pytest `1493 passed`；122 个受管文件敏感扫描零发现；Macro A/B 各 `50000/0/0`；Chaos `12/12` |
| P4-5 封板报告 | `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json` |
| P4-6 Diagnostic Redaction | `_short_error()` 与 `_diagnostic_event()` 的名称、级别、错误、trace、字段键和值统一经过纯 policy；stage 报告复用同一有界核心 |
| P4-6 边界 | 运行时输出 `4096`；最多 `32` 个显式 secret、单项 `4096`；覆盖 Header、assignment、userinfo、signed query、编码结构、播放路径和结构化容器 |
| P4-6 隔离候选 | P4-5 `829040 / 60B083...` 为固定输入；policy `9503 / 4A05F091...`；最终 `837931 / AF00837D...` |
| P4-6 验证 | 高相关 `252 passed`；P4 合并 `172 passed`；完整 pytest `1602 passed`；三轮审计的可复现高风险项已关闭 |
| P4-6 封板报告 | `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json` |
| P4-7 Douban JSON Response Boundary | 只接管 `_DoubanClient.request_json` 与 `_v80_action_unbounded` 想看 POST；复用现有 bounded reader、shape policy、deadline 与 `close_tracked()` |
| P4-7 响应上限证据 | 8 个无凭据 fixture；最大规范样本 `561` bytes，50 条保守投影 `28050` bytes；固定 `512 KiB`，余量约 `18.69x` |
| P4-7 顺序与所有权 | 非 `200` HTTP 和登录/动作消息顺序保持；cache/stale/backoff、session、retry、TimeoutBudget 与 response-close owner 不变 |
| P4-7 明确未包含 | Douban HTML、Provider、History、播放、redirect、signed URL cache、P5、第二 parser/reader/retry/cache/timeout/close owner |
| P4-7 隔离候选 | P4-6 `837931 / AF00837D...` 为固定输入；policy `251 / 69C7AEF6...`；最终 `839093 / B1F980E7...` |
| P4-7 封板验证 | AList-TVBox `1.46.1` 正式门禁 `18/18 passed`；完整 pytest `1667 passed`；Macro A/B 各 `50000 equal / 0 different / 0 errors`；Chaos `12/12` |
| P4-7 封板报告 | `work/v80-p4-7-alist-tvbox-1461-stage-gate-sealed-r2-20260816.json`；候选 `839093 / B1F980E7...` |
| AList-TVBox 1.46.1 源码证据 | base/head `9cd22bb... -> 8d601fd...`；精确 16 文件差异；34 项项目合同和 58 项上游 Maven 测试通过 |
| AList-TVBox 1.46.1 语义边界 | Python History 只证明新增 drive/navigation 字段的 wire forward compatibility；实际多级恢复 owner 尚待运行时证据 |
| P4-8 真实证据 | 2026-08-16 一次授权低频无重定向观测：`200 text/html; utf-8`，解压 `57197` bytes，SHA256 `AA28F457...`，`15/15` 有效完整页；未保存正文、URL、账号标识或标题 |
| P4-8 响应上限 | Top250 `64547`、wishlist `57197`、最大 parser 投影 `12258`；公式选择 `selected_bytes=262144`，不复制 TMDB `2 MiB` 或 Douban JSON `512 KiB` |
| P4-8 封板状态 | `_DoubanClient.request_text` 单 owner；候选 `840543 / 749F16F3...`；完整门禁 `18/18 passed`、pytest `1680 passed`、145 文件实现树稳定 |
| P4 阶段状态 | P4-1 至 P4-8 全部本地封板；最终报告 `work/v80-p4-8-douban-html-response-boundary-stage-gate-final-r2-20260816.json` |
| P5-1 Observability Policy | 纯 Schema/Error Code 目录；事件/快照 Schema `v80-diagnostic-event/1`、`v80-diagnostics-snapshot/1`；快照 `256`、文本 `512`；覆盖 16 个 P3 failure kind |
| P5-1 边界 | 只冻结 core/context/measurement 字段、level/stage 枚举和严格 Error Code lookup；不接运行时、不改公开返回或 play ID，不新增网络/I/O/时钟 owner |
| P5-1 隔离候选 | P4-8 `840543 / 749F16F3...` 为固定输入；policy `2138 / FDFA66B6...`；最终 `842681 / 19A5FFA6...` |
| P5-1 封板验证 | policy/build `42 passed`；stage-gate 构建链 `7 passed`；最终门禁 `18/18 passed`、pytest `1711 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `146/0`；稳定实现树 `148 / CEE3DFBA...`；报告 `work/v80-p5-1-observability-policy-stage-gate-final-r2-20260816.json` |
| P5-2 运行时关联 | `_diagnostic_event()`/P4 `_short_error()`/P3 TimeoutBudget 继续分别拥有事件、脱敏和 operation；顶层 scope 分配唯一 request/trace，嵌套 scope 继承根 trace，失效生命周期省略关联上下文 |
| P5-2 字段边界 | Schema、stage、request/trace 和 Error Code 为保留字段；耗时只接受有限非负数并规范为整数 `elapsed_ms`；不生成 Diagnostics Snapshot，不新增网络/I/O/时钟、缓存、重试或第二套日志框架 |
| P5-2 隔离候选 | P5-1 `842681 / 19A5FFA6...` 为固定输入；6 个固定 insertion；最终 `848247 / 510D4CFE...AB873` |
| P5-2 定向验证 | overlay `29 passed`；构建与 stage-gate 关键链 `26 passed`；三路审计的保留字段覆盖、对象地址复用、陈旧线程栈、耗时类型和文档优先级问题已关闭 |
| P5-2 完整门禁 | `18/18 passed`；pytest `1764 passed`；Macro A/B 各 `50000/0/0`；Chaos `12/12`；敏感扫描 `149/0`；`admit=true`；无生产写入或部署 |
| P5-2 封板报告 | 最终受管文档 closure 为 `work/v80-p5-2-runtime-correlation-closure-final-20260816.json`；旧报告保持只读，DAG 只重跑文档输入或依赖证据变化的分支 |
| P5-3 诊断快照覆盖层 | 复用唯一 `_diagnostic_snapshot()` owner；固定 `schema/count/events`、`1..256` 上限、旧到新顺序和脱离副本；不新增端点、持久化、时钟、buffer、二次脱敏、缓存、线程或日志 |
| P5-3 审计修复 | P5-2 event owner 改为返回 `dict(payload)`，阻断 P4 入站脱敏后的回写污染；resume 必须同时提供受信来源 SHA256，未验证报告不得复用；两轮审计无剩余 High/Medium |
| P5-3 隔离候选 | 历史 P5-2 封板仍为 `848247 / 510D4CFE...`；P5-3 加固中间态 `848253 / 5B9C10F2...964C`；最终 `848431 / 30EBACE8...A409` |
| P5-3 定向验证 | P5-2 `30 passed`；P5-3 `9 passed`；构建/防篡改链 `10 passed`；指纹消费者 `2 passed`；resume pin 及参数边界回归通过 |
| P5-3 完整门禁 | `18/18 passed`；`18 executed / 0 reused`；pytest `1784 passed`；Macro A/B 各 `50000/0/0`；Chaos `12/12`；敏感扫描 `152/0`；稳定实现树 `154 / 221363D7...CC25`；`admit=true`；耗时 `795.351s` |
| P5-3 封板报告 | 完整证据 `work/v80-p5-3-diagnostics-snapshot-closure-20260816.json`；最终受管文档 closure `work/v80-p5-3-diagnostics-snapshot-closure-final-20260816.json`；无生产写入或部署 |
| P5-5 续跑修复 | requirements 候选与 dual-runtime verifier 统一使用 `exists()`；所有存在候选入指纹，目录/读取错误与零候选 fail-closed；失败传播到 admission/V70 lock |
| P5-5 诊断 closure | `work/v80-p5-5-upstream-1471-closure-final-20260816.json` 为修复前只读失败证据：`15/18 passed`、pytest `1801 passed`；不得作为绿色封板 |
| AList-TVBox 1.48.0 源码证据 | `1.47.1 -> 1.48.0` 为 7 commits / 34 files；关键 ATVP/History/Playback blobs 不变；新叶合同 `24/24` |
| AList-TVBox 1.48.0 合同报告 | `work/v80-upstream-1480-source-contract-20260816.json`；`9144` bytes；SHA256 `BA37264DE2FDEFD13A1F13E2B221EC69982561151F10DBE1B149CF04F10D4E83` |
| P5-5 聚焦验证 | 四代 verifier 单测 `25 passed`；受影响 stage 单测 `4 passed`；1.48.0 叶合同 `24/24` |
| P5-5 完整 baseline | `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json`；`18/18 passed`；`18 executed / 0 reused`；pytest `1811 passed`；Macro A/B 各 `50000/0/0`；Chaos `12/12`；敏感扫描 `158/0`；稳定树 `160 / FE835719...149C`；`admit=true`；`824.449s` |
| P5-5 baseline pin | `185563` bytes；SHA256 `14AA4142678A71B0B64B1B9F86EE2BA6A6C9666AC1942997172B8A762476FFFD`；无生产写入或部署 |
| P5-5A 中文别名 | 重复生命周期静止态覆盖层 |
| P5-5A 候选 | `848540` bytes；SHA256 `A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；冻结 V70 与 P5-3 输入不变 |
| P5-5A 生命周期证据 | `work/v80-p5-lifecycle-stability-r7-20260817.json`；`32/32 passed`；SHA256 `E55CFC0FE64CB9597944447CFBDB51F705A62A6A00BB0160AABFEC4C1A2E2FF6` |
| P5-5A 验证 | 聚焦 `58 passed`；stage 定向 `21 passed`；敏感扫描 `0 findings`；安全/规格审计无阻断项 |
| P5-5A 首次完整报告 | `work/v80-p5-5a-lifecycle-stability-fingerprinted-baseline-20260817.json` 为只读失败证据；Macro A 仍固定 P5-3 最终指纹，pytest `1873` 项仅 2 项同源失败，非生命周期实现失败 |
| P5-5A 成功 closure | `work/v80-p5-5a-lifecycle-stability-resume-closure-r2-20260817.json`；`18/18 passed`；`8 executed / 10 reused`；pytest `1873 passed`；稳定树 `163 / 9CFDD9...B849B`；SHA256 `62A3F2F1755214E4EFC1895056BA46B3E6A96F1FEB044ECBF292B8372E70B117` |
| P5-5A 边界 | 仅绑定当前 provenance-bound candidate；runner 不是通用 Python sandbox；无生产写入或部署，不覆盖性能、并发、长稳、真实网络或实机 |
| P5-5B 中文别名 | 冷/热缓存性能基线 |
| P5-5B 候选 | 复用 `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；runtime、overlay、manifest、18 步 gate 与公开 V70 均未修改 |
| P5-5B 正式报告 | `work/v80-p5-cache-performance-r1-20260817.json`；schema `v80-p5-cache-performance/2`；`96/96 passed`；SHA256 `63CEA0A99F2114385896D216166681C8C964328E86E5D848A1BEC661E03C8379` |
| P5-5B 场景 | `cold_miss`、`fresh_hot_hit`、`stale_background_refresh` 各 `32/32`；真实 `Spider.v80_cache_load`；stale callback 受控释放 |
| P5-5B 隔离 | requests/socket、credential、`setCache` 持久化、真实 `Thread.start` 与 candidate sleep 尝试均为 `0`；host timing 只记录、不准入 |
| P5-5B 实现证据 | runner `560E80534C14FA056AB56CA553581367DA4319D37A8949DF659AF7C55D2A4BEF`；test `D838CBE50C75F1C4EEFE34021D798843DC879B1E19B520DC3849DB5346BE6B9E`；最终三路审计零 Critical/High/Medium |
| P5-5B stage closure | `work/v80-p5-5b-cache-performance-closure-r1-20260817.json`；`18/18 passed`；`7 executed / 11 reused`；pytest `1916 passed`；稳定树 `165 / 92BE65...ACA3`；`1299.442s`；`admit=true` |
| P5-5B 边界 | 仅证明合成 cache owner 路径；不覆盖真实网络、并发搜索/播放/History、长时间运行、服务器、MuMu 或实机；无生产写入或部署 |
| P5-5C 中文别名 | 长时间运行资源增长基线 |
| P5-5C 候选 | 复用 `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；runtime、overlay、manifest、gate 与公开 V70 均未修改 |
| P5-5C 正式报告 | `work/v80-p5-long-run-resource-growth-r4-20260817.json`；schema `v80-p5-long-run-resource-growth/2`；`32/32 passed`；SHA256 `9BC19054029595EC6647C2C026C98DE04E71A2D14C6466C6231ABE98921B507D` |
| P5-5C 工作量 | 单 Spider、一次 init/destroy、同 generation；`256` warm-up + `32 x 128` 测量，共 `4352` 次；cache calls `8704`、loader calls `4352` |
| P5-5C 资源证据 | candidate trace `161344 -> 173808` bytes、delta `12464`，仅观察不准入；网络、凭据、真实线程和生产写入 `0`；destroy 后 Session/task/timeout/reference/weakref 全清零 |
| P5-5C 实现证据 | runner `C59BF99D5C0AFF38C32769BC23BF989FA49ADE5161FC9768279F9B7DCA7337A5`；test `7A7B3D5CB8EB3775A69CBA0E6E0A9441D6E408242E63A71D0F7BC3BC58DD12E2`；聚焦 `50 passed`；四类审计缺口已关闭 |
| P5-5C 超时证据 | closure r1 SHA256 `EEC631A06A4E258F6E89EE063A723DE263C815E3CE2C96B771C2263783C9C34D`；pytest 在 `1800s`、约 `90%` 超时，非测试断言失败；只读保留 |
| P5-5C 成功 closure | `work/v80-p5-5c-long-run-resource-growth-closure-r2-20260817.json`；`18/18 passed`；`6 executed / 12 reused`；pytest `1966 passed`；稳定树 `167 / C7CE53...B6A026`；`2084.708s`；SHA256 `7977DDC3FC4EB0B9136A6B419BDDE136E703EF549365F0FAFC601EA76A3C76E7` |
| P5-5C 边界 | 仅证明顺序、受管、operation-count 长运行路径；不覆盖真实网络、并发搜索/播放/History、wall-clock endurance、服务器、MuMu 或实机；无生产写入或部署 |
| P5-5D 中文别名 | 搜索调用族并发与隔离基线 |
| P5-5D overlay 中文别名 | 搜索并发所有权覆盖层 |
| P5-5D 候选 | `854833` bytes；SHA256 `3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766`；P5-5A `848540 / A14571...5280` 保持为精确输入合同 |
| P5-5D 正式专项报告 | `work/v80-p5-search-concurrency-runtime-owner-final-r3-20260817.json`；schema `v80-p5-search-concurrency/3`；`7/7 passed`；SHA256 `A26D93477EF9E7798EBE023F2ECE110E10C32D6E862640F609FC21C9999CA0EE` |
| P5-5D 场景 | 前台容量、排队取消、job owner、旧代写回、响应单次关闭、资源补全舱壁隔离、live init/destroy 竞争 |
| P5-5D 清理证据 | Session `18/18` 单次关闭、executor `6/6` 清理；live init 六 executor/四 slot 换代；job/refresh/reference/bulkhead/timeout 全部归零 |
| P5-5D 验证 | runtime ownership `43 passed`；共享播放边界 `6 passed`；runner `15 passed`；stage-gate 单测 `242 passed`；三路复审 `findings=0` |
| P5-5D 首次完整 closure | `work/v80-p5-5d-search-concurrency-runtime-owner-closure-r1-20260817.json`；只读失败证据；暴露 9 个旧测试/runner owner 假设和错误沿用 `1.46.1` upstream 根，非生产并发实现失败 |
| P5-5D 成功 closure | `work/v80-p5-5d-search-concurrency-runtime-owner-resume-closure-r2-20260817.json`；`18/18 passed`；`8 executed / 10 reused`；pytest `2044 passed`；稳定树 `171 / D24ECF...8050`；敏感扫描 `165/0`；`admit=true` |
| P5-5D 边界 | DNS/media 仅作为搜索验证与播放探测共享依赖迁移 owner/lifecycle，播放算法保持不变；不覆盖完整播放/History 并发、真实网络、服务器、MuMu、FongMi 或实机；无生产写入或部署 |
| P5-5E 中文别名 | 播放调用族并发与隔离基线 |
| P5-5E overlay 中文别名 | 播放并发所有权覆盖层 |
| P5-5E 候选 | `857088` bytes；SHA256 `3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F`；P5-5D `854833 / 3C734E...9766` 保持为精确输入合同 |
| P5-5E 正式专项报告 | `work/v80-p5-playback-concurrency-r2-20260817.json`；schema `v80-p5-playback-concurrency/1`；`8/8 passed`；SHA256 `ABFB274DD4C98C282FDBB13F8329DF32BC1AA58DE77AA3C5CB302904EADC36E0` |
| P5-5E 场景 | 并发 player 隔离、旧 ATVP session 隔离、response/connection 单次关闭、取消后 slot 恢复、前后台隔离、live-init 代次围栏、陈旧副作用拒绝、destroy 清理 |
| P5-5E 证据加固 | 8 场景统一编译启动时已哈希候选字节；加载后恢复 `base/base.spider`；live-init 必须返回 `cancelled`，不得以异常空结果假绿 |
| P5-5E 验证 | 定向 `31 passed`；simplify/spec/security 最终复审均 `findings=0`；5 文件敏感扫描 `0` |
| P5-5E 技术 closure | `work/v80-p5-5e-playback-concurrency-closure-r1-20260817.json`；`18/18 passed`；pytest `2079 passed`；稳定树 `176 / F59312...BADA`；敏感扫描 `170/0`；`admit=true`；SHA256 `1E0D3ACB2B7C3041917E75E386C935BEE895AA47C10BDA09A5E06775AD5246AA` |
| P5-5E 边界 | 不覆盖 History 自身并发、真实网络、服务器、MuMu、FongMi 或实机；无生产写入或部署，不改变公开 V70 |
| P5-5F 中文别名 | History 调用族并发与隔离基线 |
| P5-5F overlay 中文别名 | History 并发所有权覆盖层 |
| P5-5F 候选 | `859732` bytes；SHA256 `B42B37C097AA989F0FE82EF380A71865A4FDA02F6606A295E120FD79DA610700`；P5-5E `857088 / 3DAB5769...299F` 保持为精确输入合同 |
| P5-5F 固定范围 | 13 个显式唯一替换；只收口 History job/background/manual/replacement owner、generation/category refresh 与持久化临界区；`_history_sync_lock` 和事件队列保持独立 |
| P5-5F 正式专项报告 | `work/v80-p5-history-concurrency-r3-20260817.json`；schema `v80-p5-history-concurrency/1`；`8/8 passed`；SHA256 `9B00F4A4FCDBF4556CC764D706E67BC73EA0E4A5A6660D595BBB043050BC5E9C` |
| P5-5F 验证 | overlay/runner `34 passed`；构建消费者 `4 passed`；stage selector `12 passed`；Chaos `7 passed`；旧消费者修复后 `53 passed`；三路复审 `findings=0` |
| P5-5F 失败恢复 | closure r1 在 pytest `2400s`、约 `75%` 超时；r2 暴露 53 个历史消费者未禁用更晚 History overlay；两份报告只读保留，均非生产 History 实现失败 |
| P5-5F 技术 closure | `work/v80-p5-5f-history-concurrency-closure-r3-20260817.json`；`18/18 passed`；`7 executed / 11 reused`；pytest `2117 passed`；稳定树 `180 / FE0ADBCF...7609`；SHA256 `77E0FF352DA25FAE2D76311584F70D1585CBB4E68274BD2CFCD505023F8D8648` |
| P5-5F 受管文档 closure | `work/v80-p5-5f-history-concurrency-doc-closure-r5-20260817.json`；`18/18 passed`；`6 executed / 12 reused`；稳定树 `180 / BFE1756C...E100`；报告 SHA256 `1FE5EC75B08AA6193F04B8B2AAE660D1628E73C12AEF02538C208C579345B509` |
| P5-5F 边界 | 不覆盖真实网络、服务器、MuMu、FongMi 或实机；无生产写入或部署，不改变公开 V70；未引入通用 executor/cache/retry/concurrency 框架 |
| 独立模块中文别名 | `46/46`：10 个 P1 有序源码切片、24 个 P2 Python 模块、12 个 P3/P4/P5 叶模块均在开发源码 README 建立稳定映射；别名不改变文件名、符号或运行时合同 |
| P4 重定向/响应边界收口 | 2026-08-18 已完成最小修复：Douban JSON/HTML、TMDB 与想看动作禁用自动重定向；`_resolve_user_id()` 仅解析同源 3xx `Location`，200 响应受 `256 KiB` 与总 deadline 约束；三个聚焦文件 `66 passed` |
| 当前 V80 候选 | `862377` bytes；SHA256 `C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D`；未修改公开 V70 或根索引 |
| 本批次最终 closure | 固定报告 `work/v80-p5-5f-redirect-boundary-alias-closure-r6-20260818.json`；必须保持 `18/18 passed`、实现树稳定、`production_writes=false`、`deployment_attempted=false` |
| 剩余发布路径 | 精确收敛 Git 候选提交、私有灰度、真实服务器/MuMu/FongMi 验证、回退演练、人工发布批准和生产晋升 |
| V70 锁定点 | 标签 `v70`，提交 `612617b35f08b98234c6e20c8137d8dea9035e97` |
| 开发构建合同 | `manifest + parts + single-file build` |
| P1 自动化 | `324 passed`；15 项 Golden 与 V70 全部一致 |
| P1 兼容门禁 | ATVP、双运行时、分类参数、AList-TVBox 1.44.0 源码合同通过 |
| P1 审计 | 简化、安全、规格审计完成；关键与高风险问题清零 |
| P2-1 自动化 | `21 passed` 窄测试；完整阶段门禁 `345 passed`；固定快照 SHA256 已冻结 |
| P2-1 审计 | 三轮限域审计；可复现兼容、不可变与假通过问题均已关闭 |
| P2-2 自动化 | `21 passed` 窄测试；完整阶段门禁 `372 passed`；15 项 Golden 零差异 |
| P2-2 门禁 | 固定三模块 DAG、34 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-2 审计 | 简化、加固和规格限域审计完成；三项可复现门禁假通过已关闭 |
| P2-3 自动化 | `43 passed` 窄测试；完整阶段门禁 `415 passed`；15 项 Golden 零差异 |
| P2-3 门禁 | 固定四模块 DAG、36 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-3 审计 | 简化、加固和规格限域审计完成；中文数字 helper 合同遗漏已关闭，剩余问题为零 |
| P2-4 自动化 | `24 passed` 窄测试；P2 定向 `137 passed`；完整阶段门禁 `439 passed`；15 项 Golden 零差异 |
| P2-4 门禁 | 固定五模块 DAG、38 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-4 审计 | 简化、加固和规格限域审计完成；冲突顺序、`"2.0"` 季号和空别名三项等值偏差已关闭，剩余问题为零 |
| P2-5 自动化 | `34 passed` 窄测试；P2 定向 `147 passed`；完整阶段门禁 `449 passed`；15 项 Golden 零差异 |
| P2-5 门禁 | 固定五模块 DAG、38 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-5 审计 | 简化、加固和规格限域审计完成；最长别名返回值、字符串换行别名两项等值偏差已关闭，剩余问题为零 |
| P2-6 自动化 | matching + scoring `60 passed`；P2 定向 `173 passed`；完整阶段门禁 `475 passed`；15 项 Golden 零差异 |
| P2-6 门禁 | 固定六模块 DAG、40 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-6 审计 | 简化、加固和规格限域审计完成；异常 aliases 与 bound 顺序偏差已关闭，最终剩余问题为零 |
| P2-7 自动化 | row scoring `17 passed`；P2-6 scoring + P2-7 row scoring `40 passed`；阶段门禁内全量测试 `492 passed`；15 项 Golden 零差异 |
| P2-7 门禁 | 固定七模块 DAG、42 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-7 差分 | 50,000 组 row 差分 `50000 equal / 0 different`；三类限域审计最终剩余问题为零 |
| P2-7 最终报告 | `work/v80-p2-7-stage-gate-final-rerun2.json`；SHA256 `3172D5D30BD087EA6BB88228E081ABE2FA5158D29C527CABE793EAB30E8453BE` |
| P2-8 自动化 | candidate ordering `11 passed`；P2 定向 `201 passed`；完整阶段门禁 `503 passed`；15 项 Golden 零差异 |
| P2-8 门禁 | 固定八模块 DAG、44 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-8 差分 | 50,000 组排序差分 `50000 equal / 0 different`；三类限域审计最终剩余问题为零 |
| P2-8 最终报告 | `work/v80-p2-8-stage-gate-final-docs.json`；报告 SHA256 记录在外部测试证据页 |
| P2-9 自动化 | candidate preference `35 passed`；P2 定向 `236 passed`；完整阶段门禁 `538 passed`；15 项 Golden 零差异 |
| P2-9 门禁 | 固定九模块 DAG、46 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-9 差分 | 50,000 组 preference 差分 `50000 equal / 0 different`；规格与加固审计零问题 |
| P2-9 审计 | 简化审计的 API 收缩建议因会分散冻结 row 合同而拒绝；最终无未解决的可复现缺陷 |
| P2-9 最终报告 | `work/v80-p2-9-stage-gate-final.json`；报告 SHA256 记录在外部测试证据页 |
| P2-10 自动化 | row merge `54 passed`；P2 定向 `290 passed`；完整阶段门禁 `592 passed`；15 项 Golden 零差异 |
| P2-10 门禁 | 固定十模块 DAG、48 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-10 差分 | 50,000 组合并差分 `50000 equal / 0 different`；浅复制和原生异常类型合同已覆盖 |
| P2-10 审计 | 简化、加固和规格三类限域审计最终均为零问题 |
| P2-10 最终报告 | `work/v80-p2-10-stage-gate-final.json`；报告 SHA256 记录在外部测试证据页 |
| P2-11 自动化 | row identity `39 passed`；全部 P2 模块 `301 passed`；完整阶段门禁 `631 passed`；15 项 Golden 零差异 |
| P2-11 门禁 | 固定十一模块 DAG、50 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-11 差分 | 50,000 组 identity 差分 `50000 equal / 0 different`；URL、magnet、ed2k、dict/UserDict 和深层编码边界已覆盖 |
| P2-11 审计 | 简化、加固和规格三类限域审计最终均为零问题；未调用的私有 rounds 接口建议已撤回 |
| P2-11 最终报告 | `work/v80-p2-11-stage-gate-final.json`；报告 SHA256 记录在外部测试证据页 |
| P2-12 自动化 | candidate merge `31 passed`；全部 P2 模块 `332 passed`；完整门禁收集 662 项，`660 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-12 门禁 | 固定十二模块 DAG、52 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-12 差分 | 50,000 组 candidate merge 差分 `50000 equal / 0 different`；输入顺序、浅复制、空 identity、稳定位置和三重重复已覆盖 |
| P2-12 审计 | 删除单用公开类型别名并补齐 identity 每行一次/跳过行零次/浅复制参数测试；简化、加固和规格审计最终剩余问题为零 |
| P2-12 最终报告 | `work/v80-p2-12-stage-gate-final.json`；报告 SHA256 记录在外部测试证据页 |
| P2-13 自动化 | candidate pipeline `21 passed`；全部 P2 模块 `353 passed`；完整门禁收集 683 项，`681 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-13 门禁 | 固定十三模块 DAG、54 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-13 差分 | 50,000 组 candidate pipeline 差分 `50000 equal / 0 different`；merge、score、mode/preference、provider 和双层轮询已覆盖 |
| P2-13 审计 | 简化审计删除重复对象 ID 顺序查找；加固与规格审计零问题，低项修正后窄测/P2 定向/50,000 差分均通过 |
| P2-13 最终报告 | `work/v80-p2-13-stage-gate-final.json`；SHA256 `2F542F569354FA0E8FB59538FF74D49E4B576ADAF2466FD3FD26957F6996738C` |
| P2-14 自动化 | candidate shadow `17 passed`；全部 P2 模块 `370 passed`；完整门禁收集 700 项，`698 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-14 门禁 | 固定十四模块 DAG、56 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-14 差分 | 固定 seed `8014` 的 50,000 组 shadow 差分 `50000 equal / 0 different / 0 errors` |
| P2-14 成本 | 20 行、2,000 次：legacy `5686.525 us/call`，legacy + shadow `11013.866 us/call`，新增 `5327.342 us/call`，比率 `1.937` |
| P2-14 审计 | 简化、加固和规格三类限域审计均为零问题；没有进入修复轮或追加防御层 |
| P2-14 最终报告 | `work/v80-p2-14-stage-gate-final.json`；SHA256 `4B7933C2B1FA9F6309C274C0B5E23E8A6BC8727E62E11CD16E239D7EBE53366C` |
| P2-15 自动化 | shadow policy `25 passed`；全部 P2 模块 `395 passed`；完整门禁收集 725 项，`723 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-15 门禁 | 固定十五模块 DAG、58 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-15 差分 | 固定 seed `8015` 的 50,000 组策略差分 `50000 equal / 0 different / 0 errors`；六种 reason 均实际命中 |
| P2-15 策略 | 仅 literal `True` 启用；`sample_every=1` 全量，N>1 稳定分桶；`already_sampled` 限制重复；预算低于估算成本跳过 |
| P2-15 审计 | 简化、加固和规格三类限域审计均为零问题；没有进入修复轮或追加运行时状态 |
| P2-15 最终报告 | `work/v80-p2-15-stage-gate-final.json`；报告 SHA256 在最终门禁后计算 |
| P2-16 自动化 | shadow composition `12 passed`；全部 P2 模块 `407 passed`；完整门禁收集 737 项，`735 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-16 门禁 | 固定十六模块 DAG、60 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-16 差分 | 固定 seed `8016` 的 50,000 组组合差分 `50000 equal / 0 different / 0 errors`；六种 reason 和三种 report 状态均实际命中 |
| P2-16 所有权 | 采样键、独立 shadow 预算和 `already_sampled` 均由未来后台调用点持有；组合层不派生、不扣减、不持久化 |
| P2-16 审计 | 简化、加固和规格三类限域审计均为零问题；没有进入修复轮或追加防御层 |
| P2-16 最终报告 | `work/v80-p2-16-stage-gate-final.json`；报告 SHA256 在最终门禁后计算 |
| P2-17 自动化 | shadow background adapter `29 passed`；全部 P2 模块 `436 passed`；完整门禁收集 766 项，`764 passed / 2 skipped`；15 项 Golden 零差异 |
| P2-17 门禁 | 固定十七模块 DAG、62 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-17 差分 | 固定 seed `8017` 的 50,000 组输入适配差分 `50000 equal / 0 different / 0 errors`；六种 reason 均实际命中，采样键长度只出现 0 或 64；SHA256 `631E624CD2805F1953743F22B1B1285CAD7A82F3D07D42E0C2C3C3C95E8C99AA` |
| P2-17 所有权 | `sampled_generation` 和 `shadow_budget_us` 由未来后台调用点持有；适配器不读取详情验活预算或资源搜索预算 |
| P2-17 审计 | 简化、加固和规格三类限域审计均为零问题；未追加运行时状态、异常包装或防御层 |
| P2-17 最终报告 | `work/v80-p2-17-stage-gate-final.json`；报告 SHA256 在最终门禁后计算 |
| P2-18 自动化 | shadow vendor `19 passed`；全部 P2 模块 `455 passed`；完整门禁收集 785 项，`783 passed / 2 skipped`；12 个必需步骤和 15 项 Golden 全部通过 |
| P2-18 门禁 | 固定十七模块 DAG、固定八模块 vendor 闭包、65 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过；两项 skipped 为 Windows 符号链接平台限制 |
| P2-18 产物 | 内存生成 `16070` bytes；vendor SHA256 `9610528E9023C77BA051F789C7C75437D0873AC0B7CC58DA20A87D4ECC9668FD`；closure SHA256 `00A8ECF9688B4677088C4C2E51F86039A19609C2CD6163544B1E8915629D8EB2`；CLI 不落盘 |
| P2-18 差分 | 固定 seed `8018` 的 50,000 组差分 `50000 equal / 0 different / 0 errors`；六种 reason、三种 report 状态和 0/64 两种采样键长度均覆盖；SHA256 `0ACA92B1C6C8D3A8603ECBEF076162CAF9C7BD98A66A732F411CCF3F60876A41` |
| P2-18 审计 | 两处冗余校验/元数据、根索引隔离断言遗漏和同行相对导入删除风险已修正；最终简化、加固和规格审计均为零问题 |
| P2-18 隔离 | manifest 仅冻结未来 vendor-proof 路径；本批未写文件、未装配 V80 单文件开发产物、未进入运行时或发布链；`production_writes=false`、`deployment_attempted=false` |
| P2-18 最终报告 | `work/v80-p2-18-stage-gate-final.json`；报告 SHA256 在最终门禁后计算 |
| P2-19 自动化 | 窄测 `75 passed / 2 skipped`；全部 P2 模块与 Golden `464 passed`；完整门禁收集 800 项，`798 passed / 2 skipped`；13 个必需步骤全部通过 |
| P2-19 产物 | V70 `616699` bytes + vendor `16070` bytes = 开发产物 `632769` bytes；SHA256 `F7590CEFD7A882CFED00D86745A68C210FB1D55B976D1228BF8AD7791D6F3172` |
| P2-19 差分 | 固定 seed `8019` 的 50,000 组装配差分 `50000 equal / 0 different / 0 errors`；六种 reason、三种 report 状态和 0/64 键长度全部精确覆盖 |
| P2-19 门禁 | 十个 parts 逐文件 SHA256、八模块 vendor、66 个受管文件凭据扫描、ATVP/FongMi/AList-TVBox 合同通过 |
| P2-19 审计 | 初审的完整门禁遗漏、退出证据不足、逐 part 指纹、受管清单和动态顶层绑定问题均已关闭；合并封板复核无剩余问题 |
| P2-19 隔离 | 无 Spider/Filter 调用点；未修改 baseline、公开源码、根索引或十个 parts；`production_writes=false`、`deployment_attempted=false` |
| P2-19 最终报告 | `work/v80-p2-19-stage-gate-final.json`；报告 SHA256 在最终门禁后计算 |
| P2 宏批次 A 自动化 | 集成测试 `64 passed / 2 skipped`；全部 P2 定向与 Golden `479 passed`；完整门禁 `813 passed / 2 skipped`；13 个必需步骤全部通过 |
| P2 宏批次 A 产物 | 九模块 vendor `18459` bytes，SHA256 `F8C118103A09AC67F8CE8DBE5F7DCD7891D40F81222CD28A4BF59223E7E1603D`；最终开发产物 `636475` bytes，SHA256 `809CB654A74DEC0364A62FE8D43FFA1BC72A43ECADD0575CCD479EFB78755FFB` |
| P2 宏批次 A 差分 | 固定 seed `8020`，`50000 equal / 0 different / 0 errors`；十种场景、30,000 次 shadow 调用、四种决策和三种 report 状态全部覆盖，关闭状态调用为零 |
| P2 宏批次 A 调用点 | `_schedule_supplement_resource_search.worker` 生产提交及 job/admission 清理之后，锁外执行；独立预算和代际状态，不写共享候选缓存 |
| P2 宏批次 A 审计 | 预算准入前物化全部 rows 的问题已关闭并增加回归；最终简化、加固和规格审计均为零问题 |
| P2 宏批次 A 隔离 | 默认关闭，不进入前台详情、bound replacement 或 entry preheat；公开 V70、根索引、baseline 和十个 parts 未修改；`production_writes=false`、`deployment_attempted=false` |
| P2 宏批次 A 最终报告 | `work/v80-p2-macro-a-stage-gate-final.json`，SHA256 `948A9AA87A7B4A2AFE12D11981B3C4F6CBD9B52948C1A6D04B2C291C710587EC`；差分报告 SHA256 `24A40E0CE1B2C6DD81337295B3F9D53763E34D58CB72F92C4FC246E105765F0E` |
| P2 宏批次 B-B1 合同 | `resource_provider.py` 仅显式登记 `vod1`、`vod`、`pansou`、`telegram`；冻结端点、搜索/详情参数、payload/row Schema 和候选归一化 |
| P2 宏批次 B-B1 自动化 | Provider/Schema/Model/阶段门禁定向 `103 passed`；P2 DAG 和 73 个受管文件敏感信息扫描通过 |
| P2 宏批次 B-B1 审计 | 生成式注册表已改为显式四项常量；最终无剩余简化、加固或规格问题 |
| P2 宏批次 B-B1 隔离 | 不执行网络、线程或缓存操作，不进入 vendor/runtime overlay，不接管 `_resource_candidates`；V70/V80 构建指纹不变 |
| P2 宏批次 B-B2 合同 | 固定顺序 `cache -> recent_success -> binding -> vod1 -> vod -> pansou -> telegram`；快慢 Provider 只分类、不调度 |
| P2 宏批次 B-B2 自动化 | Search plan/Provider/Schema/Model/阶段门禁定向 `108 passed`；P2 DAG 和 75 个受管文件敏感信息扫描通过 |
| P2 宏批次 B-B2 审计 | 无剩余简化、加固或规格问题；未追加执行器、缓存层或运行时状态 |
| P2 宏批次 B-B2 隔离 | 纯计划输出，不执行 I/O，不进入 vendor/runtime overlay；V70/V80 构建指纹不变 |
| P2 宏批次 B-B3 合同 | 本地层只接收已归一化候选，Provider 层只接收固定 payload；输出不可变批次，不跨层去重、评分或调度 |
| P2 宏批次 B-B3 自动化 | Search shadow/Plan/Provider/Schema/Model/阶段门禁定向 `114 passed`；P2 DAG 和 77 个受管文件敏感信息扫描通过 |
| P2 宏批次 B-B3 审计 | 修正省略模式与显式空模式的语义混淆；最终无剩余简化、加固或规格问题 |
| P2 宏批次 B-B3 隔离 | 不执行 I/O，不进入 vendor/runtime overlay；V70/V80 构建指纹不变 |
| P2 宏批次 B 运行时候选点 | `_resource_candidates` 完成模式/缓存/绑定候选组装之后、现有公平排序之前；复用全部现有 I/O |
| P2 宏批次 B-B4 合同 | 冻结 row identity 下按 cache、recent_success、binding、provider 优先级分类，再复用 B1/B3 生成类型化批次 |
| P2 宏批次 B-B4 自动化 | V70 adapter/Search shadow/Plan/Provider/Schema/Model/Identity/阶段门禁定向 `158 passed`；P2 DAG 和 79 个受管文件扫描通过 |
| P2 宏批次 B-B4 审计 | URL 编码身份、层冲突、未知模式、空 Provider 批次和输入不可变均覆盖；最终无剩余问题 |
| P2 宏批次 B-B4 隔离 | 不执行 I/O、锁、缓存访问、评分或调度，不进入 vendor/runtime overlay；V70/V80 构建指纹不变 |
| P2 宏批次 B vendor 预审 | 与冻结 V70 零顶层冲突；新模块仅 `_text`、`_mode`、`_first` 三组私有 helper 重名，可用局部前缀收敛 |
| P2 宏批次 B-B5 合同 | `models/schema/shadow/provider` 私有 helper 使用模块前缀；在原九模块后按依赖顺序追加 B1-B4 七模块，不引入通用 bundler |
| P2 宏批次 B-B5 自动化 | 受影响窄测与 vendor/build/overlay/stage-gate 定向 `169 passed / 2 skipped`；额外 helper 组 `84 passed`；P2 DAG 和 79 个受管文件扫描通过 |
| P2 宏批次 B-B5 产物 | 十六模块 vendor `58319` bytes，SHA256 `04A308757A40179B5F38170185E5669983BABE134E00521C3B75100E2CFD1588`，closure SHA256 `8F13F7D449CFD866A3B18AA26395AAD00BAD79C94425454CF95306AD72190D9D`；开发产物 `676335` bytes，SHA256 `31A32AF22A883957DAF70333A3A7089760EA0ED05DE4FFE84E844AE349E36015` |
| P2 宏批次 B-B5 审计 | 十六模块内部及冻结 V70 顶层命名空间零冲突；扁平化后的 V70 分层适配与源码等值；一次合并式简化、加固和规格复核无剩余问题 |
| P2 宏批次 B-B5 隔离 | 六个 Macro A overlay 锚点和调用行为不变，新增七模块未被运行时调用；未执行网络、50,000 差分、完整门禁或三路独立审计 |
| P2 宏批次 B-B6 合同 | `_resource_candidates` 完成全部 V70 I/O 和 cache/recent/binding/provider 行组装后、fair order 前运行默认关闭的分层 shadow；报告只含 layer/mode/counts/error type |
| P2 宏批次 B-B6 生命周期 | 独立开关、零默认预算、稳定采样代际、锁和 last report；init/destroy 清空采样与报告，旧代执行不能回写 |
| P2 宏批次 B-B6 自动化 | P2、Golden、build、stage-gate 定向 `584 passed / 2 skipped`；P2 DAG、82 个受管文件扫描和 ATVP/FongMi 三项兼容门禁通过 |
| P2 宏批次 B-B6 差分 | Macro A 与 Macro B 固定 seed 各 50,000 例均 `50000 equal / 0 different / 0 errors`；Macro B 报告 SHA256 `9F1559532AF183E68046F53AE38F17F46B35F2CC96471327CE2E91E9243EA800` |
| P2 宏批次 B-B6 产物 | 十七模块 vendor `61679` bytes，SHA256 `53C6A87F2CFF65C4B9FABADF800D3D0F2291D90E3122174699F1DA4C2C8EF857`，closure SHA256 `BD591DFEC19FA242F779AE93EBC9B01EB2787A63C25CECFBF0319D682DF355E8`；八锚点开发产物 `681512` bytes，SHA256 `52C9ABA52F9572790B268CF0DB95B4302952EE3CACA9A4ED337CA843E69F92BE` |
| P2 宏批次 B-B6 审计 | 合并审计发现并关闭 `destroy()` 未清空分层采样/报告状态；复核后零剩余问题，未追加新锁或防御层 |
| P2 宏批次 B-B6 隔离 | 默认关闭、异常不影响 V70 输出，不新增网络/I/O/缓存写入；公开 V70、根索引和冻结 parts 未修改；未运行完整项目门禁或三路独立审计 |
| P2 宏批次 C-C1 合同 | 独立开关与 development build、candidate shadow、layered shadow、ATVP、dual runtime、FongMi category、公开 V70 锁定、公开输出未触碰均须为字面量 `True`；按固定顺序返回首个失败原因 |
| P2 宏批次 C-C1 隔离 | 纯叶子策略只返回 `admit/reason`；不读取报告、不执行 I/O、不持有状态，不进入 vendor、overlay、冻结 parts、开发产物或公开输出 |
| P2 宏批次 C-C1 自动化 | P2、Golden、build、stage-gate 合并定向 `639 passed / 2 skipped`；P2 DAG 和 84 个受管文件扫描通过 |
| P2 宏批次 C-C1 指纹 | V70、十七模块 vendor、closure、overlay 输入和开发产物全部保持 B6 原值；未重复 50,000 差分或外部兼容门禁 |
| P2 宏批次 C-C1 审计 | 一次合并式简化、加固和规格审计 `findings=0`；未运行完整项目门禁或三路独立审计 |
| P2 宏批次 C-C2 合同 | 新增 `output_admission_dry_run`，只汇总当前内存 step 状态并调用 C1；完整证据为 `passed/admit=true`，跳过为 `skipped`，真实失败或写入/部署标记为 `failed` |
| P2 宏批次 C-C2 隔离 | 不读取或解析外部报告，不接入 vendor、overlay、冻结 parts 或公开输出；缺失/重复证据及 malformed decision 均明确拒绝 |
| P2 宏批次 C-C2 自动化 | P2、Golden、build、stage-gate 合并定向 `653 passed / 2 skipped`；P2 DAG 和 84 个受管文件扫描通过 |
| P2 宏批次 C-C2 指纹 | V70、十七模块 vendor、closure、overlay 输入和开发产物全部保持 B6 原值；未运行完整 50,000 差分或外部兼容门禁 |
| P2 宏批次 C-C2 审计 | 一次合并式简化、加固和规格审计 `findings=0`；未运行部署或公开输出切换 |
| P2 宏批次 C-C3 合同 | `v70_source_lock` 只读验证冻结标签/manifest、公开源码与唯一 V70 索引、隔离开发输出和零写入/零部署；complete 模式强制 upstream 合同 |
| P2 宏批次 C-C3 实现树 | 全部受管输入与完整 `tests` 树共 86 文件；命令前后严格比较 file count、聚合 SHA256 和逐文件 manifest；SHA256 `1A53C72BEBCEA2F76C5A223E76F72D2C6517EEE0E24BCC5D43D17C92A620009F` |
| P2 宏批次 C-C3 自动化 | 完整阶段门禁 `17/17 passed`；pytest `953 passed / 7 skipped`，使用门禁私有 `--basetemp` 且关闭缓存插件；84 个受管文件扫描和 P2 DAG 通过 |
| P2 宏批次 C-C3 差分/兼容 | Macro A/B 各 50,000 例均 `50000 equal / 0 different / 0 errors`；ATVP、双运行时、FongMi 分类与 AList-TVBox 1.42.0 upstream 合同通过 |
| P2 宏批次 C-C3 隔离 | `admit=true`、`source_lock_verified=true`、`restore_action_planned=false`、`production_writes=false`、`deployment_attempted=false`；公开 V70 指纹和根索引不变，不执行恢复或回退 |
| P2 宏批次 C-C3 审计 | 三路独立审计发现的 upstream 必需性、实现树绑定/漂移和确定性重解析测试缺口均已关闭；最终无剩余阻断项 |
| P2 宏批次 C-C3 最终报告 | `work/v80-stage-gate.json`；SHA256 `20D2E011EF76191FEB6D650643A511CC2D7CFCEA8766DF894497B48B0AAD5403` |
| 公开部署影响 | 无；不自动部署、不覆盖 V70 固定入口 |
| 公开索引 | 继续登记 `version: 70` |
| P2-C3 当时后续阶段（历史记录） | P3 剩余可靠性工作包、P4 安全、P5 可观测性与发布 |

V80 当前仍不是可部署版本。P1 证明开发结构和构建基线可重复；P2-1 至 P2-19 冻结资源模型、Schema、归一化、匹配、评分、聚合、排序、preference、合并、identity、完整候选管道、shadow policy/report/background 输入和固定 vendor；宏批次 A/B 已把两条默认关闭的 shadow 路径接入隔离开发产物，保持独立预算、代际与状态，不接管输出、共享缓存或生产预算；宏批次 C 已完成八证据准入、隔离 dry-run、V70 源码锁定与 V80 开发输出隔离验证和实现树绑定。P2 已封板，公开 V70 源码、根索引、baseline manifest 和冻结 parts 均未修改；V70 已有独立源码留存，P2 不设计恢复或回退动作。

P3 首个 History 同步工作包已完成封板。目标源码为 AList-TVBox `1.45.1`，相对 `1.45.0` 的运行时合同没有再次变化；`1.45.x` 已移除旧 `/history/{token}` 服务端实现，因此隔离 V80 路径使用 `/api/playback/*`。实现覆盖 `site/spider_plugin` 三元身份、活跃 FongMi CID 重建、增量游标、完整快照、墓碑、导入后提交、重启 UID 重识别、降序游标 latest 重建、缓存异常关闭、轻量读取与完整同步 pending 隔离、History 上下文锁和新旧认证令牌隔离；封板证据保留在 `work/v80-stage-gate-1451.json`。

P3 第二至第七个工作包已封板：结构化 Reliability、Retry/Backoff、Provider Reliability、History 客户端事件队列、Cache Health 和 Background Bulkhead 分别冻结失败分类、唯一重试所有者、Provider 熔断/并发隔离/健康评分、持久 deferred、统一 stale/backoff 和 `10/1/5` 三条后台非阻塞 lane。第八个 Chaos/Recovery 工作包使用虚拟时钟对 12 个本地故障场景建立 `0/1000/30000ms` 恢复基线，并将 History 401/500 对齐 AList-TVBox `1.45.1` `/api/playback/changes` 与真实 `followplay` 隔离。第九个 TimeoutBudget 工作包把公开前台入口、Douban/TMDB/Provider/播放/History 子阶段和后台 lane 收敛到有限绝对 deadline，并在生命周期代次切换时取消旧 scope、阻止下一阶段和恰好一次关闭仍被跟踪的响应。定向测试 `148 passed`，P3 全域 `379 passed / 986 deselected`；完整门禁 `18/18 passed`、pytest `1365 passed`，Golden、Macro A/B、Chaos、ATVP、FongMi 和 AList-TVBox `1.45.1` 合同全通过。候选为 `808647` bytes、SHA256 `9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9`。公开 V70 的广域网实测结论仍严格对应 `1.44.0`；九个 P3 工作包均未部署、未修改公开入口。P3 已完成本地工程封板，后续进入 P4 统一安全边界；每次代码编辑只跑语法和受影响窄测，工作包封板才运行相关定向、必要差分和一次完整门禁。本轮未进行新的服务器、容器或模拟器联调。详细依赖、交付物、验收、发布边界和禁止事项见 [V80 重构路线图](../../docs/V80_REFACTOR_PLAN.md)。

P4-1 Security Policy 已完成本地封板。纯策略模块定义三类网络区域、精确内部 origin 允许、外部全局地址要求、逐跳重定向复验、外部到内部跳转拒绝、HTTPS 降级拒绝和跨域头白名单；它不执行 DNS 或网络请求，也没有接入运行时调用点。模块为 `13919` bytes、SHA256 `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`，当前候选为 `822566` bytes、SHA256 `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`。最终完整门禁 `18/18 passed`、pytest `1412 passed`，报告为 `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json`。P4-2 将按网络调用族逐一接管，不建立第二重试层，不改变公开 V70。

P4-2 Route Security 已完成媒体线路探测这一条调用族的接入。现有 `_resolved_media_target()` 继续负责逐目标 DNS 解析，`_v80_probe_media_output_unbounded()` 继续拥有固定 IP 连接、Host/SNI、重定向、响应探测和同一 TimeoutBudget；overlay 只调用 P4 策略做目标/重定向判定与请求头过滤。精确配置的 ATVP/History origin 保持内部可用，外部目标要求全部解析地址为 global，外部不能跳入可信内部 origin，外部 HTTPS 不能降级，每跳重新解析，跨域只保留固定白名单。没有新增 retry、transport、DNS cache、executor、timeout owner，也未触碰 Provider、History、TMDB 或通用 session。最终候选为 `823561` bytes、SHA256 `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`；封板报告路径为 `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`。公开 V70、根索引与冻结 parts 仍未改变。

P4-3 JSON Shape Policy 已完成纯结构合同收口。模块以迭代栈验证解析后的精确 JSON 类型，固定容器深度、值节点和单集合上限，拒绝非有限浮点，并只返回固定原因而不包含原始值；它没有读取响应、解析 JSON、缓存、日志、网络或运行时接入所有权。P4-2 候选 `823561 / D8B2E0...` 是逐字节固定输入，新增模块为 `2383` bytes、SHA256 `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`，P4-3 候选为 `825944` bytes、SHA256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`。共享工作树在独立门禁运行中进入 P4-4，因此其完整合同由 P4-4 稳定报告统一证明。

P4-4 已把结构策略只接入 TMDB `_request_tmdb()` 成功 `200` 返回。原 `_json_response`、`401/403`、`429`、其他非 `200` 文案、requests session、缓存、TimeoutBudget 和 `close_tracked()` 继续拥有原职责；成功 shape rejection 也只由既有 finally 恰好一次关闭响应。overlay 不新增 reader、retry、cache 或 timeout policy，也不处理非 `200` payload，解析前字节和字段长度仍未完成。最终候选为 `825969` bytes、SHA256 `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`；完整门禁 `18/18 passed`、pytest `1456 passed`，报告为 `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`。签名 URL 缓存、统一脱敏和其余调用族仍属于后续 P4。

P4-5 已在同一 TMDB 接缝完成解析前响应与字段长度收口。新增纯 policy 固定 `2 MiB / 1024 UTF-8 bytes / 128 KiB` 三个上限并按 identity 返回接受值；overlay 通过 `_json_response()` 可选参数调用现有有界 reader，复用当前 deadline 且关闭参数为 false，外层 finally 继续恰好一次关闭。固定认证/限流错误优先，普通非 `200` 无效或超大 body 保持通用 HTTP 错误，成功 payload 先过 P4-3 shape 再过 field policy。最终候选为 `829040` bytes、SHA256 `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`；P4 专项 `103 passed`、完整 pytest `1493 passed`、Macro A/B 各 50,000 零差异零错误、Chaos `12/12`，封板报告为 `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`。公开 V70、根索引、十个冻结 parts 与生产部署均未改变。

P4-6 已把诊断与门禁报告脱敏收敛到一个受管纯 policy。运行时入口保持 `4096` 输出上限、`32 x 4096` 显式 secret 上限，并在固定扩展窗口中先识别跨界 secret 再截断；Header、assignment、Bearer/Basic、URL userinfo、signed query、一次/双编码结构名、play/parse/offline_download/p 路径、结构化 dict/list/tuple 与 key/value pair 均有回归。两锚点 overlay 只改 `_short_error()` 和 `_diagnostic_event()`，event、level、error、trace、字段键和值共享唯一 owner；stage-gate `_redact()` 直接加载同一 policy 的固定 `12000` 报告路径，`_sanitize()` 只负责结构递归和敏感键整值掩码。最终候选为 `837931` bytes、SHA256 `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`；高相关回归 `252 passed`、P4 合并 `172 passed`、完整 pytest `1602 passed`。最终决策证据为 `work/v80-p4-6-diagnostic-redaction-decision-20260815.json`，封板报告路径为 `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`。未新增网络、缓存、重试、TimeoutBudget、session、response-close 或生命周期 owner，也未执行生产写入或部署。

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
