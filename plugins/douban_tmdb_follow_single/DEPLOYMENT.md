# 豆瓣 TMDB 追更助手（AList-TVBox 专用）

仓库导入地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

插件源码地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/py/豆瓣TMDB追更单入口.py
```

## V80 当前状态（2026-08-18）

V80 的 P1、P3、P4、P5 本地能力链已经完成；P2 raw-row-preserving 分层组合器和
private-V80-only controlled switch 已完成本地接管验证。前台与背景共用同一 output owner，
switch 默认关闭，combiner 异常只执行一次 legacy fallback。当前开发候选为 `870797` bytes、
SHA256 `0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9`；Macro A
`50000` 例、`14736` 个受控差异、`0 errors`，Macro B `50000 equal`，Chaos `13/13`，
ATVP、双运行时与 FongMi 分类合同通过。独立私有 staging 已生成但尚未部署；当前仍须完成
文档后的静默双指纹与变化节点 DAG closure，不能复用较早的 r4 报告冒充新封印。

## V80 私有部署边界

- 允许把固定 V80 候选部署到私有容器、私有插件 ID 或私有配置；不得覆盖公开 V70 源码、
  根 `spiders_v2.json` 或公共订阅。
- 私有合同已生成在 `private/v80/`：`id=douban_tmdb_follow_single_v80_private`、初始
  `version=80`、独立 `spiders_v2.json` 和 `staging/`。私有源码为 `870801` bytes、SHA256
  `049C722515F6851C379969C2886FA466EDD9FC9478B6B6F591E757DEEEDDCB97`；本地 builder、
  ATVP direct-play 与双运行时门禁通过。导入前仍须等待本轮 DAG closure。
- 私有 EXT 必须保留 `atvp_plugin_mode=alist-tvbox-raw` 并显式设置
  `v80_resource_layered_output=true`；未设置时继续走旧排序路径。
- MuMu 使用已经安装的 FongMi 版本刷新私有配置，不另外安装新版客户端。
- 私有部署撤回只删除/禁用私有 V80 条目或恢复上一份私有配置，并复核私有运行时 SHA256；
  公开 V70 始终保持不变，不执行 V70 原子回退。
- 服务器、MuMu/FongMi 和真实播放/History 结果必须单独记录为人工或运行时证据，不能由本地门禁代替。

## V80 历史封板记录

本插件用于豆瓣/TMDB 浏览、剧集追更、AList-TVBox 资源搜索、线路评分和 History 续播。当前发布版本为 V70 公开测试版；最低兼容基线为 AList-TVBox 1.42.0，当前已在 1.44.0 验证。插件由 AList-TVBox 生成订阅后交给 FongMi/TvBox 使用。同一源码空 EXT 直载时保留 FongMi 元数据分类、搜索、详情和直链播放合同，但追更、History 与网盘资源功能必须使用 AList-TVBox 生成的订阅。

V80-P1 与 P2 已于 2026-08-14 完成本地验收，P3 的九个隔离工作包已于 2026-08-15 完成本地工程封板：History 同步、结构化 Reliability、Retry/Backoff、Provider Reliability、History 客户端事件队列、Cache Health、Background Bulkhead、Chaos/Recovery 和 TimeoutBudget/生命周期硬取消。TimeoutBudget 为公开前台入口建立有限根 scope，Douban、TMDB、Provider、播放、History 与重认证子阶段继承同一绝对 deadline；生命周期代次切换会取消旧 scope、阻止下一传输阶段，并恰好一次关闭仍被跟踪的响应。定向测试为 `148 passed`，P3 全域为 `379 passed / 986 deselected`；完整门禁为 `18/18 passed`、pytest `1365 passed`，Golden、Macro A/B、Chaos、ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 上游合同通过。候选为 `808647` bytes、SHA256 `9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9`，封板报告为 `work/v80-p3-1451-timeout-budget-stage-gate-sealed-20260815.json`。公开 V70 仍为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`，根 `spiders_v2.json` 继续登记 `version: 70`；V70 的实际部署与 History 联调证据仍对应 AList-TVBox `1.44.0`。P3 没有执行生产写入、部署、公开入口覆盖或冻结 parts 修改；P4 统一安全边界、P5 可观测性与发布晋升、私有联调和人工发布批准仍未完成，因此 V80 仍不属于部署目标。本页所有部署步骤继续只适用于 V70。路线图见 [V80_REFACTOR_PLAN.md](../../docs/V80_REFACTOR_PLAN.md)。

P4-1 Security Policy 已于 2026-08-15 完成本地封板。它只把三类网络区域、精确内部 origin、外部全局地址、逐跳重定向复验、HTTPS 降级拒绝和跨域请求头白名单冻结为纯决策合同，不执行 DNS、网络请求、缓存、日志、retry、TimeoutBudget 分配或运行时拦截。模块为 `13919` bytes、SHA256 `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`，P4-1 隔离候选为 `822566` bytes、SHA256 `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`；完整门禁 `18/18 passed`、pytest `1412 passed`，封板报告为 `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json`。该候选现作为 P4-2 overlay 的固定输入；V80 仍不是部署目标，本页后续步骤仍只适用于公开 V70。

P4-2 已把该策略仅接入隔离 V80 的媒体线路探测。它复用已有 DNS、固定 IP 连接、Host/SNI、重定向、响应探测、TimeoutBudget 和 route executor，增加外部全局地址、逐跳重解析、外部到内部拒绝、HTTPS 降级拒绝和跨域头白名单判定；没有新增 retry、transport、DNS cache、executor 或 timeout owner，也没有接管 Provider、History、TMDB 或通用 requests session。最终隔离候选为 `823561` bytes、SHA256 `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`，封板报告路径为 `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`。P4 仍未完成，V80 仍不是部署目标，本页后续步骤继续只适用于公开 V70。

P4-3 已把解析后 JSON 的结构限制冻结为独立叶合同：容器深度 `64`、值节点 `131072`、单集合 `8192` 项，只接受精确 JSON 类型并拒绝 NaN/Infinity，错误不包含被拒绝值。该模块不读取网络响应、不解析 JSON、不限制响应字节或字段长度，也不接管任何运行时调用族；模块为 `2383` bytes、SHA256 `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`，隔离候选为 `825944` bytes、SHA256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`。该合同由随后 P4-4 的稳定完整门禁统一封板。

P4-4 仅在 TMDB `_request_tmdb()` 的成功 `200` 返回处调用结构策略；原非 `200` 判断、JSON 解析、缓存、响应关闭、requests session 和 TimeoutBudget 所有权均未改变。非 `200` payload 不进入 shape validation，解析前响应字节和字段长度也尚未受本包限制。最终隔离候选为 `825969` bytes、SHA256 `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`，封板报告为 `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`。P4-5 才收口 TMDB 响应读取边界；V80 仍不是部署目标。

随后完成的 P3 第三个 Retry/Backoff 工作包仍只属于隔离开发链：它复用现有 urllib3 GET transport retry，Provider 仅为最坏 `0.8s` backoff 预留 deadline，不增加第二层请求循环，也不改变 V70 的公开输出。候选为 `727368` bytes、SHA256 `3BF3D5C02A4ED67F48F852A78614528B123DE53D4C4B055D1FC588EF66C5A0AE`；`278 passed / 7 skipped`，两组 50,000 例宏差分均零差异、零错误。该包不接管状态码重试、重定向、端到端硬取消、Circuit Breaker、Bulkhead、Health、Chaos、History/TMDB 或通用网络层，也没有部署或覆盖公开入口。

P4-5 已在隔离 V80 中为同一 TMDB 调用族增加解析前 `2 MiB` 响应上限、`1024` UTF-8 bytes object key 上限和 `128 KiB` string value 上限。它复用现有 `_read_bounded_json_shared()`、当前 TimeoutBudget deadline 与外层 `close_tracked()`，另外两个 `_json_response(response)` 调用保持原 `response.json()` 路径；固定 `401/403/429` 错误优先，其他非 `200` 的无效或超大 body 保持通用 HTTP 错误，成功 body 先验证 JSON shape 再验证字段长度。该包未修改公开 V70、根索引、十个冻结 parts、Douban/Provider/History/播放或通用 session，也未新增 retry/cache/transport/timeout/close owner。候选为 `829040` bytes、SHA256 `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`；封板报告写入 `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`。V80 仍不是部署目标，本页后续部署步骤继续只适用于公开 V70。

P4-6 Diagnostic Redaction Policy 已在隔离 V80 完成封板：运行时 `_short_error()`、`_diagnostic_event()` 与 stage-gate 报告统一复用同一有界脱敏核心，不新增网络、I/O、retry、cache、TimeoutBudget 或 response-close owner。候选为 `837931` bytes、SHA256 `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`，报告为 `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`。

P4-7 Douban JSON Response Boundary 已完成本地封板。它把 `_DoubanClient.request_json` 与想看动作 POST 接入固定 `512 KiB` 有界读取和既有 JSON shape policy，同时保持非 `200`/登录消息顺序、Douban cache/stale/backoff、session/retry/TimeoutBudget 与外层 `close_tracked()` 所有权。封板候选为 `839093` bytes、SHA256 `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`，报告为 `work/v80-p4-7-alist-tvbox-1461-stage-gate-sealed-r2-20260816.json`。

P4-8 Douban HTML Response Boundary 已把 `_DoubanClient.request_text` 作为唯一运行时 owner 封板，固定解压响应上限 `256 KiB`，复用现有 Requests 解码、TimeoutBudget deadline 和 `close_tracked()`。候选为 `840543` bytes、SHA256 `749F16F38DE178756C48AE4A857F30B509F16ACFFAF5E28FF421474852E4892A`；完整门禁 `18/18 passed`、pytest `1680 passed`，报告为 `work/v80-p4-8-douban-html-response-boundary-stage-gate-final-r2-20260816.json`。P4 至此完成本地封板。

P5-1 仅在隔离构建链追加 `2138` bytes 的纯 Observability Schema/Error Code policy，候选为 `842681` bytes、SHA256 `19A5FFA67ADA386585DA663AD1C7FD91FEC04322903EE207602FE2A4CC082A73`。它不接入运行时、不改变公开返回、play ID、网络、I/O 或时钟 owner；本地封板报告 `work/v80-p5-1-observability-policy-stage-gate-final-r2-20260816.json` 记录 `18/18 passed`、pytest `1711 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `146/0` 和 `admit=true`。

P5-2 运行时关联字段覆盖层只存在于隔离 V80 开发构建。它通过 6 个固定 insertion 复用 `_diagnostic_event()`、P4 `_short_error()` 和 P3 TimeoutBudget/lifecycle owner，候选为 `848247` bytes、SHA256 `510D4CFEC01457AB6A264A7AF35204E87F6A2814F0A8028A9C2B9437317AB873`；定向 overlay 为 `29 passed`，构建与 stage-gate 关键链为 `26 passed`，完整门禁为 `18/18 passed`、pytest `1764 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `149/0` 和 `admit=true`。最终受管文档 closure 报告为 `work/v80-p5-2-runtime-correlation-closure-final-20260816.json`。P4-7、P4-8、P5-1 与 P5-2 均未部署、未修改公开 V70、根 `spiders_v2.json` 或十个冻结 parts；Diagnostics Snapshot、私有灰度和人工发布批准仍未开始，因此本页后续部署步骤仍只适用于公开 V70。

P5-3 诊断快照覆盖层只存在于隔离 V80 开发构建，已完成本地完整工程门禁但未部署。它保留 `_diagnostic_snapshot()` 单 owner，以 `v80-diagnostics-snapshot/1` 的 `schema/count/events` 包装最多 256 个已在 P4 入站脱敏的事件；不增加公共端点、上传、持久化、时钟、缓存、线程或第二次脱敏。审计修复由原 P5-2 event owner 返回 `dict(payload)`，使调用方不能回写内部 buffer；历史 P5-2 封板产物仍为 `848247 / 510D4CFE...`，P5-3 加固中间态为 `848253 / 5B9C10F2...964C`，最终候选为 `848431 / 30EBACE80D845AA5E743EDC5AACB7DDD11A7D314A006A32F5A8B45CD8B87A409`。完整门禁 `18/18 passed`、pytest `1784 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `152/0`、稳定实现树 `154 / 221363D7...CC25`、`admit=true`，无生产写入或部署；证据为 `work/v80-p5-3-diagnostics-snapshot-closure-20260816.json`，最终受管文档 closure 路径为 `work/v80-p5-3-diagnostics-snapshot-closure-final-20260816.json`。续跑只接受带受信 SHA256 pin 的旧报告；后续部署步骤继续只适用于公开 V70。

P5-5 已把上游源码合同推进到 AList-TVBox `1.48.0`，但仍未部署或切换公开入口。新合同报告 `work/v80-upstream-1480-source-contract-20260816.json` 记录 `24/24` 源码检查通过，固定 7 commits / 34 files、关键 ATVP/History/Playback blobs 与新 `spring.jar`/`classes.dex` 身份。requirements 指纹修复后的绿色 baseline 为 `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json`：`18/18 passed`、pytest `1811 passed`、敏感扫描 `158/0`、稳定树 `160 / FE835719...149C`、`admit=true`、V70 source lock 通过，且 `production_writes=false`、`deployment_attempted=false`。该报告 SHA256 `14AA4142678A71B0B64B1B9F86EE2BA6A6C9666AC1942997172B8A762476FFFD` 只作为后续内容寻址 closure 的受信 pin。弹幕和快手变化没有服务器、MuMu、FongMi 或实机运行证据，因此不得据此部署、宣传或修改本页公开 V70 步骤。

完整功能不要把 `.py` 文件直接添加为普通 FongMi 站点，也不要手工填写外层 `api`、`token`、`secret`、`loader`、`source` 或 `raw`。

## 使用前准备

只需准备两项：

1. 可从 AList-TVBox 访问的本仓库 `spiders_v2.json` 地址。
2. TMDB API Read Access Token，用于 TMDB 数据和完整追更功能。

以下广域网 History 部署说明属于当前公开 V70 与已实测的 AList-TVBox `1.44.0` 合同。广域网双向 History 默认复用当前订阅地址，不需要额外配置协议转换。只要公网 HTTPS 反代同时转发 `/api/accounts/login`、`/history/{token}` 和 `Authorization` 请求头，插件即可直接登录、读取和写入。只有订阅入口不能承载 History、且另有客户端可访问的 History 入口时，才配置 `history_api`。广域网登录不要使用开放公网 HTTP；服务端仅有内网 HTTP 时，应在服务端反代层提供 HTTPS，或通过受保护的 VPN/内网穿透访问。AList-TVBox `1.45.x` 的 V80 开发合同使用 `/api/playback/*`，不能把下面的 V70 路由说明直接套用到 V80。

TMDB Token 获取方法：

1. 登录 [TMDB](https://www.themoviedb.org/)。
2. 打开“头像 → 设置 → API”，也可直接访问 [API 设置页](https://www.themoviedb.org/settings/api)。
3. 申请 API 权限后，复制页面中的 **API Read Access Token**。
4. 把完整 Token 填入 `tmdb_access_token`，不要填写账号密码。

如需把本地追更结果写回 AList-TVBox History，还需一个能登录容器 Web 后台的 `USER` 或 `ADMIN` 账号。只读取 History 不需要填写账号。

## 仓库结构

把以下文件放到同一个 HTTPS 静态仓库：

```text
spiders_v2.json
py/
  豆瓣TMDB追更单入口.py
```

源码地址必须以 `.py` 结尾。AList-TVBox 会自动生成 `csp_PyProxy`、`spring.jar`、`loader=/Atvp.py?v=...`、`.py source` 和 `raw=true`。

## Web 界面部署

以下名称对应 AList-TVBox 1.42.0 Web 页面。

### 1. 导入插件

1. 使用管理员账号登录 AList-TVBox。
2. 打开 Web 插件管理。
3. 在 **仓库地址** 中粘贴 `spiders_v2.json` 地址，点击 **导入仓库**。
4. 在下方列表找到“豆瓣 TMDB 追更助手”，确认 **启用** 已打开，状态为“正常”。

首次导入会新增插件。以后插件 `id` 保持不变并提高仓库版本号，再次导入同一仓库地址即可刷新现有插件；正式发布和更新不使用插件源码直链，也不先删除旧插件。

### 2. 填写插件 EXT

1. 在插件所在行点击 **配置**，打开 **扩展配置**。
2. 复制 `extend.example.json` 的全部内容到文本框。
3. 只需把 `YOUR_TMDB_READ_ACCESS_TOKEN` 替换成自己的 TMDB Token。
4. 需要 History 双向同步时，再填写 `history_username` 和 `history_password`。
5. 点击 **保存配置**，回到列表后点击该插件的 **刷新**。

示例中的 `_说明_*` 是合法 JSON 字段，仅用于中文注释，插件会忽略，可以保留。

### 3. 加载订阅

1. 回到 **订阅管理** 页面。
2. 使用已有订阅，或点击 **添加** 新建订阅。
3. 复制列表中的 **TvBox 配置地址**，地址形如 `/sub/{安全Token}/{订阅ID}`。
4. 在 FongMi/TvBox 中把该地址设为配置地址并刷新配置。
5. 进入“豆瓣 TMDB 追更助手”。

需要追更、History 和网盘资源时，不要把插件 `.py` 地址直接填入 FongMi/TvBox。

## EXT 必要字段

| 字段 | 是否必填 | 填写方法 |
| --- | --- | --- |
| `atvp_plugin_mode` | 必填 | 固定为 `alist-tvbox-raw`，不要修改。 |
| `tmdb_access_token` | 完整功能必填 | 从 TMDB 的“设置 → API → API Read Access Token”复制。只浏览豆瓣公开内容时可留空，但 TMDB 和相关追更功能不可用。 |
| `history_api` | 特殊部署可选 | 默认留空并复用订阅地址。仅当订阅入口与 History 入口确实分离时，填写客户端可访问的 HTTPS 地址。 |
| `history_username` | 云写入可选 | 使用能登录当前 AList-TVBox 的 `USER` 或 `ADMIN` 用户名。后台有 **用户** 菜单时，也可在其中添加用户。 |
| `history_password` | 云写入可选 | 与上面用户名对应的登录密码。用户名和密码必须同时填写。 |
| `resource_search_modes` | 推荐保留 | 默认示例启用 `vod1`、`vod`、`pansou`、`telegram`；插件会自动隐藏后端缺少的模式。 |

其余性能参数已有安全默认值，首次使用无需填写。插件 EXT 会随订阅下发，应保护订阅地址。

## 首次使用

1. 先在 FongMi 其他站点收藏或播放剧集；也可从本插件导航卡直接打开全局搜索后完成收藏或播放。
2. 打开“追更确认”，检查本机收藏和播放记录中的待选剧集，点击后确认加入追更。
3. 导航页点击电影或剧集卡始终直接打开 FongMi 全局搜索，不在导航页切换追更方式。
4. 在“追更动态”查看新集，在“追更管理”查看全部已追更记录。
5. 标记已看或取消追更时，进入“追更管理”选择对应操作，再点击项目和确认卡。
6. 需要查看同步状态、立即重试、检测通讯或调整本机 History 分享权限时，打开“追更管理”；首页不再提供独立“云端历史”分类。
7. 在详情中先选季集；已验证真实续播优先，其后按完整覆盖至最新集、是否包含最新集、集数覆盖和画质质量排序，最多保留 5 条独立有效线路。相同分享 URL 只保留标题、密码和更新时间更完整的版本，AT 已解析但桌面 Range 探测未知的安全直链仍保留给客户端播放。

添加、取消和标记已看的结果会显示持久状态卡，不需要依赖 Toast 判断操作是否成功。History 同步成功仅在“追更管理”保留最近结果；同步中或失败时，“追更动态”也会显示可重试告警。

首次加入追更时即使还没有播放记录，打开详情也会按标题和别名直接搜索 AList-TVBox。History 只用于续播集和播放位置，不是资源搜索的前置条件。搜索结果必须继续通过详情解析、链接盘检和真实播放探测；没有可信结果时保持空线路，不生成假播放项。

插件初始化以及进入首页、追更动态或追更管理时，会限量后台预热最多 3 个追更条目的播放列表并缓存约 15 分钟。详情优先直接使用已验证热缓存；预热未完成时只检查既有绑定线路，不在首次进入同步重验全部候选。后台首次得到可播线路或线路集合继续增加时，会定向刷新仍停留在当前项目的详情页。

播放和预热任务会固定启动时的容器地址、令牌和配置代次。切换容器后，旧任务会在请求或提交前停止，不会把旧资源、质量或缓存写入新后端；失败预热最多短暂退避 60 秒，之后允许后台重新恢复。

追更动作在开始、完成或失败等每个状态变化时各提交一次追更页定向刷新。直接刷新失败时最多等待约 1 秒再检查一次当前可见追更页，普通浏览分类不会被后台补全反复刷新。

## 资源匹配规则

- 优先接受标准化后完全相同的标题。
- 可接受标题前后的季号、年份、集数、画质、字幕、编码和剧集类别等资源说明。
- 不使用编辑距离或任意近似匹配，例如“测试剧集2”不会匹配“测试剧集”。
- 解说、剪辑、预告、花絮、幕后、制作特辑、特别节目和衍生内容会被拒绝。
- 明确多季剧必须匹配当前追踪季；同季资源优先于无季号资源。
- 单季剧不把候选季号当作硬门禁，季号一致时仍有排序加分，错标候选只作为较低优先级备用。
- 多季剧当前季的资源年份可以不同于整部剧的首播年份；没有季号时，年份冲突仍会被拒绝。
- `vod1`、`vod`、`pansou`、`telegram` 返回的 `vod_name/name/title/vod_title/show_name/work_title/note` 会统一参与匹配；只要顶层或嵌套链接存在显式 `work_title`，就只按这些权威标题判断。标题后缀中的年份、季集、分辨率、字幕、网盘来源和 HiveWeb 等说明不会导致有效资源被误拒绝。
- 兼容 PanSou 原始 `data.merged_by_type` 和 `data.results[].links[]`；各网盘来源和结果链接按轮询预算扫描，链接级资源先占结果名额，带 `links` 的通用父记录不能在小结果上限下挤掉有效分享。
- 相同分享 URL 即使协议或提取码字段的表达不同也只保留一份；先比较标题和链接级 `work_title`，再比较密码完整度和解析后的 RFC3339/数值时间。不同 API 的同名不透明 ID 保持独立播放列表。
- 剧集线路先比较已验证真实续播，再比较截至 `latest_episode` 的完整覆盖、是否包含最新集、明确集数和连续集数；只有这些条件相同时才继续比较历史绑定和画质质量。
- provider 从搜索候选、详情改写、播放参数、成功线路和追更绑定全链路保存；只有相同且非空的 canonical provider 可以互补缺集，未知、非规范或冲突 provider 不会从线路名称重新猜测。
- 磁力按规范化 BTIH、ED2K 按内容哈希去重；长磁力和 ED2K 使用独立输入上限，不再套用普通资源 ID 的 512 字符限制。
- 四类 API 只保留已知标量元数据并在存储前限长，未知嵌套大字段会被丢弃；PanSou 链接扫描有固定共享预算，达到输出上限后只在有限窗口内继续修正重复记录。
- 前台四 API 搜索使用独立 4 线程有界队列，盘搜/电报后台补全使用独立 2 线程池；后台任务不会占用前台并发位。详情重写独立扫描最多 64 个播放组，最终合并后才应用 5 条线路、512 集和输出字节预算。
- 播放 ID 超过上限时在验活与网络入口直接拒绝；已验证详情缓存采用字段白名单、过期清理和 64 条 LRU 上限。
- AList-TVBox 最终播放响应中的 `Cookie`、`Referer` 和 `User-Agent` 会按白名单交给 FongMi/TvBox；夸克直链缺少 Cookie 时常见的 `412`/`bad http status` 不再由插件主动过滤造成。

## History 说明

本节描述公开 V70 在 AList-TVBox `1.44.0` 上的已验证行为。V80 P3 的 `1.45.1` 隔离实现使用 `/api/playback/*`，尚未进入公开部署链。

- History 会在进入追更、资源详情等需要记录的页面时后台刷新，不需要日常手动操作。
- 播放成功不会立即同步；播放超过 8 分钟后进入待同步状态。收到退出回调时立即触发同步，没有回调时约 5 秒检测一次；播放器仍在运行或同步暂不可用时继续按 5 秒间隔重试。
- 插件 History 快照默认缓存 60 秒，详情读取过期快照时只启动一个后台刷新任务；过滤器自己的 History 缓存默认 30 秒。
- “追更确认”每次进入都会直接读取 FongMi 本机收藏和播放记录；未确认的条目保持待选，确认后才写入追更列表。
- “追更确认”“追更管理”和“追更动态”每次进入都会检查待同步播放记录，并刷新已追更剧集的最新观看集数。
- “追更管理”始终提供“立即同步 History”“检测通讯”以及追更播放记录/普通观看记录的本机分享开关，即使还没有追更剧集也可使用。
- `GET /history/{token}`：只读，不要求插件登录。
- `POST /history/{token}`：写入，需要 EXT 中配置 `USER` 或 `ADMIN` 账号。
- 跨客户端进度依赖 AList-TVBox 云端 History；配置 `USER` 或 `ADMIN` 账号后，本机退出播放器触发的进度才能上传并由其他客户端读取。
- 两个分享开关仅筛选当前客户端未来提交到 `POST /history/{token}` 的记录；关闭追更播放记录不会影响普通观看记录上传，关闭普通观看记录也不会影响追更播放记录上传。
- 无论开关状态如何，`GET` 云端拉取、History 合并、本机导入和追更进度回写都会继续执行；关闭开关不会删除已经上传到云端的记录。
- 分享设置只保存在当前客户端本地缓存，不保存或上传设备指纹。新客户端默认允许两类记录上传，用户可在该客户端的“追更管理”中单独调整。
- 本机缓存暂时无法读取分享设置时，管理页会显示“暂缓异地同步”并暂停上传；读取到设置或用户成功保存后恢复，云端拉取、合并和本机导入仍继续执行。
- 用户名或密码任一留空：严格保持只读，不发送 POST；仍可读取已有云端 History 和本机续播记录，但本机新增进度不会同步到其他客户端。
- 私网地址只对字面量私有/回环 IP、IPv6 ULA 或 `localhost` 生成 HTTP/HTTPS 对端，包含 `::1` 且有无显式端口都支持；当前订阅地址优先于旧地址。POST 仅在连接尚未建立或 TLS 协议明确不匹配时重试，TLS EOF、读取超时和远端断开不会重复提交，错误正文按流式字节上限读取。
- 异地客户端只能从云端 History 取得另一台设备的进度；只读模式不会把本机新增进度上传，因此其他设备仍会看到云端原有集数和位置。
- 云端读取暂时失败时，插件会使用过期缓存或本机记录继续处理，并禁止本轮上传；失败阶段和时间会保留在管理页。
- 上传、本机导入或追更进度回写单项失败时，其余已取得的有效结果仍会继续应用，管理页会保留失败阶段和时间。
- 自动同步与手动同步不会并发执行；重复点击只会提示当前任务仍在运行。
- 登录凭据只用于当前容器的 History 写入，不写入发布包。

## 过滤器复用

过滤器是可选功能，用于给其他 AList-TVBox 受管站点补充 History 选集和续播位置。它不搜索资源、不共享本追更助手的独立备选线路，也不替换外站最终播放地址。

简要设置：

1. 打开 **订阅 → 过滤器管理**。
2. **过滤器地址** 填同一份 `豆瓣TMDB追更单入口.py` 的 HTTPS 直链。
3. **拦截点** 选择“详情”和“播放”。
4. **作用范围** 选择“除外”，在 **插件** 中选择本追更助手，避免自身被重复处理。
5. 点击 **添加过滤器**。
6. 在过滤器所在行点击 **配置**。保持表单默认值即可，也可在 **JSON 编辑** 中粘贴 `filter.example.json`。
7. 点击 **保存配置**，再点击该行 **刷新**。
8. 让 FongMi/TvBox 刷新订阅配置。

完整说明见 `FILTER.md`。插件和过滤器是两条独立记录：主插件更新时重新导入仓库，过滤器还需在过滤器管理中确认使用同一发布源码并单独点击 **刷新**；两者不会互相刷新。

## 常见问题

### 插件状态异常或看不到插件

确认仓库可由 AList-TVBox 访问，索引文件名为 `spiders_v2.json`，且其中的源码路径以 `.py` 结尾。正式更新时重新导入仓库，不要删除旧插件或改用源码直链。

### 提示不是 AList-TVBox raw 订阅

确认 EXT 中保留：

```json
{"atvp_plugin_mode":"alist-tvbox-raw"}
```

保存配置、刷新插件，再让 FongMi/TvBox 刷新配置。不要手填 `atvp_api` 或 `atvp_token`。

### TMDB 页面提示凭据无效

确认填写的是 TMDB **API Read Access Token**，没有多余空格，也没有误填 API Key、登录密码或整段网页内容。

### History 能读取但不能写入

确认 `history_username` 和 `history_password` 同时填写，且该账号能登录当前 AList-TVBox。`USER` 和 `ADMIN` 都允许。修改后保存配置并刷新插件。

如果公开 V70 订阅能加载但 History 通讯检测失败，确认公网 HTTPS 反代同时开放 `/api/accounts/login` 和 `/history/{token}`，并保留 `Authorization` 请求头。只有 History 使用另一入口时才填写 `history_api`，不要因为容器内网监听 HTTP 就把客户端地址改成不可达的内网 HTTP。该排障项不适用于 V80 的 AList-TVBox `1.45.1` `/api/playback/*` 开发路径。

### 过滤器没有生效

确认拦截点为“详情、播放”，作用范围覆盖目标插件，过滤器已启用且状态正常。更新源码后先重新导入主插件仓库，再单独刷新过滤器。

### 详情没有资源

插件只把 HTTP `404/405/501` 识别为后端缺失，并自动隐藏对应模式。如果所有模式都不可用，页面会明确显示无资源。

### 播放提示 bad http status

先确认主插件和同源过滤器都已刷新到 V70。v55 会丢弃各网盘直链所需的播放头，夸克 Cookie 缺失时会表现为详情有线路但候选返回 `bad http status`；v56 起按白名单保留 AList-TVBox 返回的标准播放头，v57 进一步阻止跨域失败回退敏感头和签名媒体直链进入长期状态，v60 重构后台任务与缓存生命周期，v61 修复首次详情 History/线路和追更确认反馈，v63 将动态页 History 刷新改为云端快照路径，v64 修复集数感知预热和同步后即时刷新，V70 修复残缺绑定线路在预热期间阻止完整线路搜索的问题。

## V80-P5-5A 生命周期证据边界

- P5-5A **重复生命周期静止态覆盖层** 仍是隔离开发候选，不属于可部署版本，也没有修改本页的 V70 部署步骤。
- 当前候选为 `848540` bytes，SHA256 `A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；32 轮 `init({}) -> destroy()` 本地静止态报告为 `work/v80-p5-lifecycle-stability-r7-20260817.json`。
- 最终本地 stage-gate closure 为 `18/18 passed`、pytest `1873 passed`，但 `production_writes=false`、`deployment_attempted=false`，不能据此刷新插件仓库、过滤器、订阅或容器。
- runner 只绑定当前受管 candidate，不是通用 Python sandbox；零网络观察不等于任意源码无法绕过，也不等于服务器、MuMu、FongMi 或真实设备通过。
- P5-5B 缓存性能和 P5-5C 长时间运行资源增长均已完成独立本地证据；并发调用族、私有灰度、公开 V80 晋升和回退演练完成前，继续保留公开 V70 和根 `spiders_v2.json` 的 `version: 70`。

## V80-P5-5B 缓存性能证据边界

- P5-5B **冷/热缓存性能基线** 仍是隔离开发证据，不属于可部署版本，也没有修改本页的 V70 部署步骤。
- 当前候选保持 `848540` bytes、SHA256 `A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；正式报告 `work/v80-p5-cache-performance-r1-20260817.json` 为 `96/96 passed`，SHA256 `63CEA0A99F2114385896D216166681C8C964328E86E5D848A1BEC661E03C8379`。
- 内容寻址 stage closure 为 `work/v80-p5-5b-cache-performance-closure-r1-20260817.json`：`18/18 passed`、`7 executed / 11 reused`、pytest `1916 passed`、稳定实现树 `165 / 92BE658F0135B2A972F053ECAD599346F24A4D050AED00758D3799446527ACA3`，耗时 `1299.442s`；output admission 与 V70 source lock 通过，且 `production_writes=false`、`deployment_attempted=false`。
- 三场景只覆盖合成 `cold_miss`、`fresh_hot_hit` 和 `stale_background_refresh`；host timing 是本机观测值，不是发布 SLO，也不能推导服务器、网络、MuMu、FongMi 或真实设备时延。
- runner 观察到受管 requests/socket、凭据、持久化、真实线程和 candidate sleep 尝试均为零；其边界不是通用 Python sandbox，且不覆盖并发搜索/播放/History 或长时间运行。
- P5-5C 已封板，但后续并发工作包、私有灰度、人工批准和完整回退演练关闭前，禁止上传、替换公开入口或把根索引切换到 V80。

## V80-P5-5C 长时间运行资源增长证据边界

- P5-5C **长时间运行资源增长基线** 仍是隔离开发证据，不属于可部署版本，也没有修改本页的 V70 部署步骤。
- 当前候选保持 `848540` bytes、SHA256 `A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`；正式报告 `work/v80-p5-long-run-resource-growth-r4-20260817.json` 为 `32/32 passed`，SHA256 `9BC19054029595EC6647C2C026C98DE04E71A2D14C6466C6231ABE98921B507D`。
- 内容寻址 stage closure 为 `work/v80-p5-5c-long-run-resource-growth-closure-r2-20260817.json`：`18/18 passed`、`6 executed / 12 reused`、pytest `1966 passed`、稳定实现树 `167 / C7CE536D18F6C869951E4D50A0FAD69D83241D768BC043767491C11E87B6A026`，SHA256 `7977DDC3FC4EB0B9136A6B419BDDE136E703EF549365F0FAFC601EA76A3C76E7`；output admission 与 V70 source lock 通过，且 `production_writes=false`、`deployment_attempted=false`。
- tracemalloc 只观察候选文件的 Python allocation，`12464` bytes delta 不是发布阈值，也不覆盖 native memory、RSS 或 wall-clock endurance；零网络/线程/持久化观察只约束受管表面，不是通用 Python sandbox。
- 后续搜索、播放和 History 并发基线必须按调用族独立建立；在私有灰度、人工批准和完整回退演练关闭前，不得部署 V80 或切换公开索引。

## V80-P5-5D 搜索调用族并发与隔离证据边界

- P5-5D **搜索调用族并发与隔离基线** 仍是隔离开发证据，不属于可部署版本；固定 overlay 的中文别名为“搜索并发所有权覆盖层”，以 24 个显式唯一替换收口搜索 owner 和生命周期，不修改本页 V70 部署步骤。
- 当前候选为 `854833` bytes、SHA256 `3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766`，P5-5A `848540 / A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280` 继续作为中间输入合同。
- 正式专项报告 `work/v80-p5-search-concurrency-runtime-owner-final-r3-20260817.json` 为 schema `/3`、`7/7 passed`，SHA256 `A26D93477EF9E7798EBE023F2ECE110E10C32D6E862640F609FC21C9999CA0EE`；覆盖前台容量、排队取消、job owner、旧代写回、响应单次关闭、资源补全舱壁隔离和 live init/destroy 竞争。
- cleanup 证据为 18 个 Session 单次关闭、6 个 executor 清理，live init 六 executor/四 slot 换代，search job、refresh key、reference、bulkhead 和 timeout 状态归零；runtime ownership `43 passed`、共享播放边界 `6 passed`、runner `15 passed`、stage-gate 单测 `242 passed`，三路复审 `findings=0`。
- 首次完整 closure 只读保留为失败诊断：9 个旧测试/runner 仍假设 admission 标量、旧函数签名或四 executor，并错误沿用 `1.46.1` upstream 根。最小修正后从其可信 SHA 内容寻址续跑，`work/v80-p5-5d-search-concurrency-runtime-owner-resume-closure-r2-20260817.json` 为 `18/18 passed`、`8 executed / 10 reused`、pytest `2044 passed`、稳定树 `171 / D24ECF6C92C16A1687CB331B81977D71642ADE629501C786BE5946D267C48050`、敏感扫描 `165/0`、`admit=true`，且未写入生产或部署。
- DNS/media executor 是搜索可播放性验证与播放探测共享依赖，本包仅迁移 owner/slot 生命周期；共享播放探测算法保持不变，不能替代 P5-5E 播放并发。runner 使用受控 session 和禁止网络表面，结论不能推导真实网络、服务器、MuMu、FongMi 或实机时延。
- P5-5E 播放调用族和随后 History 调用族仍须分别建立证据；私有灰度、人工批准和完整回退演练关闭前，禁止上传、替换公开入口或把根索引切换到 V80。

## V80-P5-5E 播放调用族并发与隔离证据边界

- P5-5E **播放调用族并发与隔离基线** 仍是隔离开发证据，不属于可部署版本；固定 overlay 的中文别名为“播放并发所有权覆盖层”，以 7 个显式唯一替换收口播放 owner 和生命周期，不修改本页 V70 部署步骤。
- 当前候选为 `857088` bytes、SHA256 `3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F`，P5-5D `854833 / 3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766` 继续作为中间输入合同。
- 正式专项报告 `work/v80-p5-playback-concurrency-r2-20260817.json` 为 schema `/1`、`8/8 passed`，SHA256 `ABFB274DD4C98C282FDBB13F8329DF32BC1AA58DE77AA3C5CB302904EADC36E0`；覆盖 player 隔离、旧 ATVP session、单次关闭、slot 恢复、前后台隔离、live init、陈旧副作用拒绝和 destroy 清理。
- runner 固定让 8 场景从启动时已哈希的同一候选字节编译，加载后恢复 `base/base.spider`；live-init 场景明确绑定 `cancelled` 结果，避免异常退出或运行中替换候选产生假通过。定向 `31 passed`，三路最终复审 `findings=0`。
- 技术 closure `work/v80-p5-5e-playback-concurrency-closure-r1-20260817.json` 为 `18/18 passed`、pytest `2079 passed`、稳定树 `176 / F59312A671B1B2E275A74F93E96478AF9C3EEA47CE12A89B2F50E8A85B99BADA`、敏感扫描 `170/0`、`admit=true`，SHA256 `1E0D3ACB2B7C3041917E75E386C935BEE895AA47C10BDA09A5E06775AD5246AA`；`production_writes=false`、`deployment_attempted=false`。
- 该证据不覆盖 History 自身并发、真实网络、服务器、MuMu、FongMi 或实机时延。P5-5F History 并发、私有灰度、人工批准和完整回退演练关闭前，禁止上传、替换公开入口或把根索引切换到 V80。

## V80-P5-5F History 调用族并发与隔离证据边界

- P5-5F **History 调用族并发与隔离基线** 仍是隔离开发证据，不属于可部署版本；固定 overlay 的中文别名为“History 并发所有权覆盖层”，以 13 个显式唯一替换收口 History job/background/manual/replacement owner、generation/category refresh 和持久化临界区，不修改 `_history_sync_lock`、History 事件队列或本页 V70 部署步骤。
- 当前候选为 `859732` bytes、SHA256 `B42B37C097AA989F0FE82EF380A71865A4FDA02F6606A295E120FD79DA610700`，P5-5E `857088 / 3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F` 继续作为中间输入合同。
- 正式专项报告 `work/v80-p5-history-concurrency-r3-20260817.json` 为 schema `/1`、`8/8 passed`，SHA256 `9B00F4A4FCDBF4556CC764D706E67BC73EA0E4A5A6660D595BBB043050BC5E9C`；定向与消费者回归分别为 `34`、`4`、`12`、`7` 和 `53 passed`，三路最终复审 `findings=0`。
- closure r1 只因 pytest 在 `2400s`、约 `75%` 超时；closure r2 只暴露 53 个历史测试消费者没有禁用更晚 History overlay。两份失败报告均只读保留，恢复时只修复已复现消费者并按依赖图续跑，没有重跑独立完整 baseline。
- 技术 closure `work/v80-p5-5f-history-concurrency-closure-r3-20260817.json` 为 `18/18 passed`、`7 executed / 11 reused`、pytest `2117 passed`、稳定树 `180 / FE0ADBCF7628CFCE1E10D55FAF3B0780394CEFE1518755BBD388BDCDC5F87609`，SHA256 `77E0FF352DA25FAE2D76311584F70D1585CBB4E68274BD2CFCD505023F8D8648`；`production_writes=false`、`deployment_attempted=false`。
- 该证据不覆盖真实网络、服务器、MuMu、FongMi 或实机。私有灰度、真实环境验证、完整回退演练、人工发布批准和生产晋升完成前，继续禁止上传、替换公开入口或把根索引切换到 V80。

## 文件说明

- `../../py/豆瓣TMDB追更单入口.py`：当前测试版唯一明文源码入口。
- 历史版本通过 Git 提交或版本标签原子回退，不在当前仓库树中重复保存整份源码。
- `../../spiders_v2.json`：插件仓库索引。
- `extend.example.json`：带中文说明、可直接粘贴的插件 EXT。
- `filter.example.json`：可直接粘贴到过滤器“JSON 编辑”的配置。
- `FILTER.md`：过滤器 Web 界面操作和边界。
- `CHANGELOG.md`：逐版本更新记录。
- `STATUS.md`：源码指纹、兼容基线和发布状态。

## 安全边界

- 发布包不包含服务器地址、订阅令牌、Cookie、账号密码、CK 或调试快照。
- 不接入网盘账号管理接口 `/api/pan/accounts/-/info`。
- 不修改 AList-TVBox 服务端、`Atvp.py`、`spring.jar` 或 FongMi APK。
- 本仓库公开提供明文源码；实际 EXT 会随订阅下发，应保护 AList-TVBox 订阅地址和容器访问权限。
