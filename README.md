# AList-TVBox 插件仓库

这是一个遵循 [har01d5/tvbox](https://github.com/har01d5/tvbox) `spiders_v2.json` 导入格式的精简插件仓库，仅保留 AList-TVBox 导入、插件运行和公开维护所需文件。

## Web 插件管理导入

在 AList-TVBox Web 界面打开插件管理，把以下地址填入 **仓库地址** 后选择 **导入仓库**：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

这是本仓库插件发布后的正式安装和更新路径。首次导入会新增插件；以后保持插件 `id` 不变并递增仓库版本号，再次导入同一仓库地址即可刷新现有插件源码，不需要删除旧插件或改用源码直链。插件 EXT 和启用状态由现有插件记录继续保留。

仓库导入完成后，刷新正在使用的客户端订阅即可加载新版。

只部署 SeedHub 时使用仓库内的单插件索引，避免刷新或重复导入无关插件：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/plugins/seedhub/spiders_v2.json
```

## 插件列表

| 插件 | 版本 | 索引状态 | 说明 |
| --- | ---: | --- | --- |
| 豆瓣 TMDB 追更助手 | 70 测试版 | 可导入 | [能力与配置](plugins/douban_tmdb_follow_single/README.md) |
| SeedHub 磁力与多网盘 | 1 | 可导入 | [能力与配置](plugins/seedhub/README.md) |

### 豆瓣 TMDB 追更助手 v70 测试版

- 追更详情预热进行中时，只有单条绑定线路连续覆盖 E01 至当前目标集才直接返回。
- 旧绑定只有最近单集时继续执行受限前台搜索，并保留旧线路作为超时兜底。
- 已追更剧集首开复用本地 TMDB 元数据并共享统一资源截止时间，避免资料请求与线路搜索串行叠加导致 ANR。
- 同一资源接口按网盘提供方轮询候选，后台验证会继续寻找完整季度线路。

- 播放成功后分阶段刷新 FongMi 最近观看：覆盖播放器 History 的异步写入和 5 秒保存节流，追更状态同步不再依赖退出影视模块重进。
- 新播放会使旧的云端 History 快照失效；晚到的轻量请求不能覆盖完整同步刚发布的高集数进度。
- 完整线路就绪门禁改为单一播放组连续覆盖目标集；不同残缺组只能用于详情展示或明确的同盘补全，不会被自动绑定为完整线路。
- 动态页改为只读取云端 History 快照，不再触发本机 History 导出、全量合并和导入；完整双向同步保留在“立即同步 History”和播放结束同步路径。
- History 无云端差异时跳过第二次本机导出和整表导入，减少动态页和详情页等待。

- 统一管理后台任务、定时器和执行器，插件重新初始化或销毁后，旧任务不能继续覆盖新配置下的状态。
- 统一响应缓存与线路质量缓存的保存、重试和退避；过期数据刷新采用单任务所有权，减少重复刷新和旧任务回写。
- 豆瓣、TMDB、追更持久化与 History 协调逻辑拆分为内部组件，保持单文件发布和双运行时兼容。
- 新增脱敏诊断事件与诊断快照，关键失败可定位到具体阶段，同时避免令牌、Cookie 和认证信息进入诊断内容。
- 修复跨生命周期缓存保存、线路质量失败重试、追更页刷新任务和资源搜索名额释放等并发边界问题。
- 修复首次详情云端 History 时序、追更确认反馈与候选记录清理；广域网 History 默认复用订阅 HTTPS 地址，并兼容 AList-TVBox 1.44.0 单条删除接口异常。
- 仓库只保留固定入口 `py/豆瓣TMDB追更单入口.py`；历史版本通过 Git 提交或标签原子回退，不再重复提交整份源码。

### V80 开发说明

当前公开安装和更新仍固定为 V70。V80 只在 `v80-dev` 分支按 [V80 重构路线图](docs/V80_REFACTOR_PLAN.md) 开发，不自动部署，也不修改根 `spiders_v2.json` 的 `version: 70`。

V80 采用“开发态模块化、发布态单文件”的构建合同：由 manifest 定义有序 parts，再生成单文件开发产物。P1 至 P5 的构建结果使用独立开发位置，不覆盖 `py/豆瓣TMDB追更单入口.py`；只有 P1-P5 全部门禁、实机联调和人工发布批准完成后，才允许原子晋升公开入口和索引。

V80-P1 与 P2 已于 2026-08-14 完成本地验收。P2 完成固定资源模型、Provider/Schema、候选归一化/匹配/评分/合并/排序、两条默认关闭且使用独立预算与代际状态的 shadow 路径，以及八证据准入 dry-run 和 V70 源码锁定与 V80 开发输出隔离验证；没有接管公开输出、共享缓存或生产预算。最终完整门禁 `17/17 passed`，pytest `953 passed / 7 skipped`，Macro A/B 各 50,000 例差分均为 `50000 equal / 0 different / 0 errors`，ATVP direct-play、FongMi direct-PY、FongMi category/extend 和 AList-TVBox 1.42.0 upstream 合同通过；pytest 使用门禁私有 `--basetemp` 并关闭缓存插件，不依赖全局临时目录。86 文件实现树在门禁前后保持稳定，SHA256 `1A53C72BEBCEA2F76C5A223E76F72D2C6517EEE0E24BCC5D43D17C92A620009F`；最终报告 `work/v80-stage-gate.json` 的 SHA256 为 `20D2E011EF76191FEB6D650643A511CC2D7CFCEA8766DF894497B48B0AAD5403`。冻结 V70 仍为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`；十七模块 vendor、closure、overlay 输入和隔离开发产物保持 B6 指纹，开发产物为 `681512` bytes、SHA256 `52C9ABA52F9572790B268CF0DB95B4302952EE3CACA9A4ED337CA843E69F92BE`。门禁记录 `admit=true`、`source_lock_verified=true`、`restore_action_planned=false`、`production_writes=false`、`deployment_attempted=false`，公开源码、根索引、baseline manifest 和十个冻结 parts 均未修改；V70 已有独立源码留存，本阶段不计划恢复或回退。

P3 的首个 History 同步工作包已完成封板，目标上游已同步到 AList-TVBox `1.45.1`。`1.45.x` 已移除旧 `/history/{token}` 服务端实现，因此 V80 隔离开发路径改用 `/api/playback/*`，并保留对旧容器 `404/405` 的受控回退与重新登录。该工作包覆盖 `site/spider_plugin` 三元身份、增量游标、完整快照、墓碑删除、导入后提交、重启后 UID 重识别、降序游标重建、认证令牌隔离和 History 上下文串行化；定向门禁为 `46 passed`，隔离候选为 `714878` bytes、SHA256 `4F293BF5D62A1AC10A287B0608556C6C449FB46B98CE0F9826DF4EDBA9AC5B26`。封板结果保留在 `work/v80-stage-gate-1451.json`。

P3 的第二个 Reliability 工作包已完成实现并进入封板。它只增加结构化失败分类、Provider `_resource_api_get()` 的 HTTP/payload 异常映射，以及复用现有 `_atvp_deadline_timeout()` 的绝对 deadline 阶段分配；结构化错误优先，旧文案诊断继续兼容。该包不接管 History、TMDB 或通用网络层，不实现 retry/backoff、Circuit Breaker、Bulkhead、Health 或 Chaos，也不宣称端到端 TimeoutBudget 或整个 P3 已完成。定向验证为 `259 passed / 7 skipped`，隔离候选为 `724277` bytes、SHA256 `6D590868B80950923F44A793A515A351EC9CC8FABC631EF7DD6DE5ED860C4099`；封板报告写入 `work/v80-stage-gate-1451-reliability.json`。公开 V70 仍锁定为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`，两个 P3 工作包均未修改公开源码、根索引或十个冻结 parts。

P3 的第三个 Retry/Backoff 工作包已完成实现并进入封板。它正式化现有 ATVP urllib3 传输重试为唯一重试所有者：`total/connect/read=2`、`status/other=0`、`backoff_factor=0.4`、仅 GET、禁用 `Retry-After` 和状态码重试；Provider 的绝对 deadline 只预留最坏 `0.8s` 退避，未叠加第二层应用重试。旧版 urllib3 的兼容构造至少保留原有传输重试，不静默降为零重试；无 deadline 调用保持 V70 行为。定向验证为 `278 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，隔离候选为 `727368` bytes、SHA256 `3BF3D5C02A4ED67F48F852A78614528B123DE53D4C4B055D1FC588EF66C5A0AE`。本包不接管 HTTP 状态重试、重定向策略、Circuit Breaker、Bulkhead、Health、Chaos、History/TMDB 或通用网络层，也不宣称端到端硬 wall-clock cancellation；V70 公开输出与 1.45.1 上游合同均保持锁定。

P3 的第四个 Provider Reliability 工作包已完成实现、三路复审和封板。它只在 Provider `_resource_api_get()` 路径增加按 backend/mode 隔离的三态 Circuit Breaker、容量为 `2` 的 Bulkhead 和有界 EWMA Health：连续 `3` 次瞬态失败后打开 `30s`，半开仅允许一个探针；瞬态范围严格限定为 timeout、DNS、TLS、transport、server 和 rate limit，拒绝以结构化 `circuit_open`、`bulkhead_rejected` 返回。backend 切换、重新初始化和 `destroy()` 会推进代次并使旧租约失效，旧请求不能污染新状态；现有 urllib3 仍是唯一重试所有者，没有新增应用层 retry loop。Reliability 窄测 `171 passed`，扩展定向 `304 passed / 7 skipped`，隔离候选为 `738611` bytes、SHA256 `49106B27ED2F1824F9C9460464B200093BB243554EB4F023736FD28D7832AB76`；封板报告为 `work/v80-stage-gate-1451-provider-reliability.json`。本包没有扩展到 TMDB、History、通用网络、HTTP 状态重试、重定向或公开 V70 接管；后续 P3 仍需收口其他子系统隔离、Chaos/恢复基线和端到端超时。

P3 的第五个 History 客户端事件队列工作包已完成实现、第二轮三路复审和封板。活动队列上限为 `256`，批量溢出持久化到受 `HISTORY_ROW_LIMIT` 约束的 `deferred`，每轮最多 drain `8` 条；deferred 支持跨重启恢复、UID 轮换隔离、delete/upsert 单调合并和重复批量幂等。满队列时可更新已有 deferred 身份，真正的新身份仍明确拒绝。History 专项 `31 passed`，P3 全域 `249 passed`，构建与阶段定向 `86 passed / 7 skipped`，三路复审的 Critical/High/Medium 均为 `0`。最终完整门禁 `17/17 passed`，pytest `1207 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`；隔离候选为 `776229` bytes、SHA256 `9A3008A774FACE213EDC337E3B92CDBF088C4A79CB8961D04DD24F133A02C5C6`。封板报告为 `work/v80-p3-1451-stage-gate-sealed-r2-20260814.json`。P3 仍未整体完成，公开 V70、根索引和冻结 parts 均未切换。

P3 的第六个 Cache Health 工作包已于 2026-08-15 完成实现、交错线程回归、集中复审和封板。它只统一 TMDB JSON cache、Douban JSON/text cache、Spider History 快照和通用后台 cache refresh 的 stale/backoff 决策：仅 `None` 为 miss，保持 inclusive TTL，stale 立即返回并在后台刷新，连续失败最多记录 `6` 次，延迟为 `1/2/4/8/16/32s` 且受 `failure_ttl` 限制。History 非阻塞刷新失败现在使用同一退避抑制重复请求，但仍不影响播放。本包不接管 Provider circuit/bulkhead、资源缓存、Filter History cache、History 持久事件队列或 P4 安全范围。聚焦测试 `47 passed`，构建与阶段定向 `91 passed / 7 skipped`，完整门禁 `17/17 passed`，pytest `1259 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，ATVP、FongMi 双运行时、分类参数和 AList-TVBox `1.45.1` 上游合同通过。最终隔离候选为 `781140` bytes、SHA256 `50572D6304283CE39AA17AA2F25D1ED3EE9CEE88BB4DEB1C5B81D06EC6D79FBE`，报告为 `work/v80-p3-1451-cache-health-stage-gate-sealed-20260815.json`。P3 仍剩独立 Bulkhead、Chaos/恢复基线、TimeoutBudget 与硬取消等工作，公开 V70 保持锁定。

P3 的第七个 Background Bulkhead 工作包已于 2026-08-15 完成实现、合并回归、集中复审和封板。它只增加三个固定、互相独立且非阻塞的后台 lane：`resource_completion=10`、`history=1`、`route_probe=5`。资源 lane 覆盖绑定线路替换、入口资源预热和补充资源搜索；History lane 覆盖后台快照/同步和手工 probe/sync；route lane 只覆盖后台线路预热。准入失败立即返回，不排队、不等待、不新增 retry；执行器或线程启动失败会释放租约并保留原启动失败诊断。重新初始化和 `destroy()` 推进代次并清空活动计数，旧代次租约不能释放新代次容量。本包不接管 Provider bulkhead、前台搜索、History 持久事件队列、cache refresh 或 V70。聚焦范围 `44 passed`，受影响回归 `81 passed / 2 skipped`，包级回归 `163 passed / 7 skipped`；最终完整门禁固定要求 `17/17 passed`、pytest `1308 passed / 7 skipped`、Macro A/B 零差异，并验证 ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 上游合同。隔离候选为 `786881` bytes、SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`；报告 `work/v80-p3-1451-background-bulkhead-stage-gate-sealed-20260815.json` 为 `71535` bytes、SHA256 `01E67933BC238319ECD064FC1527D6BAF36896A86E8A3729B48A759F43E639C9`。公开 V70、根索引和十个冻结 parts 继续锁定；P3 剩余范围收敛为 Chaos/恢复时间基线、端到端 TimeoutBudget 与硬取消边界。

P3 的第八个 Chaos/Recovery 工作包已于 2026-08-15 完成实现、包级回归和集中复审。确定性虚拟时钟覆盖 TMDB 500/timeout stale、PanSou timeout、History 401 强制重认证、History 500 播放隔离、AList 502、DNS 失败、IPv6 不可达、播放 URL 过期重签发、截断 JSON、现有流式超大 JSON 边界和旧生命周期任务，12 个场景全部通过。固定恢复基线为 `0ms`、`1000ms` 或 `30000ms`；TMDB 冷启动/热缓存 `250ms / 0ms` 只是合成传输延迟，不代表实机性能。集中复审将 History 401/500 改为真实 `1.45.1` `/api/playback/changes` 路径，并验证 History 故障后的实际 `followplay`；非预期异常不记录原始文本。聚焦回归为 `92 passed / 5 skipped`，P3 包级回归为 `446 passed / 7 skipped`，105 个受管文件的敏感信息扫描通过；隔离候选仍为 `786881` bytes、SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`。封板证据由 `work/v80-p3-1451-chaos-recovery-stage-gate-sealed-20260815.json` 记录。本包不执行真实网络请求、真实 sleep、生产写入或部署；超大 JSON 统一安全边界仍属于 P4，随后 TimeoutBudget 与硬取消已按下一段完成。

P3 的第九个 TimeoutBudget 与生命周期硬取消工作包已于 2026-08-15 完成实现和本地阶段封板。公开前台入口各自只建立一个有限根 scope，Douban、TMDB、Provider、播放、History 与重认证子阶段继承同一绝对 deadline，子 deadline 只能收紧，传输 timeout 和既有 retry/backoff 均从剩余预算计算；没有新增重试层。`init()`/`destroy()` 代次切换会取消旧 scope、阻止其进入下一传输阶段，并恰好一次关闭仍被跟踪的流式响应，旧代次不能关闭或污染新代次资源；三个后台 lane 使用彼此独立的有限 scope。定向测试为 `148 passed`，P3 全域为 `379 passed / 986 deselected`；最终完整门禁为 `18/18 passed`，pytest `1365 passed`，Golden `15 equal / 0 different`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，Chaos `12/12`，ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 上游合同通过。隔离候选为 `808647` bytes、SHA256 `9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9`；最终报告为 `work/v80-p3-1451-timeout-budget-stage-gate-sealed-20260815.json`。P3 至此完成本地工程封板，但 V80 仍未部署、未覆盖公开 V70，统一 URL/重定向/响应/头部/脱敏安全边界仍属于 P4。

P4 的第一个 Security Policy 工作包已于 2026-08-15 完成本地封板。它只冻结纯决策合同：`trusted_backend`、`configured_internal`、`external_untrusted` 三个网络区域；精确配置的私网/回环/链路本地后端可用；外部目标的全部解析地址必须为 global；外部重定向不得进入内部区域，外部 HTTPS 不得降级为 HTTP，每一跳都要求新的解析地址证据；跨域请求头使用固定白名单并移除凭据。该模块不执行 DNS、网络、缓存、日志、重试、TimeoutBudget 分配或运行时拦截，只作为 `13919` bytes、SHA256 `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8` 的叶模块追加在 P3 候选之后。当前隔离候选为 `822566` bytes、SHA256 `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`；完整门禁 `18/18 passed`、pytest `1412 passed`，Golden、Macro A/B、Chaos、ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 合同均通过。封板报告写入 `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json`。公开 V70 与根索引未变；P4 仍未完成，下一工作包只允许逐个接入现有网络接缝。

P4-2 已把上述策略只接入现有媒体线路探测调用族。接入点复用已有 DNS 解析、固定 IP 连接、Host/SNI、重定向循环、响应探测、TimeoutBudget 和 route probe executor；精确配置的 `atvp_api`、`history_api` 与 History origin 保持可信，外部目标要求全部解析地址为 global，外部重定向不能进入可信内部 origin，外部 HTTPS 不能降级到 HTTP，每一跳重新解析并按固定白名单过滤跨域头。该包不接管 Provider、History、TMDB 或通用 requests session，不新增 retry、transport、DNS cache、executor 或 timeout owner。P4-1 输出 `822566 / A1C922...` 现在是 P4-2 的固定输入，最终隔离候选为 `823561` bytes、SHA256 `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`；完整门禁目标为 `18/18 passed`、pytest `1426 passed`，封板报告路径为 `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`。P4 仍未完成，公开 V70 与根索引继续锁定。

P4-3 JSON Shape Policy 已于 2026-08-15 完成合同收口。它只冻结解析后 JSON 值的结构规则：容器深度最多 `64`、值节点最多 `131072`、单个 list/dict 最多 `8192` 项，只接受精确 JSON 类型并拒绝非有限浮点；遍历使用有界迭代栈，拒绝原因固定且不回显输入。该叶模块不读取响应、不执行 JSON 解析，不限制响应字节或字符串/字段长度，也不接管任何调用族。模块为 `2383` bytes、SHA256 `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`，P4-3 候选为 `825944` bytes、SHA256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`；策略专项 `12 passed`、当时 P4 专项 `64 passed`。共享工作树在独立门禁运行中继续进入 P4-4，因此 P4-3 不保留一个误标为成功的独立封板报告，其全部合同由 P4-4 最终门禁重新验证。

P4-4 已把 P4-3 策略只接入 TMDB 元数据 `_request_tmdb()` 成功 `200` 返回。现有 `_json_response` 仍拥有解析与非 JSON 错误，`401/403`、`429` 和其他非 `200` 文案顺序不变，TimeoutBudget、requests session、缓存和 `close_tracked()` 所有权不变；shape rejection 仍恰好一次关闭响应。该 overlay 不增加 reader、retry、cache 或 timeout policy，也不验证非 `200` payload，不解决解析前响应字节和字段长度上限。P4-3 输出 `825944 / 8FB4EE...` 为固定输入，最终隔离候选为 `825969` bytes、SHA256 `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`。P4 专项 `74 passed`，完整门禁 `18/18 passed`、pytest `1456 passed`，Macro A/B、Chaos、ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 合同通过；封板报告为 `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`。P4 仍未完成，P4-5 只收口 TMDB 调用族的解析前响应字节和字段长度边界。

P4-5 已把上述缺口继续限定在同一 TMDB 调用族：固定解析前响应上限 `2 MiB`、object key 上限 `1024` UTF-8 bytes、string value 上限 `128 KiB`，字段遍历保持迭代式且拒绝原因不回显输入。`_json_response()` 只增加可选有界模式，另外两个一参数调用仍走既有 `response.json()`；TMDB 有界模式复用 `_read_bounded_json_shared()`、当前 `operation.deadline` 和 `close_response=False`，外层 `close_tracked()` 仍是唯一关闭所有者。`401/403/429` 固定错误在读取前保持优先，其他非 `200` 的无效或超大 body 回退既有 `TMDB HTTP <status>`，成功响应仍按 shape 后 field 的顺序验证。该包不触碰 Douban、Provider、History、播放或通用 session，也不新增 retry、cache、transport、timeout 或 close owner。当前隔离候选为 `829040` bytes、SHA256 `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`；P4 专项 `103 passed`、pytest `1493 passed`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，Chaos `12/12`。封板报告写入 `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`；公开 V70 与根索引继续锁定。

P4-6 Diagnostic Redaction Policy 已完成封板候选验证。运行时 policy 固定输出 `4096` 字符、最多处理 `32` 个显式 secret、单个 secret 最长 `4096` 字符，并在固定扫描窗口内先脱敏再截断；覆盖 Authorization/Proxy-Authorization、Cookie/Set-Cookie、assignment、Bearer/Basic、URL userinfo、常见 signed query、一次/双编码查询键与 play/parse 路径、结构化 dict/list/tuple 和显式 secret 的编码变体。两锚点 overlay 只把 `_short_error()` 与 `_diagnostic_event()` 的 event、level、error、trace、字段键和值统一路由到该 policy；stage-gate 报告复用同一有界核心，不保留第二套 URL/query/path 脱敏规则。该包不新增网络、I/O、retry、cache、transport、TimeoutBudget、session、response-close 或生命周期 owner。P4-5 输出 `829040 / 60B083...` 保持固定输入，policy 模块为 `9503` bytes、SHA256 `4A05F0910BEF7FCFA70CFEAA4D25B5B9B05482150A004CB3AFF9D5C1CD17A831`，最终候选为 `837931` bytes、SHA256 `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`；高相关回归 `252 passed`、P4 合并 `172 passed`、完整 pytest `1602 passed`。封板报告路径为 `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`；公开 V70、根索引和生产部署继续锁定。

P4-7 Douban JSON Response Boundary 已完成本地封板。8 个无凭据 fixture 冻结集合、推荐/筛选、两种搜索、详情和三种动作响应，规范序列化最大样本为 `561` bytes；按最大 50 条页面保守放大为 `28050` bytes，固定响应上限选择 `512 KiB`，约有 `18.69x` 余量且仅为 TMDB 上限的四分之一。新叶 policy 只提供该不可变字节上限；两锚点 overlay 只接管 `_DoubanClient.request_json` 与 `_v80_action_unbounded` 的想看 POST，复用 `_json_response()` 有界模式、`_read_bounded_json_shared()`、现有 shape policy、`operation.deadline` 和外层 `close_tracked()`。非 `200` HTTP 顺序、登录失效/动作消息、Douban cache/stale/backoff、session/retry/TimeoutBudget/close owner 均保持不变；Douban HTML、Provider、History、播放、redirect、signed URL cache 与 P5 继续排除。P4-6 `837931 / AF00837D...` 为固定输入，policy 为 `251` bytes、SHA256 `69C7AEF61E8724616A6621CF74C7686D702D34A8A6E3C207DB430D50301A4170`，封板候选为 `839093` bytes、SHA256 `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`。AList-TVBox `1.46.1` 更新后的正式门禁 `18/18 passed`、完整 pytest `1667 passed`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，Chaos `12/12`；报告为 `work/v80-p4-7-alist-tvbox-1461-stage-gate-sealed-r2-20260816.json`。未部署、未写入公开 V70 或根索引。

2026-08-16 已把 AList-TVBox `1.46.1` 纳入 V80 当前上游源码合同。该版本保留 `1.45.1` 的 raw plugin、路由和认证合同，同时为续播 ID 与 History 增加可选多级导航坐标和规范网盘路径。项目验证器固定 tag/commit、精确 16 文件差异、`Atvp.py` Git blob/LF 哈希、`spring.jar` 指纹、迁移注册和上游测试标记，`34/34` 检查通过；详情见 [源码变化与证据](docs/ALIST_TVBOX_1461_SOURCE_DELTA.md)。V80 Python History 当前只证明 wire forward compatibility，不宣称已拥有跨设备多级导航恢复语义。

同日当前上游继续更新到 AList-TVBox `1.47.1`。相对 `1.46.1` 的官方 compare 为 6 个提交、22 个文件，范围集中在网络直播关注；`Atvp.py`、History DTO/实体/Service 的 Git blob 未变化，1.46.1 raw plugin、认证、播放与多级续播合同继续通过。新叶验证器固定 `1.45.0` 至 `1.47.1` 继承链、clean worktree、22 文件集合、`spring.jar`/`classes.dex` 指纹、V19/Native reflect 注册、空共享/tokenized 两条 TVBox 调用链和管理端 `ADMIN|USER` 权限；stage-gate 对无效输入 scope 与 `failed/missing` 依赖 fail-closed。详情见 [1.47.1 源码变化与证据](docs/ALIST_TVBOX_1471_SOURCE_DELTA.md)。上游没有 LiveFollow 专项测试，本地源码门禁不等同于服务器或客户端关注/取关联调。

当前最新上游合同已继续推进到 AList-TVBox `1.48.0`。相对 `1.47.1` 的精确范围为 7 个提交、34 个文件，新增虎牙/斗鱼/B站/抖音实时弹幕与配置，并修复快手播放会话；`Atvp.py`、History、`PlaybackSyncInput` 和 `PlaybackSyncService` 的 Git blob 仍未变化。新叶 verifier 对精确 tag/commit、clean worktree、34 文件 delta、四个兼容 blob、新 `spring.jar`/`classes.dex` 身份和续播 markers 执行 `24/24` 检查；四代 verifier 单测为 `25 passed`，受影响 stage 单测另为 `4 passed`。报告为 `work/v80-upstream-1480-source-contract-20260816.json`，SHA256 `BA37264DE2FDEFD13A1F13E2B221EC69982561151F10DBE1B149CF04F10D4E83`；详见 [1.48.0 源码变化与证据](docs/ALIST_TVBOX_1480_SOURCE_DELTA.md)。这些是源码合同证据，不代表弹幕或快手已完成服务器、MuMu、FongMi 或实机联调。

P4-8 已解除 wishlist 证据阻塞并封板 `_DoubanClient.request_text` 单一 owner 的 Douban HTML 响应边界。一次授权、低频、无重定向且不落正文的观测得到 `200 text/html; charset=utf-8`、完整解压体 `57197` bytes、SHA256 `AA28F4570F11493F8B9EBB19E6176E2A12368817F0371804CC6E2C442EADB0C9`，实际 parser 口径为 `15` 个 grid item 与 `15` 个有效电影 subject；证据不含 URL、账号标识、标题或正文。结合 Top250 `64547` bytes 与最大 parser 投影 `12258` bytes，公式选择正式 `selected_bytes=262144`。新增 `271` bytes 的不可变叶 policy，并把 streaming overlay 接入 P4-7 精确输出；候选为 `840543` bytes、SHA256 `749F16F38DE178756C48AE4A857F30B509F16ACFFAF5E28FF421474852E4892A`。完整门禁 `18/18 passed`、pytest `1680 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`，145 文件实现树稳定；封板报告为 `work/v80-p4-8-douban-html-response-boundary-stage-gate-final-r2-20260816.json`。redirect、signed URL cache、Provider、History、播放、公开 V70、根索引和部署继续排除。

P5-1 纯 Observability Schema 与 Error Code 目录已于 2026-08-16 完成本地工程封板，仍未接入运行时事件、公开返回或播放 ID。事件/快照 Schema 固定为 `v80-diagnostic-event/1` 与 `v80-diagnostics-snapshot/1`，快照最多 `256` 条、文本最多 `512` 字符；16 个 P3 失败类型具有唯一稳定 Error Code，并冻结 core/context/measurement 字段、级别和阶段枚举。policy 模块为 `2138` bytes、SHA256 `FDFA66B624DD9C5405A77B8FAAC1D2A3973B83AB7EBFB241AFBC99319AAE4C59`，追加在 P4-8 精确输出后，隔离候选为 `842681` bytes、SHA256 `19A5FFA67ADA386585DA663AD1C7FD91FEC04322903EE207602FE2A4CC082A73`。最终门禁 `18/18 passed`、pytest `1711 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`、敏感扫描 `146/0`，报告为 `work/v80-p5-1-observability-policy-stage-gate-final-r2-20260816.json`。下一工作包 P5-2 只允许接入既有请求/操作链的运行时关联字段；Diagnostics Snapshot、私有灰度和公开晋升均尚未开始。

P5-2 运行时关联字段覆盖层已完成隔离实现、三路审计修复和完整工程门禁。它仍以 `_diagnostic_event()`、P4 `_short_error()` 和 P3 `TimeoutBudgetController` 为唯一 event、脱敏和 operation owner，通过 6 个固定 insertion 接入 `request_id`、根 scope 继承的 `trace_id`、闭集 `stage`、稳定 `error_code`、规范化 `elapsed_ms` 与既有 provider/media 上下文；生命周期 reset、cancel、generation mismatch 或 scope 结束后不再产生关联上下文。P5-1 `842681 / 19A5FFA6...` 保持固定输入，候选为 `848247` bytes、SHA256 `510D4CFEC01457AB6A264A7AF35204E87F6A2814F0A8028A9C2B9437317AB873`；overlay 定向 `29 passed`，构建与 stage-gate 关键链 `26 passed`，完整门禁 `18/18 passed`、pytest `1764 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`、敏感扫描 `149/0`、`admit=true`。最终受管文档 closure 报告固定为 `work/v80-p5-2-runtime-correlation-closure-final-20260816.json`。本包不生成 Diagnostics Snapshot，不新增网络、I/O、时钟、缓存、重试或第二套日志框架，也不改变公开 V70、根索引、部署、公开返回或 play ID。

P5-3 诊断快照覆盖层已完成隔离实现、两轮审计修复和完整工程门禁。现有私有 `_diagnostic_snapshot()` 仍是唯一快照 owner，只返回 `schema/count/events`，按 `1..256` 上限截取最近事件并保持旧到新顺序；不新增端点、持久化、时钟、buffer、dropped counter、二次脱敏、缓存、线程或日志。安全审计发现 P5-2 `_diagnostic_event()` 曾把内部 buffer 字典直接返回给调用方，现由原 event owner 返回 `dict(payload)` 脱离副本，防止 P4 入站脱敏后回写污染；历史 P5-2 封板产物仍为 `848247 / 510D4CFE...`，P5-3 当前链使用的加固中间态为 `848253 / 5B9C10F2EC877DEEF1302DCA35ABADC8BB65063EF33F0EA9698120DD96AD964C`，最终候选为 `848431` bytes、SHA256 `30EBACE80D845AA5E743EDC5AACB7DDD11A7D314A006A32F5A8B45CD8B87A409`。完整门禁 `18/18 passed`、pytest `1784 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`、敏感扫描 `152/0`、稳定实现树 `154 / 221363D790E1CCA2E3A95470D749248883213DF282061CDD9204AC53EC86CC25`、`admit=true`；本次因 gate/tool 与 P5-3 输入变化执行 `18` 步、复用 `0` 步，耗时 `795.351s`。完整证据为 `work/v80-p5-3-diagnostics-snapshot-closure-20260816.json`，最终受管文档 closure 路径固定为 `work/v80-p5-3-diagnostics-snapshot-closure-final-20260816.json`。`--resume-from` 必须同时提供受信的 `--resume-source-sha256`，未固定来源不得复用；公开 V70、根索引、十个 parts、部署和生产状态不变。

P5-5 已完成内容寻址续跑与 AList-TVBox `1.48.0` 上游合同的绿色 baseline。FongMi 两个 requirements 候选与 `verify_dual_runtime.installed_requirements()` 使用同一 `exists()` 语义：所有存在候选进入指纹，目录或读取失败使 scope 无效，零候选 fail-closed；`dual_runtime` 失败按 DAG 传播到 output admission 和 V70 source lock。修复前报告 `work/v80-p5-5-upstream-1471-closure-final-20260816.json` 保持只读，不能作为绿色封板。静默双指纹后生成的唯一完整 baseline 为 `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json`：`18/18 passed`、`18 executed / 0 reused`、pytest `1811 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `158/0`，稳定实现树 `160 / FE835719DD2CF3FF6B259A75D23F2F63EFE47BECDF2B96F2E9310B681301149C`，`admit=true`、V70 source lock 通过，耗时 `824.449s`，无生产写入或部署。该 baseline 的受信 resume pin 为 `14AA4142678A71B0B64B1B9F86EE2BA6A6C9666AC1942997172B8A762476FFFD`；后续受管文档变化只执行 DAG 失效闭包，不重跑完整 gate。

P5-5A **重复生命周期静止态覆盖层** 已于 2026-08-17 完成本地工程封板。它只在 P5-3 诊断快照精确输出后修复 `destroy()` 关闭三个受管 Session 后仍保留引用的问题，不修改冻结 V70、十个 parts、网络/缓存/重试/TimeoutBudget owner 或公开合同。项目专用 runner 对受管候选执行 32 轮 `init({}) -> destroy()`：先证明 Thread/Future/Timer 在销毁瞬间仍为 active，再受控释放并要求 1 秒内最终静止；代次连续、Session 恰好关闭、旧回调不能跨代写入，网络尝试、持久化和部署均为零。候选为 `848540` bytes、SHA256 `A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；生命周期报告 `work/v80-p5-lifecycle-stability-r7-20260817.json` 为 `32/32 passed`，SHA256 `E55CFC0FE64CB9597944447CFBDB51F705A62A6A00BB0160AABFEC4C1A2E2FF6`。完整门禁首次正确暴露 Macro A 仍固定 P5-3 最终指纹；保留失败报告后只更新该最终候选消费者，并从受信失败报告按 DAG 续跑。成功 closure `work/v80-p5-5a-lifecycle-stability-resume-closure-r2-20260817.json` 为 `18/18 passed`、`8 executed / 10 reused`、pytest `1873 passed`、稳定实现树 `163 / 9CFDD9B20BD92D8BEC485C29516C5B651D9FD0DB57DE409E67779F273E5B849B`，SHA256 `62A3F2F1755214E4EFC1895056BA46B3E6A96F1FEB044ECBF292B8372E70B117`；无生产写入或部署。该 runner 不是通用 Python sandbox，结论只绑定上述受管 candidate；冷/热缓存性能、并发搜索/播放/History、长时间运行、真实网络和实机仍属后续独立工作包。

P5-5B **冷/热缓存性能基线** 已完成独立证据与 stage closure，仍复用 P5-5A 候选 `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`，没有修改 runtime、overlay、manifest、18 步 gate 或公开 V70。项目专用 runner 直接执行真实 `Spider.v80_cache_load`，固定 `cold_miss`、`fresh_hot_hit`、`stale_background_refresh` 三场景各 32 样本；后台刷新只进入受控队列并显式释放，host `min/median/p95/max` 仅记录、不作为阈值。正式报告 `work/v80-p5-cache-performance-r1-20260817.json` 为 `96/96 passed`，SHA256 `63CEA0A99F2114385896D216166681C8C964328E86E5D848A1BEC661E03C8379`；受管 requests/socket、凭据、持久化、真实线程和 candidate sleep 尝试均为零。runner/test 最终哈希为 `560E80534C14FA056AB56CA553581367DA4319D37A8949DF659AF7C55D2A4BEF` 与 `D838CBE50C75F1C4EEFE34021D798843DC879B1E19B520DC3849DB5346BE6B9E`，三轮最终审计已清零 Critical/High/Medium。内容寻址 closure `work/v80-p5-5b-cache-performance-closure-r1-20260817.json` 为 `18/18 passed`、`7 executed / 11 reused`、pytest `1916 passed`、稳定实现树 `165 / 92BE658F0135B2A972F053ECAD599346F24A4D050AED00758D3799446527ACA3`，耗时 `1299.442s`，output admission 与 V70 source lock 通过；该报告只证明合成 cache owner 路径，不代表真实网络、并发、长稳、服务器、MuMu 或实机性能。

P5-5C **长时间运行资源增长基线** 已完成独立证据与内容寻址 closure，继续复用候选 `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`，未修改 runtime、overlay、manifest、gate 或公开 V70。项目专用 runner 在单个真实 Spider、一次 `init()`/`destroy()` 和同一 generation 内执行 `256 + 32 x 128 = 4352` 次顺序操作，逐检查点验证 cache、diagnostics、TimeoutOperation response、weakref、任务、Session 和引用容器；正式 `/2` 报告 `work/v80-p5-long-run-resource-growth-r4-20260817.json` 为 `32/32 passed`，SHA256 `9BC19054029595EC6647C2C026C98DE04E71A2D14C6466C6231ABE98921B507D`。候选文件 trace 从 `161344` 增至 `173808` bytes、delta `12464` bytes，仅为 tracemalloc 观察值，不是准入阈值；受管网络、凭据、真实线程和生产写入均为零，destroy 后 Session/task/timeout/reference/response weakref 全部清零。runner/test 哈希为 `C59BF99D5C0AFF38C32769BC23BF989FA49ADE5161FC9768279F9B7DCA7337A5` 与 `7A7B3D5CB8EB3775A69CBA0E6E0A9441D6E408242E63A71D0F7BC3BC58DD12E2`，聚焦回归 `50 passed`；审计关闭报告器内存污染、mini profile 假发布、reference bool 类型混淆和异常类型泄露。首次 closure 仅因 pytest 在 `1800s`、约 `90%` 处超时而失败；保留失败报告后以其 SHA256 pin 续跑，最终 `work/v80-p5-5c-long-run-resource-growth-closure-r2-20260817.json` 为 `18/18 passed`、`6 executed / 12 reused`、pytest `1966 passed`、稳定实现树 `167 / C7CE536D18F6C869951E4D50A0FAD69D83241D768BC043767491C11E87B6A026`，SHA256 `7977DDC3FC4EB0B9136A6B419BDDE136E703EF549365F0FAFC601EA76A3C76E7`；本结论不外推到真实网络、并发搜索/播放/History、wall-clock endurance、服务器、MuMu 或实机。

P5-5D **搜索调用族并发与隔离基线** 已完成第二轮专项实现、聚焦回归、三路复审和正式 18 步 stage closure。单个 `build_v80_search_concurrency_ownership_overlay.py` 覆盖层的中文别名为“搜索并发所有权覆盖层”，以 P5-5A `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280` 为固定输入并执行 24 个显式、唯一锚点替换；它收口 search job identity、generation 贯通、supplement 跨代阻断、资源 response exactly-once owner 和 live-init runtime 轮换，不增加通用 token/cache/sandbox/压力框架。DNS/media executor 是搜索可播放性验证与播放探测共用的受管依赖，本包只把其 owner/slot 从模块全局迁入 Spider 生命周期；四个共享播放探测算法保持 AST 不变，两个 owner 方法在归一化 owner/slot 后 AST 等价，P5-5E 仍须独立验证播放并发。当前候选为 `854833` bytes、SHA256 `3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766`。schema `v80-p5-search-concurrency/3` runner 为 `7/7 passed`，报告 `work/v80-p5-search-concurrency-runtime-owner-final-r3-20260817.json` 的 SHA256 为 `A26D93477EF9E7798EBE023F2ECE110E10C32D6E862640F609FC21C9999CA0EE`；live init 会轮换六个 executor 与四个 slot，旧 API/排队任务不能使用新 session，response 单次关闭，cleanup 为 Session `18/18`、executor `6/6`，worker/job/refresh/timeout 归零。runtime ownership `43 passed`、共享播放边界 `6 passed`、runner `15 passed`、stage-gate 单测 `242 passed`，第二轮 simplify/spec/security 复审均 `findings=0`。首次完整 closure 正确暴露 9 个旧测试/runner 对 admission 标量、generation/timeout 参数和四 executor 的过期假设，以及错误沿用 `1.46.1` upstream 根；只更新这些固定消费者并切换到干净的 `1.48.0 / 8f01c0f...f63` 根后，内容寻址 closure `work/v80-p5-5d-search-concurrency-runtime-owner-resume-closure-r2-20260817.json` 为 `18/18 passed`、`8 executed / 10 reused`、pytest `2044 passed`、稳定实现树 `171 / D24ECF6C92C16A1687CB331B81977D71642ADE629501C786BE5946D267C48050`、敏感扫描 `165/0`、`admit=true`；公开 V70、根索引和部署状态不变。该证据仍不替代真实网络、服务器、MuMu、FongMi、实机、P5-5E 播放并发或随后独立的 History 并发。

P5-5E **播放调用族并发与隔离基线** 已完成小范围实现、证据加固、三路复审和正式 18 步 stage closure。中文别名“播放并发所有权覆盖层”对应 7 个显式唯一替换，以 P5-5D `854833 / 3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766` 为固定输入；它只收口播放调用的 generation/backend/session 所有权、ATVP 旧会话隔离、response/connection 单次关闭、取消后 slot 释放、前台/后台隔离、live-init 围栏、陈旧 route-quality/probe/History 副作用拒绝和 destroy 清理，不增加通用 executor、cache、retry、sandbox、token 或并发框架。当前候选为 `857088` bytes、SHA256 `3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F`。正式 `v80-p5-playback-concurrency/1` 报告 `work/v80-p5-playback-concurrency-r2-20260817.json` 为 `8/8 passed`，SHA256 `ABFB274DD4C98C282FDBB13F8329DF32BC1AA58DE77AA3C5CB302904EADC36E0`；runner 固定复用启动时已哈希候选字节，并在加载后恢复 `base/base.spider`，避免报告与实际执行字节漂移或污染 pytest 进程。P5-5E 定向为 `31 passed`，simplify/spec/security 最终复审均 `findings=0`。技术 closure `work/v80-p5-5e-playback-concurrency-closure-r1-20260817.json` 为 `18/18 passed`、pytest `2079 passed`、稳定实现树 `176 / F59312A671B1B2E275A74F93E96478AF9C3EEA47CE12A89B2F50E8A85B99BADA`、敏感扫描 `170/0`、`admit=true`，SHA256 `1E0D3ACB2B7C3041917E75E386C935BEE895AA47C10BDA09A5E06775AD5246AA`；公开 V70、根索引和部署状态不变。下一独立包为 P5-5F History 并发，私有灰度、回退演练和发布晋升仍未完成。

P5-5F **History 调用族并发与隔离基线** 已完成小范围实现、确定性回归、三路复审和技术 closure。中文别名“History 并发所有权覆盖层”对应 13 个显式唯一替换，以 P5-5E `857088 / 3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F` 为固定输入；它只收口 History job identity、background/manual owner、replacement owner 保护、同一 context lock 内的 generation/category refresh 和临界区外持久化，不修改 `_history_sync_lock`、History 事件队列或引入通用 executor/cache/retry/concurrency 框架。当前候选为 `859732` bytes、SHA256 `B42B37C097AA989F0FE82EF380A71865A4FDA02F6606A295E120FD79DA610700`。正式 `v80-p5-history-concurrency/1` 报告 `work/v80-p5-history-concurrency-r3-20260817.json` 为 `8/8 passed`，SHA256 `9B00F4A4FCDBF4556CC764D706E67BC73EA0E4A5A6660D595BBB043050BC5E9C`；History 覆盖层及 runner `34 passed`、构建消费者 `4 passed`、stage selector `12 passed`、Chaos `7 passed`，旧消费者修复后 `53 passed`，simplify/spec/security 最终复审均 `findings=0`。失败 closure r1 只因 pytest 在 `2400s`、约 `75%` 超时；r2 只暴露 53 个历史测试消费者未禁用更晚 History overlay，两份报告均只读保留。最终技术 closure `work/v80-p5-5f-history-concurrency-closure-r3-20260817.json` 为 `18/18 passed`、`7 executed / 11 reused`、pytest `2117 passed`、稳定实现树 `180 / FE0ADBCF7628CFCE1E10D55FAF3B0780394CEFE1518755BBD388BDCDC5F87609`，SHA256 `77E0FF352DA25FAE2D76311584F70D1585CBB4E68274BD2CFCD505023F8D8648`；`production_writes=false`、`deployment_attempted=false`。本地工程仍不等于生产完成，剩余为私有灰度、真实服务器/MuMu/FongMi 验证、回退演练、人工发布批准和生产晋升。

2026-08-18 的项目级安全复核关闭了 P4 响应边界的最后两个灰度阻断项：Douban JSON/HTML、TMDB 与想看动作的固定请求 owner 全部显式关闭 Requests 自动重定向；`_resolve_user_id()` 对 3xx 只解析同源 `Location`，不跟随也不读取响应体，对 `200` 使用既有 `256 KiB` 上限、总 deadline 和单一关闭 owner。三个 P4 overlay 聚焦文件 `66 passed`，未新增通用 session、redirect、retry、cache 或 executor 框架。最终候选更新为 `862377` bytes、SHA256 `C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D`；开发源码 README 已为 `10` 个 P1 chunk 和 `36` 个根目录 Python module 建立 `46/46` 唯一中文维护别名，聚焦校验 `1 passed`。本批次最终内容寻址证据固定写入 `work/v80-p5-5f-redirect-boundary-alias-closure-r6-20260818.json`；该报告未通过前不得进入私有灰度，且公开 V70 与根索引继续保持冻结。

## 精简结构

```text
spiders_v2.json                       # AList-TVBox 仓库导入入口
docs/
  V80_REFACTOR_PLAN.md                # V70 冻结基线与 V80 分阶段重构门禁
py/                                   # 可发布插件源码
plugins/
  douban_tmdb_follow_single/          # 单个插件的文档与维护记录
    README.md                          # 能力与配置概览
    DEPLOYMENT.md                      # 完整部署步骤
    FILTER.md                          # 过滤器复用说明
    CHANGELOG.md                       # 插件更新记录
    STATUS.md                          # 发布和验证状态
    extend.example.json                # 插件 EXT 示例
    filter.example.json                # 过滤器配置示例
  seedhub/                             # SeedHub 插件文档与维护记录
    README.md                           # 能力、链路与使用边界
    DEPLOYMENT.md                       # 部署和人工客户端验证步骤
    CHANGELOG.md                        # 插件更新记录
    STATUS.md                           # 发布和验证状态
    extend.example.json                 # 可选插件 EXT 示例
    spiders_v2.json                     # 仅导入 SeedHub 的仓库索引
```

仓库不复制官方项目中的旧索引、JAR、验证工具、测试缓存或第三方插件集合。

## 索引维护规则

- 插件 `id` 发布后保持稳定，更新时只递增 `version`。
- 每次源码更新必须同时修改源码中的 `//@version` 和对应 `spiders_v2.json` 中的 `version`，两处版本保持一致。
- `file` 必须指向仓库中存在的公开插件文件。
- 明文 raw Python 插件的 `file` 必须以 `.py` 结尾。
- 只有通过兼容与安全检查的版本才设置 `valid: true`。
- 每次发布同步更新仓库根 `README.md` 的插件版本与当前版本摘要，以及对应插件的 `README.md`、`DEPLOYMENT.md`、`CHANGELOG.md` 和 `STATUS.md`。
- 同一插件只保留一个固定源码入口；历史版本由 Git 提交或标签保存，禁止新增 `_vNN.py` 发布副本。
- 每个插件的每个版本都必须在自己的 `CHANGELOG.md` 中书写更新说明。
- 更新说明只描述用户可感知的功能新增、功能调整、体验优化和问题修复，不写测试过程、测试数量、审计过程、发布命令、日志、源码大小、哈希或其他验证数据。
- 对应单插件索引存在时优先使用 `plugins/<id>/spiders_v2.json`，避免整仓导入影响其他已配置插件。

## 安全边界

本仓库不保存服务器地址、订阅令牌、Cookie、账号密码、网盘凭据或调试快照。示例中的凭据均为空值或明确占位值。实际 EXT 会随 AList-TVBox 订阅下发，应妥善保护订阅地址和容器访问权限。
