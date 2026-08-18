# V80 生产级重构路线图

## 1. 文档状态

本文档是豆瓣 TMDB 追更助手从 V70 向 V80 演进的治理基线，用于约束开发顺序、阶段产物、验收门禁、审计与回退。它不是发布公告，也不表示 V80 已可部署。

截至 2026-08-18：

- 当前公开发布仍为 `V70`，仓库索引 `spiders_v2.json` 仍登记 `version: 70`。
- V80 只在 `v80-dev` 分支开发，不自动部署，不覆盖公开固定入口，不修改公开索引版本。
- P1、P3、P4、P5 本地能力链已完成；P2 的模型、Provider、Schema、匹配、评分、合并、排序和影子差分已完成，但真实前台/背景输出仍由旧 `_resource_fair_candidate_order()` owner 负责，尚未完成生产接管。
- 当前候选为 `862581 / 87DCAC75E7F60CA70219EA99C238940E756D53D17A82D2FE684622A38CD5BADC`。项目级安全复核除关闭 Requests 自动重定向和 `_resolve_user_id()` 无界读取外，已把未探测播放 URL 的弱兜底迁移到 V80 专用覆盖层，并让敏感扫描与实现树共用同一显式测试清单；定向组合闭包为 `318 passed`，未新增通用 redirect/session/cache/retry 框架。
- 46 个维护单元中文别名已按 10 个 chunk 与 36 个 Python module 精确覆盖；最终 r6 closure 为 `18/18 passed`、pytest `2124 passed`，报告 SHA256 `743ACB44FDE44AA17E5E4118DE859854A5FCA5426FD04FDFDC74D9CAC91385A9`。
- `work/v80-upstream-1500-private-release-doc-closure-final-r4-20260818.json` 仍是上一受信完整基线；当前候选在文档同步、静默双指纹和 DAG 续跑完成前不描述为已封印提交。私有灰度、真实环境验证、私有配置撤回和人工批准完成前，V80 不得接管公开行为。

## 2. V70 冻结基线

V70 是 V80 重构期间唯一的发布与行为基准。

| 项目 | 锁定值 |
| --- | --- |
| Git 标签 | `v70` |
| Git 提交 | `612617b35f08b98234c6e20c8137d8dea9035e97`（短提交 `612617b`） |
| 发布入口 | `py/豆瓣TMDB追更单入口.py` |
| 文件大小 | `616699` 字节 |
| SHA256 | `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4` |
| 自动化回归 | `285` 项通过 |
| ATVP 合同 | direct-play / `upstream-1.25-raw` 门禁通过 |
| 双运行时合同 | AList-TVBox raw 插件链与 FongMi direct-PY 门禁通过 |
| FongMi 分类合同 | TypeFragment、SiteApi、Chaquopy、Atvp 参数链通过 |
| V70 实机基线 | AList-TVBox 1.44.0、FongMi TV 5.6.1 已记录验证 |
| V80 P3 上游目标 | AList-TVBox 1.45.1；History 使用 `/api/playback/*` |

冻结规则：

1. 不移动或重写 `v70` 标签。
2. P1 至 P4 不修改公开固定入口和 `spiders_v2.json` 的 V70 登记。
3. V80 的开发构建产物必须使用独立路径或临时产物，不得由构建命令自动复制到公开入口。
4. 若 V70 必须紧急修复，应建立独立修复决策和发布记录；不得把未完成的 V80 重构混入 V70。
5. 任一 V80 阶段失败时，公开部署继续使用 `v70/612617b`，无需逆向撤销未发布的重构。

## 3. 重构原则

### 3.1 保留行为，替换结构

V80 不是推倒重写。先固化 V70 的输入输出、排序、播放 ID、History 合并、缓存与异常降级行为，再逐模块迁移。未经 Golden 或合同样本批准的行为变化视为回归。

### 3.2 开发态模块化，发布态单文件

V80 的构建合同只规定三类输入和一个输出：

```text
manifest
  + ordered parts
  + single-file build
  -> 豆瓣TMDB追更单入口.py
```

- `manifest` 定义部件顺序和构建元数据。
- `parts` 保存按职责拆分的开发源码。
- `single-file build` 生成兼容 AList-TVBox/FongMi 的单文件产物。
- 构建必须确定性、离线可重复，并默认写入开发产物位置。
- 本路线图不预设构建器语言、文件名、模板系统或模块加载方式；具体实现由 P1 在测试约束下决定。

### 3.3 合同优先

以下合同在整个 V80 周期内均为硬门禁：

- AList-TVBox raw 插件加载和 direct-play 返回合同。
- FongMi direct-PY 空 EXT 初始化、分类、搜索、详情和播放合同。
- FongMi 分类调用中 `tid`、`pg`、`filter`、`extend` 的传递与 JSON 字符串兼容。
- `detailContent`、`playerContent`、播放 ID、播放头白名单和运行时 `siteKey` 合同。
- `Spider` 与 `Filter` 不得出现重复方法定义。

### 3.4 有证据才切换

新旧实现优先影子运行或固定输入对比。差异报告必须说明差异来源、是否预期、对应测试和批准结论；不能以“新实现更合理”为由直接改变 V70 行为。

## 4. 阶段依赖

```text
V70 freeze
    |
    v
P1 architecture and build foundation
    |
    v
P2 normalized resource engine
    |
    v
P3 reliability and history synchronization
    |
    v
P4 unified security boundary
    |
    v
P5 observability, release candidate and promotion
```

P4 的威胁建模可以在早期准备，但安全边界的正式接管必须建立在 P1 的模块边界以及 P2/P3 的网络与数据流已经稳定之后。P5 的基础诊断字段可以提前预留，但完整观测与发布晋升只在前四阶段验收后进行。

## 5. V80-P1：架构与构建基础

### 阶段状态

2026-08-13 已完成本地验收。最终完整门禁为 `324 passed`，15 项脱敏 Golden 行为与冻结 V70 全部一致；ATVP direct-play、FongMi direct-PY、分类参数链和 AList-TVBox 1.44.0 源码合同通过。简化、安全和规格审计中的关键与高风险问题已关闭。该结论仅属于源码与本地门禁证据，不替代服务器、容器、MuMu 或真实设备验证。

### 目标

改变开发结构，不改变运行行为；建立可重复的单文件构建、V70 行为快照和阶段门禁。

### 前置条件

- V70 标签、提交、大小和 SHA256 已复核。
- 现有 285 项回归可从干净环境重复执行。
- ATVP、双运行时和 FongMi 分类合同工具可执行。

### 工作范围

1. 固化 V70 行为快照和 Golden Fixtures，覆盖元数据、资源搜索、详情、播放、History、缓存和失败降级。
2. 建立 `manifest + parts + single-file build` 开发结构。
3. 按现有依赖顺序拆分职责，不重新设计业务算法。
4. 建立依赖方向，底层网络、缓存和模型不得反向依赖 Spider/Filter Adapter。
5. 建立确定性构建检查、重复方法检查、敏感信息扫描和版本一致性检查。
6. 生成 V80 开发产物，但不写入公开固定入口。

### 建议逻辑边界

```text
config_models
runtime_lifecycle
network_transport
cache_health
metadata
follow
history
resource_engine
providers
playback
adapter_filter
```

这些名称表示职责，不强制对应一对一文件，也不授权在 P1 改变业务行为。

### 交付物

- V70 行为与合同基线报告。
- 脱敏 Golden Fixtures 及其来源说明。
- manifest、开发 parts 和单文件开发构建产物。
- 构建可重复性、依赖边界和源码结构检查。
- 每次迁移的 V70/V80 差异报告。

### 验收

- 285 项 V70 回归全部通过。
- ATVP direct-play、FongMi direct-PY、FongMi 分类参数合同全部通过。
- 同一输入连续构建的开发产物字节一致。
- 构建产物中不存在重复 `Spider`/`Filter` 方法。
- Golden 输出与 V70 一致；任何允许差异均有单独审批记录。
- `spiders_v2.json` 仍为 `version: 70`，公开固定入口仍为 V70 指纹。

### 回退

删除或停用未发布的 V80 开发产物，继续从 `v70/612617b` 发布。P1 不需要修改生产配置或客户端订阅。

### 禁止事项

- 禁止在拆分过程中顺便改算法、返回结构或用户文案。
- 禁止构建后自动部署、自动改索引或覆盖 V70 文件。
- 禁止引入运行时动态插件加载或多文件发布依赖。
- 禁止为追求模块纯度破坏 Python/FongMi 运行时兼容。

## 6. V80-P2：统一资源引擎

### 目标

把多源资源规则收敛为可验证的归一化流水线，并以影子结果证明新引擎可替代 V70 逻辑。

### 依赖

P1 全部门禁通过，构建产物与 V70 行为等价。

### 工作范围

1. 在输入边界引入 `MediaIdentity`、`ResourceCandidate`、`EpisodeRange`、`PlaySource` 等明确模型。
2. 为 `vod1`、`vod`、`pansou`、`telegram` 建立静态 Provider Adapter。
3. Provider 只负责请求、登记过的 Schema 识别和数据归一化。
4. 抽离标题、年份、季号、集数、provider、去重、同盘补全和完整度规则。
5. 建立有冻结默认值的评分 Policy，保留可解释的拒绝原因和分数组成。
6. 建立缓存、最近成功线路、绑定线路、快速源、慢速补全的分层搜索。
7. 对同一固定输入并行运行 V70 和 V80 引擎，只记录差异，不立即接管输出。

### 交付物

- 统一模型和序列化合同。
- 四个静态 Provider Adapter 与 Schema Registry。
- 归一化、匹配、去重、评分和分层搜索测试集。
- 新旧引擎影子差异报告及批准记录。

### 验收

- V70 全部门禁继续通过。
- 固定 Provider 样本、错误 Schema、超限数据和候选冲突均有 Golden/Contract 覆盖。
- 未登记 Schema 明确降级或失败，不任意猜测字段。
- 错误影视匹配率不得因重构上升；任何排序变化都能由评分构成解释。
- 未新增资源源，未改变公开 EXT 合同。

### 回退

通过开关或构建选择恢复 V70 资源路径；归一化模型可以保留在边界，但不得继续接管输出。

### 禁止事项

- 禁止一次性替换全部内部字典而没有边界适配期。
- 禁止把“模糊匹配更强”作为验收标准。
- 禁止运行时下载 Provider、执行外部代码或接受任意 Schema 猜测。
- 禁止在本阶段增加 115、夸克、UC 等新资源源范围。

## 7. V80-P3：可靠性与 History 同步

### 目标

使 TMDB、History、任一资源源或后台任务失败时，详情、播放和其他上游仍可独立工作。

### 依赖

P2 统一模型、Provider 边界和影子切换已验收。

### 当前工作包状态

2026-08-14 已完成 P3 首个 History 同步工作包的封板；2026-08-15 第九个 TimeoutBudget 与生命周期硬取消工作包完成后，P3 已完成本地工程阶段封板。目标上游已同步到 AList-TVBox `1.45.1`；相对 `1.45.0` 仅发布说明与 Native Image 反射配置发生变化，路由、DTO、鉴权、`Atvp.py` 和 `spring.jar` 合同未再次漂移。AList-TVBox `1.45.x` 已移除旧 `/history/{token}` 服务端实现，因此隔离 V80 路径使用 `/api/playback/*`，只在旧容器明确返回 `404/405` 时受控回退并重新登录。

History 工作包冻结 `site/spider_plugin` 三元身份、活跃 FongMi CID 重建、增量游标、完整快照、墓碑删除、导入后提交、重启 UID 重识别、降序游标 latest 重建、缓存异常关闭、轻量读取与完整同步 pending 隔离、History 上下文串行化和新旧认证令牌隔离。定向门禁为 `46 passed`，AList-TVBox `1.45.1` 上游合同通过；隔离候选为 `714878` bytes、SHA256 `4F293BF5D62A1AC10A287B0608556C6C449FB46B98CE0F9826DF4EDBA9AC5B26`，封板结果由 `work/v80-stage-gate-1451.json` 记录。

第二个 Reliability 工作包已完成实现并进入封板。它只建立结构化失败分类、Provider `_resource_api_get()` 的 HTTP/payload 异常映射，以及复用现有 `_atvp_deadline_timeout()` 的绝对 deadline 阶段分配；阶段 timeout 不得突破父 deadline，结构化错误优先，旧英文和中文诊断保留兼容回退。当前包不接管 History、TMDB 或通用网络层，不实现 retry/backoff、Circuit Breaker、Bulkhead、Health 或 Chaos，也不宣称端到端 TimeoutBudget。定向验证为 `259 passed / 7 skipped`；隔离候选为 `724277` bytes、SHA256 `6D590868B80950923F44A793A515A351EC9CC8FABC631EF7DD6DE5ED860C4099`，封板报告写入 `work/v80-stage-gate-1451-reliability.json`。

第三个 Retry/Backoff 工作包已完成实现并进入封板。它只正式化现有 ATVP urllib3 传输重试：`total/connect/read=2`、`status/other=0`、`backoff_factor=0.4`、GET-only、禁用 `Retry-After` 和状态码重试；Provider 绝对 deadline 预留最坏 `0.8s` backoff，禁止新增应用层 retry loop。旧版 urllib3 的兼容构造至少保留 V70 原有传输重试；无 deadline 行为保持不变。定向验证为 `278 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`；隔离候选为 `727368` bytes、SHA256 `3BF3D5C02A4ED67F48F852A78614528B123DE53D4C4B055D1FC588EF66C5A0AE`。本包明确不接管 HTTP 状态重试、重定向策略、端到端硬 wall-clock cancellation、Circuit Breaker、Bulkhead、Health、Chaos、History/TMDB 或通用网络层。

第四个 Provider Reliability 工作包已完成实现、三路复审和封板。它在 Provider `_resource_api_get()` 边界按 backend/mode 建立独立三态 Circuit Breaker、容量 `2` 的 Bulkhead 与有界 EWMA Health：连续 `3` 次瞬态失败后 open `30s`，half-open 只允许一个探针；瞬态失败严格限定为 timeout、DNS、TLS、transport、server 和 rate limit，拒绝以结构化 `circuit_open`、`bulkhead_rejected` 返回。backend 切换、重新初始化和 `destroy()` 都会重置控制器并推进代次，旧请求在准入和网络前二次校验，旧租约完成也不能改写新状态；租约 finish 使用独立锁保证恰好一次释放。现有 urllib3 继续独占重试所有权，没有新增应用层 retry loop。窄测为 `171 passed`，扩展定向为 `304 passed / 7 skipped`，简化、加固和规格复审均为零问题；隔离候选为 `738611` bytes、SHA256 `49106B27ED2F1824F9C9460464B200093BB243554EB4F023736FD28D7832AB76`，封板报告为 `work/v80-stage-gate-1451-provider-reliability.json`。

第五个 History 客户端事件队列工作包已于 2026-08-14 完成实现、第二轮三路复审和封板。活动队列固定上限 `256`，批量溢出进入受 `HISTORY_ROW_LIMIT` 约束的持久化 `deferred`，每轮最多 drain `8` 条；deferred 可跨重启恢复，并按账号 UID 与 `transition_pending` 隔离。相同身份的 upsert/delete 使用单调合并，重复批量同步不会清除同水位 deferred，满队列时允许更新已有 deferred 身份但明确拒绝真正的新身份。History 专项为 `31 passed`，P3 全域为 `249 passed`，构建与阶段定向为 `86 passed / 7 skipped`；第二轮简化、加固和规格复审的 Critical/High/Medium 均为 `0`。最终完整门禁 `17/17 passed`，pytest `1207 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，ATVP、FongMi 双运行时、分类参数和 AList-TVBox `1.45.1` 上游合同通过。隔离候选为 `776229` bytes、SHA256 `9A3008A774FACE213EDC337E3B92CDBF088C4A79CB8961D04DD24F133A02C5C6`；报告为 `work/v80-p3-1451-stage-gate-sealed-r2-20260814.json`，报告 SHA256 `151EEE6D0E2F9488AF66D0996040D220002513210F8116569478CD6EAE1B2580`。

第六个 Cache Health 工作包已于 2026-08-15 完成实现、交错线程回归、集中复审和封板。它将 TMDB JSON cache、Douban JSON/text cache、Spider History 快照的非阻塞刷新和通用后台 cache refresh 收敛到同一 stale/backoff 合同：仅 `None` 视为 miss，保持 inclusive TTL 与 `allow_stale=False` 语义，stale 立即返回并后台刷新，失败计数上限 `6`，退避为 `1/2/4/8/16/32s` 且受 `failure_ttl` 限制。failure state 仅存内存，持久缓存 schema、key 白名单和 `48` 条上限不变；代次检查与 payload/health 提交在同一锁内完成，旧代次任务不能回写。History 非阻塞刷新失败使用同一退避抑制重复刷新，且仍不影响播放。本包明确不接管 Provider circuit/bulkhead、资源缓存、Filter History cache、History 持久事件队列或 P4 安全范围。聚焦测试 `47 passed`，构建与阶段定向 `91 passed / 7 skipped`，完整门禁 `17/17 passed`，pytest `1259 passed / 7 skipped`，Macro A/B 各 `50000 equal / 0 different / 0 errors`，ATVP、FongMi 双运行时、分类参数和 AList-TVBox `1.45.1` 上游合同通过。隔离候选为 `781140` bytes、SHA256 `50572D6304283CE39AA17AA2F25D1ED3EE9CEE88BB4DEB1C5B81D06EC6D79FBE`；报告为 `work/v80-p3-1451-cache-health-stage-gate-sealed-20260815.json`。

第七个 Background Bulkhead 工作包已于 2026-08-15 完成实现、合并回归、集中复审和封板。三个 lane 及容量固定为 `resource_completion=10`、`history=1`、`route_probe=5`，只执行非阻塞准入。资源完成 lane 覆盖绑定线路替换、入口资源预热和补充资源搜索；History lane 覆盖后台快照/同步与手工 probe/sync；route lane 只覆盖后台线路预热。拒绝不会等待、排队或触发新重试；线程/执行器启动失败会释放租约并恢复原启动失败诊断。活动数与拒绝数按 lane 独立，重新初始化和 `destroy()` 推进代次，旧代次租约不能释放新代次容量。本包不接管 Provider bulkhead、前台搜索、History 持久事件队列、cache refresh 或 P4/V70 范围。简化审计发现的固定容量可配置和启动失败误报两个中等问题、并发测试轮询一个低风险问题已关闭；阶段门禁抽象化建议因扩大范围被拒绝。聚焦范围 `44 passed`，受影响回归 `81 passed / 2 skipped`，包级回归 `163 passed / 7 skipped`；最终完整门禁固定要求 `17/17 passed`、pytest `1308 passed / 7 skipped`、Macro A/B 零差异，并通过 ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 上游合同。隔离候选为 `786881` bytes、SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`；报告 `work/v80-p3-1451-background-bulkhead-stage-gate-sealed-20260815.json` 为 `71535` bytes、SHA256 `01E67933BC238319ECD064FC1527D6BAF36896A86E8A3729B48A759F43E639C9`。

第八个 Chaos/Recovery 工作包已于 2026-08-15 完成实现、包级回归和集中复审。它使用确定性虚拟时钟和本地故障夹具，覆盖 TMDB 500/timeout stale、PanSou timeout、History 401 强制重认证、History 500 播放隔离、AList 502、DNS 失败、IPv6 不可达、播放 URL 过期重签发、截断 JSON、现有流式超大 JSON 边界和旧生命周期任务，`12/12` 场景通过。固定恢复基线为 `0ms`、`1000ms` 或 `30000ms`；TMDB 冷启动/热缓存 `250ms / 0ms` 是合成传输延迟，不是实机基准。集中复审将 History 401/500 切到真实 AList-TVBox `1.45.1` `/api/playback/changes` 路径，固定验证 `GET -> POST login -> GET` 重认证序列，并在 History 故障后走实际 `followplay` 验证播放隔离；非预期异常只记录固定错误，不带入原始 URL 或凭据文本。聚焦回归为 `92 passed / 5 skipped`，P3 包级回归为 `446 passed / 7 skipped`，105 个受管文件敏感信息扫描通过。隔离候选仍为 `786881` bytes、SHA256 `694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`；封板证据由 `work/v80-p3-1451-chaos-recovery-stage-gate-sealed-20260815.json` 记录。本包不执行真实网络请求、真实 sleep、生产写入或部署；超大 JSON 只验证现有 stream 上限，统一响应安全属于 P4。

第九个 TimeoutBudget 与生命周期硬取消工作包已于 2026-08-15 完成实现、回归和本地阶段封板。`homeVideoContent`、分类、详情、搜索、播放和动作入口各自只建立一个有限根 scope；Douban JSON/text、TMDB、Provider、ATVP play/parse、History v1.45/legacy 与重认证子阶段继承父绝对 deadline，显式子 deadline 只能进一步收紧。请求 timeout 根据剩余预算、剩余请求阶段与既有 retry/backoff 计算，保留 urllib3 为唯一重试所有者，不增加应用层 retry loop。`init()`/`destroy()` 推进代次时取消旧 scope、阻止其进入下一传输阶段，并恰好一次关闭仍被跟踪的流式响应；旧代次不能关闭或污染新代次资源。三个后台 lane 使用独立有限 scope，不合并线程池、状态或预算。定向测试为 `148 passed`，P3 全域为 `379 passed / 986 deselected`；最终完整门禁为 `18/18 passed`、pytest `1365 passed`，Golden `15 equal / 0 different`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`，ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 上游合同通过。隔离候选为 `808647` bytes、SHA256 `9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9`；最终报告为 `work/v80-p3-1451-timeout-budget-stage-gate-sealed-20260815.json`。本包不接管 P4 的 URL、重定向、DNS/IP、响应、请求头和脱敏边界，不执行真实网络性能测试或部署。

公开 V70 仍为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`，其真实 History 联调证据仍对应 AList-TVBox `1.44.0`。九个 P3 工作包均未修改公开源码、根 `spiders_v2.json`、baseline manifest 或十个冻结 parts，也未部署 V80。Provider 熔断/并发隔离/健康评分、History 客户端事件队列、现有 cache stale/backoff 统一迁移、后台独立 Bulkhead、Chaos/恢复基线以及端到端 TimeoutBudget/生命周期硬取消均已关闭；P3 本地工程阶段至此完成，下一阶段为 P4 统一安全边界。

### 工作范围

1. 建立端到端 `TimeoutBudget`，避免多层超时简单相加（第九个 TimeoutBudget 工作包已完成）。
2. 为 TMDB、History 和每个 Provider 建立隔离的 Circuit Breaker 与健康状态。
3. 将现有失败缓存、退避和 stale cache 迁移到统一 Health 层（第六个 Cache Health 工作包已完成）。
4. 将 History 写入组织为客户端事件队列，包含 `pending`、`retry`、`ack`、`dead-letter`。
5. 先用客户端本地单调版本、播放进度和更新时间解决冲突，不假设服务端已支持新 `revision` 字段。
6. Provider 资源搜索 Bulkhead 与后台补全/History/线路探测的固定独立 Bulkhead 已由第四和第七工作包关闭；不扩大到前台搜索等待队列。
7. 线路健康由多次结果和时间衰减形成，不由单次成功或失败决定。
8. 覆盖超时、HTTP 500/401、DNS 失败、截断 JSON、旧生命周期任务等 Chaos 场景（第八个 Chaos/Recovery 工作包已完成）。

### 交付物

- Timeout、Retry、Backoff、Circuit Breaker、Bulkhead 的策略合同。
- History 客户端事件队列和冲突处理说明。
- 上游隔离与生命周期测试。
- Chaos 测试报告和恢复时间基线。

### 验收

- History 失败不影响播放。
- TMDB 失败时允许使用合规 stale cache，不清空已有追更状态。
- 单个 Provider 失败不影响其他 Provider。
- 旧初始化代次的任务不能写入新配置状态。
- 同一前台操作的子阶段不能突破根绝对 deadline，生命周期取消必须阻止下一传输阶段并关闭活动响应。
- 同一 History 事件重试不造成重复提交或进度倒退。
- 冷启动和热缓存性能分别记录，不用热缓存数据替代冷启动结论。

### 回退

按子系统恢复原 V70 的缓存、任务和 History 路径；Circuit Breaker 和队列不得成为无法关闭的单点依赖。

### 禁止事项

- 禁止要求服务端为 V80 新增字段或修改 AList-TVBox/FongMi 容器合同。
- 禁止把所有上游共用一个熔断状态或线程池。
- 禁止在播放器返回路径同步等待 History 网络写入。
- 禁止用无限重试掩盖死信和配置错误。

## 8. V80-P4：统一安全边界

### 目标

让所有外部 URL、重定向、响应、请求头和敏感信息经过统一且可测试的安全入口。

### 依赖

P1 模块边界、P2 数据入口和 P3 网络/健康路径已稳定。

### 工作范围

1. 定义 `trusted_backend`、`configured_internal`、`external_untrusted` 网络区域。
2. 允许用户明确配置的 AList/History 私网地址；外部资源、图片和重定向默认禁止未授权私网、回环与链路本地目标。
3. 每次重定向重新校验 scheme、hostname、DNS 结果、目标 IP 和跨域策略。
4. 保持固定 IP 连接下 Host、SNI 和证书校验合同。
5. 统一限制响应字节、JSON 深度、集合数量、字段长度、播放 ID 和 URL 长度。
6. 请求头采用白名单，敏感头不得无条件跨域传递。
7. Token、Cookie、密码、Authorization、签名 URL 和诊断内容统一脱敏。
8. 长期缓存不得保存完整认证响应、长期有效凭据或可复用签名媒体直链。

### 交付物

- 网络区域和 URL 决策表。
- 重定向、DNS/IP、头部和响应限制的统一策略。
- 威胁模型、敏感数据流图和脱敏规则。
- IPv4/IPv6、编码 URL、DNS rebinding、恶意 JSON 和超长输入测试。

### 验收

- 合法私网 AList/History 配置仍可用，未授权私网跳转被拒绝。
- 每跳重定向都重新验证，没有首次验证后绕过。
- 敏感字段不进入日志、Golden、诊断快照和长期缓存。
- 超大或恶意响应被有界拒绝，不耗尽内存或线程。
- V70 兼容门禁、播放头合同和真实网络回归继续通过。

### 回退

安全层出现误阻断时，只能回退到已验证的上一安全策略版本；不得通过全局关闭 TLS、SSRF 或响应限制解决。

### 禁止事项

- 禁止全面封锁私网，因为 AList/History 可以是明确配置的内部服务。
- 禁止全局 `verify_tls=false`、无限响应读取或跨域转发全部头部。
- 禁止在测试夹具、错误信息或发布文档中保存真实凭据和签名 URL。
- 禁止把未知 URL 自动提升为可信后端。

### 当前工作包状态

P4-1 Security Policy 已于 2026-08-15 完成本地封板。新增叶模块只冻结纯决策合同：`trusted_backend`、`configured_internal`、`external_untrusted` 三个网络区域；精确配置的内部后端允许私网、回环和链路本地地址；外部目标要求全部解析地址为 global；外部重定向不能进入内部区域，外部 HTTPS 不能降级为 HTTP，且每跳必须提交新的解析地址证据；跨域头部只保留固定白名单并移除凭据。该包不执行 DNS、网络请求、缓存、日志、retry、TimeoutBudget 分配或运行时拦截，也不宣称 JSON 深度、集合数量、元数据响应、字段限制、脱敏和签名 URL 缓存已完成。

策略模块为 `13919` bytes、SHA256 `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`，逐字节追加在 P3 TimeoutBudget 输出后；P4-1 隔离候选为 `822566` bytes、SHA256 `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`。策略专项 `42 passed`，完整门禁 `18/18 passed`、pytest `1412 passed`，Golden、Macro A/B 各 50,000 例、Chaos `12/12`、ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 合同通过；112 个受管文件敏感扫描零发现。封板报告写入 `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json`。该输出现作为 P4-2 route overlay 的固定输入。

P4-2 Route Security 已于 2026-08-15 完成媒体线路探测单调用族接入。现有 `_resolved_media_target()`、固定 IP 连接、Host/SNI、重定向循环、响应探测、TimeoutBudget 和 route executor 继续拥有原职责；P4 overlay 只增加目标/重定向判定与请求头过滤。精确配置的 ATVP/History origin 保持内部可用，外部目标全部解析地址必须为 global，外部重定向不能进入可信内部 origin，外部 HTTPS 不能降级，每跳重新解析，跨域使用固定头白名单。该包不触碰 Provider、History、TMDB 或通用 requests session，不新增 retry、transport、DNS cache、executor 或 timeout owner。P4-1 候选 `822566 / A1C922...` 成为固定输入，最终候选为 `823561` bytes、SHA256 `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`；封板报告路径为 `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`。P4 后续仍按一个调用族或一个统一响应边界推进，不把未接入范围假定为已完成。

P4-3 JSON Shape Policy 已于 2026-08-15 完成本地封板。新增叶模块只验证已经解析完成的 JSON 值：容器深度上限 `64`、值节点上限 `128 * 1024`、单个 list/dict 上限 `8 * 1024`，只接受 `None`、精确 `str/int/bool/float/list/dict`，拒绝 NaN/Infinity、非字符串 object key 和其他运行时对象。遍历使用迭代栈，错误只暴露固定 reason，不保留或回显被拒绝值；固定 mapping policy 不提供运行时配置面。该包不读取响应字节、不调用 JSON parser、不限制字符串/字段/播放 ID/URL 长度，也没有接入 Provider、History、TMDB、Douban、播放、缓存、日志、retry 或 TimeoutBudget。

P4-2 候选 `823561 / D8B2E0...` 是 P4-3 的固定输入；模块为 `2383` bytes、SHA256 `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`，P4-3 候选为 `825944` bytes、SHA256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`。策略专项 `12 passed`，当时 P4 专项 `64 passed`。共享工作树在 P4-3 独立完整门禁期间继续进入 P4-4，树稳定性检查正确拒绝了误封板；P4-3 的全部合同由下一段 P4-4 稳定门禁重新覆盖，失败的独立诊断报告不作为成功证据。

P4-4 TMDB JSON Shape 已于 2026-08-15 完成单调用族接入。overlay 只把 `Spider._request_tmdb()` 成功 `200` 的 `return data` 改为一次 `v80_validate_json_shape(data)`；`_json_response` 继续拥有解析和非 JSON 错误，`401/403`、`429`、其他非 `200` 判断顺序与文案不变，requests session、缓存、TimeoutBudget、stream 与 `close_tracked()` 所有权不变。shape rejection 由既有 finally 恰好一次关闭响应；overlay 不增加 reader、retry、cache、timeout 或 response-close owner，也不验证非 `200` payload。该包仍是解析后保护，不解决响应在 JSON parser 前的字节上限或字符串/字段长度。

P4-3 候选 `825944 / 8FB4EE...` 是固定输入；overlay 构建器为 `7094` bytes、SHA256 `768E3E0F7FAF4B9E055AFADA4608C919302BF57F741F4C329EDFFA218A8171D5`，最终候选为 `825969` bytes、SHA256 `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`。P4 专项 `74 passed`，P4-4 overlay 专项 `10 passed`，完整门禁 `18/18 passed`、pytest `1456 passed`，Golden、Macro A/B、Chaos、ATVP、FongMi 双运行时/分类参数和 AList-TVBox `1.45.1` 合同通过；118 个受管文件敏感扫描零发现。合并式简化、安全和规格审计无剩余问题，封板报告为 `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`。P4-5 只继续收口 TMDB 解析前响应字节与字段长度，不把 Douban、Provider、History 或通用 session 一次性抽象。

P4-5 TMDB Response Boundary 已于 2026-08-15 完成实现与封板输入冻结。新增 `tmdb_response_policy.py` 只定义不可变上限和纯字段检查：响应 `2 MiB`、object key `1024` UTF-8 bytes、string value `128 KiB`；遍历使用迭代栈，接受对象按 identity 返回，固定 `key_too_long` / `string_too_long` 原因不保存或回显被拒绝内容。overlay 只给现有 `_json_response()` 增加可选有界模式，并在 `_request_tmdb()` 传入既有 reader、`operation.deadline` 与 `close_response=False`；另外两个一参数调用保持 `response.json()` 行为，外层 `operation.close_tracked(response)` 仍是唯一关闭所有者。`401/403/429` 在读取前返回原固定错误，普通非 `200` 的超大/无效 JSON 回退原 `TMDB HTTP <status>`，成功响应按 `v80_validate_json_shape()` 后 `v80_validate_tmdb_json_fields()` 顺序验证。该包不新增网络、retry、cache、TimeoutBudget、parser、session 或 close owner，也不接入 Douban、Provider、History、播放或通用 requests 调用族。

P4-4 候选 `825969 / 4746D9...` 是 P4-5 固定输入；response policy 模块为 `1735` bytes、SHA256 `C2D56B1432AB66163591953BA0ACD532A71BE0D963984EAF78C31F70DF3BD375`，模块追加输出为 `827704 / 3CDCB55A...`，最终候选为 `829040` bytes、SHA256 `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`。P4 专项 `103 passed`，完整 pytest `1493 passed`，122 个受管文件敏感扫描零发现，Macro A/B 各 `50000 equal / 0 different / 0 errors`，Chaos `12/12`；完整门禁报告固定写入 `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`。下一 P4 包必须重新盘点一个单独调用族或一个统一脱敏/签名 URL 缓存策略的现有所有者后再立项，不得把剩余网络面一次性抽象，也不得修改公开 V70、根 `spiders_v2.json` 或十个冻结 parts。

P4-6 Diagnostic Redaction Policy 已完成候选实现、三轮限域审计与本地回归。纯 policy 的运行时入口固定输出 `4096` 字符，最多读取 `32` 个显式 secret、每项最多 `4096` 字符，并在 `4096 + 4096 - 1` 的固定窗口内先脱敏再截断；内部有界核心允许 stage report 使用固定 `12000` 输出，不向运行时增加配置面。覆盖 Authorization/Proxy-Authorization、Cookie/Set-Cookie、assignment、Bearer/Basic、URL userinfo、signed query、一次/双编码 query/path 结构名、play/parse/offline_download/p 路径、dict/list/tuple/key-value pair 和显式 secret 的 URL 编码变体。两锚点 overlay 只替换 `_short_error()` 与 `_diagnostic_event()` 接缝，event、level、error、trace、字段键和值均经 `_short_error`，stage-gate `_redact()` 直接加载同一受管 policy core，删除独立 URL/query/path/assignment 脱敏实现；`_sanitize()` 仅保留结构递归和敏感键整值掩码。

P4-5 候选 `829040 / 60B083...` 是 P4-6 固定输入；Diagnostic Redaction Policy 模块为 `9503` bytes、SHA256 `4A05F0910BEF7FCFA70CFEAA4D25B5B9B05482150A004CB3AFF9D5C1CD17A831`，追加输出为 `838543 / 23023B88...`，最终候选为 `837931` bytes、SHA256 `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`。高相关构建/门禁回归 `252 passed`，P4 合并 `172 passed`，完整 pytest `1602 passed`；最终决策证据为 `work/v80-p4-6-diagnostic-redaction-decision-20260815.json`，封板报告路径为 `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`。本包未新增网络、I/O、retry、cache、transport、TimeoutBudget、session、response-close 或生命周期 owner，公开 V70、根 `spiders_v2.json`、十个冻结 parts 与生产部署均保持只读。P4-6 封板后仍按一个现有 owner/调用族一个工作包推进，不提前进入 P5。

P4-7 Douban JSON Response Boundary 已完成本地封板。8 个无凭据 fixture 冻结集合、推荐/筛选、两种搜索、详情和三种动作响应；规范序列化最大样本为 `561` bytes，按最大 50 条页面保守放大为 `28050` bytes，因此固定 `512 KiB` 响应上限仍保留约 `18.69x` 余量，并且不复制独立 TMDB 调用族的 `2 MiB`。新叶 policy 只提供不可变 `max_response_bytes`；两锚点 overlay 只接管 `_DoubanClient.request_json` 与 `_v80_action_unbounded` 的想看 POST，复用 `_read_bounded_json_shared()`、`_json_response()` 有界模式、`v80_validate_json_shape()`、当前 `operation.deadline` 以及既有 session/retry/cache/stale/close owner。非 `200` HTTP、登录失效和动作消息顺序保持；Douban HTML、redirect、signed URL cache、Provider、History、播放、P5 和新 parser/reader/retry/cache/timeout/close owner 均明确排除。

P4-6 候选 `837931 / AF00837D...` 是 P4-7 固定输入；Douban policy 模块为 `251` bytes、SHA256 `69C7AEF61E8724616A6621CF74C7686D702D34A8A6E3C207DB430D50301A4170`，追加输出为 `838182` bytes、SHA256 `91B9FB70EEC5B84E40A0E6DEB4DFFC1B0E599A5D3904263D885FABB2C180637C`，封板候选为 `839093` bytes、SHA256 `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`。正式门禁 `18/18 passed`、完整 pytest `1640 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`；决策证据为 `work/v80-p4-7-douban-json-response-boundary-decision-20260815.json` 与 `work/v80-p4-7-douban-json-response-fixture-decision-20260815.json`，封板报告为 `work/v80-p4-7-douban-response-boundary-stage-gate-sealed-20260815.json`。公开 V70、根索引、生产部署和 P5 均未接管。

P4-8 Douban HTML Response Boundary 已完成证据解阻与本地封板，仍只归属 `_DoubanClient.request_text` 单一 owner。2026-08-16 的一次授权、低频、无重定向且不落正文的 wishlist 观测返回 `200 text/html; charset=utf-8`，完整解压体为 `57197` bytes、SHA256 `AA28F4570F11493F8B9EBB19E6176E2A12368817F0371804CC6E2C442EADB0C9`，实际 parser 口径得到 `15` 个 grid item 和 `15` 个有效电影 subject，证明标准完整 15 条页面；证据不保存 URL、账号标识、标题或正文。结合 Top250 `64547` bytes 和最大 parser 投影 `12258` bytes，既有公式 `round_up_64KiB(max(16*P,4*O))` 选择 `256 KiB`，`selected_bytes=262144`。新增叶 policy 只定义该不可变上限，既有 streaming overlay 只在状态检查后按 `Content-Length` 与实际解压流双重计数，沿用 `response.text` 解码、TimeoutBudget deadline 和 exactly-once `close_tracked()`；P4-7 `839093 / B1F980E7...` 为固定输入，policy 为 `271 / DBBA0B73...`，追加后为 `839364 / A817548D...`，候选为 `840543 / 749F16F3...`。完整门禁 `18/18 passed`、pytest `1680 passed`、Macro A/B 各 `50000 equal / 0 different / 0 errors`、Chaos `12/12`，实现树 145 文件且门禁期间稳定；封板报告为 `work/v80-p4-8-douban-html-response-boundary-stage-gate-final-r2-20260816.json`。redirect、signed URL cache、Provider、History、播放、通用 session、新 retry/cache/parser/reader/timeout/close owner、公开 V70、根索引和部署仍明确排除。

AList-TVBox 当前上游源码合同已于 2026-08-16 更新到 `1.48.0`。`1.46.1` 的播放同步扩展和 `1.47.1` 的网络直播关注继续作为历史兼容层；`1.48.0` 相对 `1.47.1` 为 7 个提交、34 个文件，范围是虎牙/斗鱼/B站/抖音实时弹幕、弹幕配置和快手播放修复。`Atvp.py`、History、`PlaybackSyncInput` 与 `PlaybackSyncService` 的 Git blob 未变化，项目按 `1.45.0 -> 1.45.1 -> 1.46.1 -> 1.47.1 -> 1.48.0` 叶验证器链固定 tag commit、精确 delta、clean worktree、JAR/DEX 指纹与续播 markers；当前 1.48.0 叶合同为 `24/24`，报告 `work/v80-upstream-1480-source-contract-20260816.json` 的 SHA256 为 `BA37264DE2FDEFD13A1F13E2B221EC69982561151F10DBE1B149CF04F10D4E83`。详见 `docs/ALIST_TVBOX_1461_SOURCE_DELTA.md`、`docs/ALIST_TVBOX_1471_SOURCE_DELTA.md` 与 `docs/ALIST_TVBOX_1480_SOURCE_DELTA.md`。源码证据不等同于弹幕、快手、直播关注或 Python History 多级恢复的服务器/客户端实机联调。

## 9. V80-P5：可观测性与正式发布

### 目标

使一次搜索到播放和 History 的链路可定位、可脱敏复现，并完成 V80 发布候选验证与受控晋升。

### 依赖

P1 至 P4 全部门禁通过，无未解决的关键或高风险审计项。

### 工作范围

1. 统一 `request_id`、`trace_id`、`media_id`、`provider`、`episode` 等关联字段。
2. 建立稳定 Error Code，用户提示与诊断细节分离。
3. 记录缓存命中、阶段耗时、候选拒绝原因、评分构成、熔断状态和最终选择。
4. 输出不含凭据的 Diagnostics Snapshot。
5. 执行性能基准、长时间运行、反复初始化和真实设备联调。
6. 使用私有开发插件 ID 或私有索引灰度，不覆盖 V70 公共入口。
7. 发布候选经人工批准后，才原子更新源码、索引、文档和 `v80` 标签。

### 当前原子工作包：P5-5 内容寻址续跑与 1.50.0 上游合同

P5-1 已冻结可观测性数据合同但不接入运行时。事件与快照 Schema 固定为 `v80-diagnostic-event/1` 和 `v80-diagnostics-snapshot/1`，快照最多 `256` 条、文本最多 `512` 字符；core/context/measurement 字段顺序、level/stage 闭集和 16 个 P3 failure kind 的唯一稳定 Error Code 均由一个纯叶模块拥有。P4-8 候选 `840543 / 749F16F3...` 是 P5-1 固定输入；policy 模块为 `2138` bytes、SHA256 `FDFA66B624DD9C5405A77B8FAAC1D2A3973B83AB7EBFB241AFBC99319AAE4C59`，封板候选为 `842681` bytes、SHA256 `19A5FFA67ADA386585DA663AD1C7FD91FEC04322903EE207602FE2A4CC082A73`。最终报告 `work/v80-p5-1-observability-policy-stage-gate-final-r2-20260816.json` 记录 `18/18 passed`、pytest `1711 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `146/0` 和 `admit=true`。

P5-2 只把 P5-1 Schema 接入既有私有 `_diagnostic_event()` buffer。事件、脱敏、operation 和时间来源继续分别由 `_diagnostic_event()`、P4 `_short_error()`、P3 `TimeoutBudgetController` 和既有 event `time.time()` 调用拥有；新增生命周期内单调 scope 序列，顶层 scope 获得不可逆 `request_id`/`trace_id`，嵌套 scope 继承根 trace。reset、cancel、generation mismatch 或 finished scope 使关联上下文失效；调用方字段不能覆盖 Schema、stage、关联 ID 或稳定 Error Code；无效、负数、NaN、Infinity 耗时不进入 `elapsed_ms`。6 个固定 insertion 以 P5-1 `842681 / 19A5FFA6...` 为输入，形成 `848247` bytes、SHA256 `510D4CFEC01457AB6A264A7AF35204E87F6A2814F0A8028A9C2B9437317AB873` 的隔离候选。overlay 定向 `29 passed`，构建与 stage-gate 关键链 `26 passed`；三路审计发现的保留字段覆盖、地址复用、陈旧线程栈和耗时类型边界均已关闭。完整门禁记录 `18/18 passed`、pytest `1764 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `149/0` 和 `admit=true`；最终受管文档 closure 写入 `work/v80-p5-2-runtime-correlation-closure-final-20260816.json`。本包不生成 Diagnostics Snapshot，不增加网络/I/O/时钟、缓存、重试、日志或快照框架。

P5-3 只升级现有私有 `_diagnostic_snapshot()`：输出固定为 `v80-diagnostics-snapshot/1` 的 `schema/count/events`，`None` 或非法 limit 使用策略上限，数值夹到 `1..256`，事件保持旧到新，返回 list 与 event dict 脱离内部 buffer。它不新增公共/认证端点、持久化、上传、时钟、第二 buffer、dropped counter、二次脱敏、缓存、线程、日志或 snapshot event。安全审计发现 P5-2 event 返回值与内部 buffer 共用同一 dict，现由原 `_diagnostic_event()` owner 返回 `dict(payload)`，既阻断入站脱敏后的回写污染，也避免在 P5-3 引入深拷贝或第二次 redaction。历史 P5-2 封板产物继续为 `848247 / 510D4CFE...`；P5-3 当前加固中间态为 `848253` bytes、SHA256 `5B9C10F2EC877DEEF1302DCA35ABADC8BB65063EF33F0EA9698120DD96AD964C`，最终候选为 `848431` bytes、SHA256 `30EBACE80D845AA5E743EDC5AACB7DDD11A7D314A006A32F5A8B45CD8B87A409`。两轮三向审计已关闭事件引用逃逸和未固定 resume 报告可伪造复用两项高风险问题；`--resume-from` 现强制受信 SHA256 pin。完整门禁记录 `18/18 passed`、`18 executed / 0 reused`、pytest `1784 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `152/0`、稳定实现树 `154 / 221363D790E1CCA2E3A95470D749248883213DF282061CDD9204AC53EC86CC25`、`admit=true` 和 `795.351s`；证据为 `work/v80-p5-3-diagnostics-snapshot-closure-20260816.json`，最终受管文档 closure 路径固定为 `work/v80-p5-3-diagnostics-snapshot-closure-final-20260816.json`。

P5-5 不增加通用缓存或自动依赖推断。18 个固定步骤继续使用显式输入和 DAG 失效传播；旧报告只读，新 closure 单独生成。FongMi requirements 候选与真实 dual-runtime verifier 统一为 `exists()` 语义：所有存在候选进入内容指纹，目录/读取失败使 scope 无效，零候选 fail-closed；失败由 `dual_runtime` 传播到 output admission 和 V70 source lock。修复前 `work/v80-p5-5-upstream-1471-closure-final-20260816.json` 的 `15/18 passed` 与 pytest `1801 passed` 只证明闭包传播，不能作为绿色封板。四代 verifier 单测为 `25 passed`，受影响 stage 单测另为 `4 passed`。45 秒静默双指纹后生成的唯一完整 baseline `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json` 为 `18/18 passed`、`18 executed / 0 reused`、pytest `1811 passed`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、敏感扫描 `158/0`，稳定实现树 `160 / FE835719DD2CF3FF6B259A75D23F2F63EFE47BECDF2B96F2E9310B681301149C`，`admit=true`、V70 source lock 通过，耗时 `824.449s`，无生产写入或部署。该 baseline 的受信 resume pin 为 `14AA4142678A71B0B64B1B9F86EE2BA6A6C9666AC1942997172B8A762476FFFD`；后续受管文档变化只执行 DAG 失效闭包，不重跑完整 gate。

2026-08-18 已把当前上游精确叶子继续推进到 `1.50.0 / 7ba1119e1e71bb427fb281f534a4c111ff7b500c`。相对 `1.48.0` 的变化恰好为 `20` 个路径；Atvp/raw 与七个播放同步 owner blob 保持不变。新叶单测 `9 passed`，全部版本化上游验证器及 stage-gate 单测 `284 passed`。由于 `tools/run_v80_stage_gate.py` 是全部 18 步共同的 `gate_tool` 输入，本次叶子选择与指纹接入使旧 closure 全部失效，因此只执行一次必要的新基线，不削弱内容指纹或扩建兼容缓存。正式报告 `work/v80-upstream-1500-complete-closure-20260818.json` 为 `18/18 passed`、`18 executed / 0 reused`、pytest `2133/2133`、Macro A/B 各 `50000/0/0`、Chaos `12/12`、稳定树 `182 / 4B33C067BD84404B5372BA0CDB419575BBF795D8D2285217B4CDD0FBBD724FFD`、`admit=true`，耗时 `2210.101s`，SHA256 `8FF99EC165D302DB425C4636CF2671CD202D05E4E90A6E74C5471D2D62E38194`。候选保持 `862377 / C1ACAB...481B7D`，公开 V70 与生产状态未变；下一阶段只推进 P5-6 私有灰度、服务器/MuMu/FongMi 验证、人工批准和私有生产晋升，不执行 V70 原子回退。

### 交付物

- 诊断事件 Schema、Error Code 目录和脱敏快照。
- 性能、稳定性、兼容性、安全与实机联调报告。
- V80 发布候选单文件、指纹、变更说明和私有部署撤回记录。
- 原子发布清单。

### 验收

- 一次搜索、匹配、详情、探测、播放和 History 链路可由同一 trace 关联。
- 诊断信息足以定位阶段失败，但不包含 Token、Cookie、密码、Authorization 或完整签名 URL。
- 500+ 测试可作为增长目标，但合同覆盖、风险覆盖和确定性优先于数量。
- “详情 <300ms”只允许声明为热缓存首屏目标；冷缓存网络搜索必须单独记录。
- AList-TVBox 与 FongMi 双运行时、分类参数和实机链路全部通过。
- 发布前再次确认 V70 标签、公开源码和根索引未变化；V70 不作为私有 V80 的原子回退事务。

### 私有部署撤回

发布前可直接丢弃候选。私有部署后只撤销私有 V80 站点/插件条目或恢复上一份私有配置，并复核私有运行时 SHA256；公开 V70 源码、`version: 70` 根索引和公共订阅始终不变，不执行 V70 原子回退。

### 禁止事项

- 禁止仅凭自动化测试数量宣告 V80 可发布。
- 禁止在没有私有灰度和实机证据时替换公共入口。
- 禁止只更新源码而遗漏索引、README、STATUS、DEPLOYMENT、CHANGELOG 或标签。
- 禁止构建命令直接执行 Git 推送、仓库导入、容器刷新或客户端订阅更新。

## 10. 分层验证与审计节奏

验证按改动风险分三层执行，避免每个局部修改都重复完整门禁和三路审计。

2026-08-15 已完成本地测试效率基线修正：overlay 参数化测试按模块复用一次完整 V80 构建，阶段门禁篡改用例复用同一真实构建证据；没有删除测试、断言或兼容门禁。完整 pytest 从 `1424.88s` 降至 `144.56s`，阶段门禁单测从 `302.34s` 降至 `63.54s`。本地固定使用 Python `3.12.13`、pytest `8.4.1`、requests `2.32.4`、lxml `6.1.1` 和 paramiko `4.0.0`；`tools/run_v80_stage_gate.py` 自动接入 `work/python-test-deps` 并记录最慢 30 项，避免依赖临时 `PYTHONPATH`。这些优化只消除重复构建和环境漂移，不降低验证范围。

### 编辑循环

每次代码修改只执行：

1. Python 语法/导入检查。
2. 受影响模块单元测试。
3. 若修改构建或 manifest，再检查 V70、开发产物和 vendor 指纹。

编辑循环不得用窄测宣告宏批次或阶段完成；发现回归必须在当前循环修复或回退。

### 宏批次封板

一组紧密相关职责完成后执行：

1. 全部 P2 定向测试和 15 项 V70 Golden/Contract。
2. 行为、匹配、排序、序列化或运行时调用路径发生变化时，执行固定 seed 的 50,000 组差分；仅文档、测试断言或门禁元数据变化不重复执行该差分。
3. 单文件构建可重复性、Spider/Filter 重复方法、逐 part 指纹和敏感信息扫描。
4. 一次合并式简化、加固和规格复核，记录接受、修正和拒绝的建议。

### 阶段与高风险边界

只有以下边界运行完整项目门禁和三路独立审计：

1. 首次接入运行时调用点。
2. 网络、并发、缓存、生命周期或安全边界发生结构性变化。
3. V80 开发链首次接管输出或改变回退路径。
4. P2 至 P5 各阶段最终封板和公开发布候选。

完整门禁包括 V70 全量回归、Golden、AList-TVBox direct-play、FongMi direct-PY、FongMi category/extend、AList-TVBox 源码合同、敏感信息扫描、单文件构建和 V70/V80 行为差异。三路审计仍分别覆盖无必要复杂度、安全/并发风险和规格完整性，但不在同一宏批次的每个小修正后重复启动。

每个阶段验收后形成不可变的里程碑提交，建议使用内部 `v80-p1` 至 `v80-p5` 标记；这些标记不等于公开发布。

## 11. 发布隔离与私有晋升

开发期必须保持以下隔离：

| 对象 | V70 公开链 | V80 开发链 |
| --- | --- | --- |
| Git | `v70` / `612617b` | `v80-dev` 及阶段里程碑 |
| 插件 ID | `douban_tmdb_follow_single` | 私有开发 ID 或不进入容器 |
| 索引 | 根 `spiders_v2.json`，`version: 70` | 私有开发索引或本地产物 |
| 源码入口 | `py/豆瓣TMDB追更单入口.py` | 独立开发构建输出 |
| 部署 | 公开 V70 保持原状 | 仅进入私有容器、私有插件 ID 或私有配置 |

V80 私有晋升必须作为一次受控事务完成：

1. 冻结并复核候选提交。
2. 完成所有门禁、私有灰度和实机联调。
3. 生成候选单文件并记录大小、SHA256 和测试证据。
4. 经人工批准后，只更新私有索引/配置和对应 README、DEPLOYMENT、STATUS、CHANGELOG；公开源码与根 `spiders_v2.json` 不变。
5. 固定候选提交、报告 SHA256 和私有配置指纹，不创建或移动公开 `v80` 标签。
6. 私有容器刷新和客户端私有配置刷新后，验证实际运行时版本与 SHA256。

V80 仅作为私有部署目标；整个流程都不得改变公开 V70。

## 12. 执行记录

### 12.1 当前执行点（2026-08-18）

当前只处理真实阻断，不扩建通用防御框架。raw-row-preserving 分层组合器和 private-V80-only controlled switch 已完成本地接管验证：前台与背景共用 `_resource_output_candidate_order`，默认关闭，combiner 异常只单次回退旧 owner。当前候选为 `870797` bytes、SHA256 `0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9`；Macro A 为 `50000` 例、`14736` 个受控差异、`0 errors`，Macro B 为 `50000 equal / 0 different / 0 errors`，Chaos `13/13`，三项源码级兼容门禁通过。独立 `private/v80/` 已生成 `id=douban_tmdb_follow_single_v80_private`、`version=80`、私有索引和 staging；staged source 为 `870801 / 049C722515F6851C379969C2886FA466EDD9FC9478B6B6F591E757DEEEDDCB97`。下一阶段只做静默双指纹、变化节点 DAG closure 和私有运行时验证；禁止新增通用 redirect、session、cache、retry、executor、并发或跨项目框架。

1.50.0 追加封板现作为当前上游源码基线：`work/v80-upstream-1500-complete-closure-20260818.json` 为 `18/18 passed`、pytest `2133/2133`、稳定树 `182 / 4B33C067...24FFD`、`admit=true`，报告 SHA256 `8FF99EC165D302DB425C4636CF2671CD202D05E4E90A6E74C5471D2D62E38194`。后续 r4 文档 closure 固定为 `6 executed / 12 reused`、稳定树 `182 / 71EBA399...8F91`、报告 SHA256 `4CFABE8441BD769BAB4A4246EF1B6BF5B03609E56E4E659176180A6B4538C9C5`；两者均是当前候选之前的受信基线，不替代本轮新 closure。

当前发布边界按用户最新指令固定为：允许私有部署 V80，使用 MuMu 已安装的 FongMi 版本刷新私有配置，不另外安装新版；公开 V70 始终保持不变，取消 V70 原子回退。

### 12.2 历史执行记录

V80-P1、P2-1 至 P2-19 和 P2 宏批次 A 已于 2026-08-14 完成本地验收。宏批次 A 将固定九模块 shadow vendor 装配到隔离 V80 开发产物，并通过六个固定锚点接入 `_schedule_supplement_resource_search.worker`：生命周期初始化与重置、独立零默认预算、代际采样状态，以及生产提交和 job/admission 清理完成后的唯一后台调用点。调用保持锁外执行、默认关闭，不读取或消耗生产详情验活/资源搜索预算，不写入共享 `_resource_candidates`，不进入前台详情、bound replacement 或 entry preheat，也不改变任何用户输出。

冻结 V70 继续为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`。九模块 vendor 为 `18459` bytes、SHA256 `F8C118103A09AC67F8CE8DBE5F7DCD7891D40F81222CD28A4BF59223E7E1603D`，闭包 SHA256 `F8F41A158F8457E3538339D99B42F8D51B9402FD5D1AA2062329A1D6B168FC26`；六锚点 overlay 输入为 `635158` bytes、SHA256 `A1C0957059721AA89304B19D21E157BC0967C878E2CF383565F8B8DD7792543F`；最终开发产物为 `636475` bytes、SHA256 `809CB654A74DEC0364A62FE8D43FFA1BC72A43ECADD0575CCD479EFB78755FFB`。开发 manifest 仍保持 `version: 70`、`index_contract: none`，十个冻结 parts、baseline manifest、公开源码和根索引均未修改。

宏批次 A 集成测试为 `64 passed / 2 skipped`，全部 P2 定向与 Golden 为 `479 passed`；固定 seed `8020` 的 50,000 组运行时差分为 `50000 equal / 0 different / 0 errors`，覆盖十种场景、30,000 次实际 shadow 调用、四种决策结果、三种 report 状态、过时代际、重复任务和提交失败，关闭状态下实际 shadow 调用为零，报告保持脱敏。完整门禁为 `813 passed / 2 skipped`，13 个必需步骤、15 项 Golden、71 个受管文件凭据扫描及 ATVP/FongMi/AList-TVBox 合同全部通过。初审发现的预算准入前复制全部 rows 问题已通过传递 worker 私有列表引用修正，并增加禁止准入前物化的回归；最终简化、加固和规格审计均无剩余问题。最终报告为 `work/v80-p2-macro-a-stage-gate-final.json`，SHA256 `948A9AA87A7B4A2AFE12D11981B3C4F6CBD9B52948C1A6D04B2C291C710587EC`；差分报告为 `work/v80-p2-macro-a-differential.json`，SHA256 `24A40E0CE1B2C6DD81337295B3F9D53763E34D58CB72F92C4FC246E105765F0E`。门禁记录 `production_writes=false`、`deployment_attempted=false`。

下一执行点为宏批次 B：收敛 `vod1`、`vod`、`pansou`、`telegram` 的固定 Provider/Schema 边界，并建立缓存、最近成功线路、绑定线路、快速源和慢速补全的分层搜索。B 继续保持 shadow-only，优先复用 V70 已有请求、线程、预算和缓存合同，不新增资源源、不引入通用插件框架，也不提前接管输出。每次编辑只运行语法和受影响窄测；工作包封板执行相关 P2 定向、必要差分和一次合并复核；只有实际跨越网络/并发/缓存结构或输出接管边界时才升级为完整门禁和三路独立审计。宏批次 C 仍负责 shadow 证据、开发链受控切换、V70 源码锁定与 V80 开发输出隔离验证和 P2 阶段封板；P3 至 P5 不得提前接管业务路径。

宏批次 B 的 B1 固定 Provider/Schema 边界已于 2026-08-14 完成。`resource_provider.py` 显式登记且只登记 `vod1`、`vod`、`pansou`、`telegram` 四个 Adapter；每项冻结实际端点、V70 搜索/详情参数、允许的 payload/row Schema，并复用现有 `map_resource_payload` 归一化合同。未知模式抛出明确错误，未登记 Schema 返回空结果，不执行网络、线程、缓存或运行时注册。初次实现中的生成式注册表已在合并复核中改为显式四项常量，最终无剩余简化、加固或规格问题。B1 定向封板为 `103 passed`，P2 DAG 和 73 个受管文件敏感信息扫描通过；开发产物仍为 `636475` bytes、SHA256 `809CB654A74DEC0364A62FE8D43FFA1BC72A43ECADD0575CCD479EFB78755FFB`，冻结 V70 指纹不变。下一工作包 B2 建立纯分层搜索计划，先表达缓存、最近成功、绑定、快速源和慢速补全的顺序/准入，不执行 I/O，也不接管现有 `_resource_candidates`。

宏批次 B 的 B2 纯分层搜索计划已于 2026-08-14 完成。`resource_search_plan.py` 只接受本地层可用状态和固定 Provider 模式，输出不可变步骤序列：`cache -> recent_success -> binding -> vod1 -> vod -> pansou -> telegram`；`vod1`/`vod` 标记为快速 Provider，`pansou`/`telegram` 标记为补充 Provider。输入模式按 B1 固定注册表归一化、去重并恢复冻结优先级，未知模式明确拒绝；计划本身不选择线程、不发请求、不读写缓存，也不改变 V70 当前绑定与搜索行为。B2 定向封板为 `108 passed`，P2 DAG 和 75 个受管文件敏感信息扫描通过，V70 与 V80 构建指纹不变；合并复核无剩余问题。下一工作包 B3 以注入的本地候选和 Provider payload 组合纯 shadow 分层结果，不接运行时调用点。

宏批次 B 的 B3 纯 shadow 分层组合已于 2026-08-14 完成。`resource_search_shadow.py` 接受已经归一化的 cache/recent_success/binding 候选和 B1 固定 Provider payload，按 B2 计划输出不可变 `LayeredResourceBatch`；本层不跨层去重、不评分、不调度，也不把 V70 原始 dict 隐式转换为新模型。省略 `available_modes` 时从 payload 键推导，显式空模式则严格禁用 Provider，避免“关闭搜索”被误解释为自动发现。B3 定向封板为 `114 passed`，P2 DAG 和 77 个受管文件敏感信息扫描通过，V70 与 V80 构建指纹不变；最终合并复核无剩余问题。

Macro B 的运行时接入候选点冻结为 `_resource_candidates`：位于各模式结果收集、补充缓存合并和绑定候选追加之后，现有 `_resource_fair_candidate_order` 之前。该位置已经完成全部 V70 I/O，可以在默认关闭和独立预算下构造 shadow 分层输入，不需要增加请求、线程池、缓存写入或网络状态。下一工作包 B4 先建立 V70 原始候选行到 `ResourceCandidate` 的纯适配和层归属，再决定固定 vendor/overlay 变更；在 B4 封板前不修改运行时产物。

宏批次 B 的 B4 V70 行适配已于 2026-08-14 完成。`resource_search_v70_adapter.py` 使用冻结的 row identity 将 `_resource_candidates` 已收集行按 `cache -> recent_success -> binding -> provider` 优先级分类，再复用 B1/B3 生成类型化分层批次；缓存 URL 的编码/解码等价、最近线路与绑定冲突、未知模式拒绝、空 Provider 批次保留及输入不可变均有覆盖。本层不执行请求、锁、缓存访问、评分或调度。B4 定向封板为 `158 passed`，P2 DAG 和 79 个受管文件敏感信息扫描通过，V70 与 V80 构建指纹不变；合并复核无剩余问题。

固定 vendor 可装配性只读审计确认 B1-B4 的顶层符号与冻结 V70 零冲突；新模块之间仅 `_text`、`_mode`、`_first` 三组私有 helper 重名。下一工作包 B5 只对这三组 helper 做模块前缀收敛并扩展固定 vendor closure，不引入通用 bundler、动态命名空间或运行时注册。B5 closure 独立通过后，B6 才在已冻结的 `_resource_candidates` 位置加入默认关闭、独立预算的 shadow-only overlay，并执行 Macro B 定向、必要的 50,000 差分和一次合并复核。

宏批次 B 的 B5 固定 closure 装配已于 2026-08-14 完成。`resource_models.py`、`resource_schema.py`、`resource_shadow.py`、`resource_provider.py` 的重名私有 helper 仅增加模块前缀；原九模块 vendor 后按依赖顺序追加 models、schema、shadow、provider、search plan、search shadow 和 V70 adapter，形成固定十六模块闭包。未引入通用 bundler、动态命名空间、运行时注册或新调用点。扁平化后的 V70 分层适配与源码等值，十六模块内部及冻结 V70 顶层命名空间均零冲突；相关定向封板为 `169 passed / 2 skipped`，P2 DAG、79 个受管文件敏感信息扫描和隔离构建通过。vendor 为 `58319` bytes、SHA256 `04A308757A40179B5F38170185E5669983BABE134E00521C3B75100E2CFD1588`、closure SHA256 `8F13F7D449CFD866A3B18AA26395AAD00BAD79C94425454CF95306AD72190D9D`；overlay 输入为 `675018` bytes、SHA256 `ECA4327D65B7442873BF7FF10FE73417FE07DFFCE4C7E0E65128B9CBD1285C35`；最终开发产物为 `676335` bytes、SHA256 `31A32AF22A883957DAF70333A3A7089760EA0ED05DE4FFE84E844AE349E36015`。六个 Macro A overlay 锚点和运行行为保持不变，新增七模块尚无运行时调用点；按分层验证规则，本批未重复 50,000 差分、完整门禁或三路独立审计。B5 封板时已将后续 B6 限定为冻结 `_resource_candidates` 接缝上的默认关闭、独立预算 shadow-only overlay；该工作现已按下一段记录完成。

宏批次 B 的 B6 分层搜索 shadow overlay 已于 2026-08-14 完成。新增 `resource_search_shadow_runtime.py`，只记录 layer、mode、数量和错误类型；它拥有独立开关、零默认预算、稳定采样代际、锁和最后报告，不持久化资源 ID、标题或 URL。第八个固定 overlay 锚点位于 `_resource_candidates` 完成全部 V70 I/O、缓存/最近成功/绑定行组装之后和 `_resource_fair_candidate_order` 之前；关闭或异常时不改变 V70 输出。初始化和 `destroy()` 均推进代际并清空分层采样/报告状态，旧代执行不能回写。十七模块 vendor 为 `61679` bytes，SHA256 `53C6A87F2CFF65C4B9FABADF800D3D0F2291D90E3122174699F1DA4C2C8EF857`，closure SHA256 `BD591DFEC19FA242F779AE93EBC9B01EB2787A63C25CECFBF0319D682DF355E8`；overlay 输入为 `678378` bytes，SHA256 `3A8AD7ADB62372858A03E6B3790C85B6F17336CC8C00029B0E485A9E9593C253`；最终开发产物为 `681512` bytes，SHA256 `52C9ABA52F9572790B268CF0DB95B4302952EE3CACA9A4ED337CA843E69F92BE`。P2、Golden、构建和阶段门禁定向为 `584 passed / 2 skipped`，82 个受管文件扫描、P2 DAG、ATVP direct-play、FongMi direct-PY 和分类参数合同通过。Macro A 与 Macro B 各 50,000 例均为 `50000 equal / 0 different / 0 errors`；Macro B 覆盖十种场景、40,000 次 shadow 调用、5,000 次合成异常和 25,000 份脱敏 observed 报告。一次合并审计发现并关闭 `destroy()` 未清空分层观测状态的问题，复核后无剩余问题。未运行完整项目门禁或三路独立审计，未修改公开 V70、根索引或冻结 parts。随后执行的 Macro C-C1 已按下一段完成。

宏批次 C 的 C1 受控输出准入合同已于 2026-08-14 完成。新增叶子模块 `resource_output_admission.py`，只在独立开关和 development build、candidate shadow、layered shadow、ATVP、dual runtime、FongMi category、公开 V70 锁定、公开输出未触碰八项证据均为字面量 `True` 时返回 `{"admit": true, "reason": "admitted"}`；否则按固定顺序返回首个未满足原因。该模块不读取或重解析报告，不执行 I/O，不持有运行时状态，也不进入十七模块 vendor、overlay、冻结 parts、开发产物或公开输出。工作包合并运行 P2、Golden、构建和阶段门禁定向，结果为 `639 passed / 2 skipped`；P2 DAG 和 84 个受管文件扫描通过，V70、vendor、closure、overlay 输入及开发产物指纹全部保持 B6 原值。一次合并式简化、加固和规格审计为 `findings=0`。由于 C1 是未调用的纯策略，本包未重复 50,000 差分、外部兼容门禁、完整项目门禁或三路独立审计。C2 已在下一段接入隔离开发链 dry-run，未修改公开 V70 输出。
宏批次 C 的 C2 隔离 dry-run 接入已于 2026-08-14 完成。阶段门禁新增 `output_admission_dry_run` 步骤，只汇总当前内存中的结构、DAG、敏感扫描、构建、Golden、pytest、vendor、Macro A/B、ATVP、双运行时、FongMi 分类和 V70 标签证据，再调用 C1；不读取或解析外部报告，不接入 vendor、overlay、冻结 parts 或公开输出。完整证据返回 `passed` 与 `admit=true`；partial/跳过证据返回 `skipped`，真实失败、写入或部署标记返回 `failed`。缺失/重复证据以及策略加载或返回形状异常均被隔离为明确失败原因。C2 工作包合并定向为 `653 passed / 2 skipped`，P2 DAG 和 84 个受管文件扫描通过，V70、vendor、closure、overlay 输入和开发产物指纹保持 B6 原值。一次合并式简化、加固和规格审计为 `findings=0`。本包未运行完整 50,000 差分、外部兼容门禁或部署；下一执行点为 C3 源码锁定与开发输出隔离验证和 P2 封板准备。

宏批次 C 的 C3 V70 源码锁定与 V80 开发输出隔离验证及 P2 阶段封板已于 2026-08-14 完成。阶段门禁新增 `v70_source_lock`，只读核对 V70 标签、baseline manifest、公开源码字节/大小/SHA256、根索引唯一 `version: 70` 记录、隔离的 `build/v80-dev` 输出、C2 公开输出未触碰证据以及零生产写入/零部署尝试；V70 已有独立源码留存，本阶段不计划恢复、回退、部署或公开切换。封板审计同时关闭两个 P1 假通过缺口：complete 模式现在强制 AList-TVBox upstream 源码合同；`implementation_tree` 对全部受管文件和完整 `tests` 树共 86 个文件形成内容寻址清单，并在所有 pytest、差分和兼容命令结束后复算 `file_count/tree_sha256/manifest`，防止报告与实际测试树漂移；pytest 子命令固定使用门禁私有临时目录并关闭缓存插件，避免全局临时目录权限污染。最终完整门禁为 `17/17 passed`，pytest 为 `953 passed / 7 skipped`，两组固定 seed 的 50,000 例差分均为 `50000 equal / 0 different / 0 errors`，ATVP direct-play、FongMi direct-PY、FongMi category/extend 和 AList-TVBox 1.42.0 upstream 合同全部通过；86 文件实现树 SHA256 为 `1A53C72BEBCEA2F76C5A223E76F72D2C6517EEE0E24BCC5D43D17C92A620009F`。最终报告为 `work/v80-stage-gate.json`，SHA256 `20D2E011EF76191FEB6D650643A511CC2D7CFCEA8766DF894497B48B0AAD5403`；报告记录 `admit=true`、`source_lock_verified=true`、`restore_action_planned=false`、`production_writes=false`、`deployment_attempted=false`。三路独立审计发现的规格、加固和文档问题均已关闭，最终复核无剩余阻断项。冻结 V70 继续为 `616699` bytes、SHA256 `233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4`，十七模块 vendor、closure、overlay 输入和开发产物保持 B6 指纹。P2 至此完成；下一阶段为 P3 可靠性与同步，不是部署或公开输出切换。

P3 九个隔离工作包、P4-1 至 P4-8、P5-1 Observability Policy、P5-2 运行时关联字段和 P5-3 诊断快照覆盖层均已完成本地工程封板；P5-4 私有只读导出/灰度 owner 已关闭为 `internal-only`，不新增 HTTP endpoint、首页入口、容器协议或管理动作。P5-5 已把 AList-TVBox 上游源码合同推进到 `1.48.0`，并收敛内容寻址续跑的 requirements 输入语义：固定 stage-gate 的 `upstream_contract` 覆盖 `1.45.0 -> 1.45.1 -> 1.46.1 -> 1.47.1 -> 1.48.0` 五个 tag commit、四段 delta、clean worktree 和完整 verifier 文件链；所有实际存在的 FongMi requirements 候选都进入指纹，目录/读取错误与零候选 fail-closed。1.48.0 叶合同 `24/24`，四代 verifier 单测 `25 passed`，受影响 stage 单测 `4 passed`。唯一完整 baseline `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json` 为 `18/18 passed`、pytest `1811 passed`、稳定树 `160 / FE835719...149C`、`admit=true`，且 V70 与生产状态未变；后续只使用其受信 SHA256 pin 做内容寻址 closure。生命周期、缓存性能、顺序长稳和搜索调用族并发已有独立本地证据；人工发布批准、服务器/MuMu/FongMi 弹幕与快手联调、私有灰度和公开 V70 晋升仍未开始。

P5-5A **重复生命周期静止态基线** 已于 2026-08-17 封板。新增项目专用 runner 与单锚点 overlay，只修复 V80 `destroy()` 在关闭 `_session`、`_history_session`、`_tmdb_session` 后继续保留引用的问题；冻结 V70 和 P5-3 输入分别保持 `616699 / 233C73...82D4` 与 `848431 / 30EBAC...A409`，P5-5A 候选为 `848540 / A14571...5280`。32 轮报告 `work/v80-p5-lifecycle-stability-r7-20260817.json` 为 `32/32 passed`，绑定 runner/candidate provenance、连续 generation、精确资源证据及零网络/持久化/部署观察。完整 baseline 首次失败只因 Macro A 的最终候选常量仍停留在 P5-3；保留该失败证据后，最小更新最终消费者并按固定 DAG 续跑，closure 为 `18/18 passed`、`8 executed / 10 reused`、pytest `1873 passed`、稳定树 `163 / 9CFDD9...B849B`。安全与规格审计无阻断项；不把 runner 扩建为通用 Python sandbox，也不宣称取消任意运行中的用户代码。

P5-5B **冷/热缓存性能基线** 已于 2026-08-17 完成独立证据封板。它不新增 overlay 或 runtime 行为，只对 P5-5A 候选 `848540 / A14571...5280` 的真实 `Spider.v80_cache_load` 建立项目专用 runner：固定 `cold_miss`、`fresh_hot_hit`、`stale_background_refresh` 三场景各 32 样本，stale worker 只进入受控队列并显式释放；host `min/median/p95/max` 仅记录，不参与准入。正式 `/2` 报告 `work/v80-p5-cache-performance-r1-20260817.json` 为 `96/96 passed`，SHA256 `63CEA0A99F2114385896D216166681C8C964328E86E5D848A1BEC661E03C8379`；candidate executed/rebuilt/output 与前后状态闭包一致，受管网络、凭据、持久化、真实线程和 candidate sleep 尝试均为零。内容寻址 closure `work/v80-p5-5b-cache-performance-closure-r1-20260817.json` 为 `18/18 passed`、`7 executed / 11 reused`、pytest `1916 passed`、稳定实现树 `165 / 92BE658F0135B2A972F053ECAD599346F24A4D050AED00758D3799446527ACA3`，耗时 `1299.442s`；output admission 与 V70 source lock 通过，且没有生产写入或部署尝试。三轮审计关闭加载源码身份、closure expected state、缓存命中 TOCTOU、跨轮旧 candidate 和 destroy 后计数等缺口，最终 Critical/High/Medium 为零；结论不外推到真实网络、并发、长稳、服务器、MuMu 或实机。

P5-5C **长时间运行资源增长基线** 已于 2026-08-17 完成独立证据封板。项目专用 runner 在单个真实 Spider、一次 init/destroy 和同一 generation 内执行 `256 + 32 x 128 = 4352` 次顺序操作，逐检查点冻结 cache、diagnostics、TimeoutOperation response、weakref、任务、Session 和引用 owner；不新增 runtime、overlay、manifest、gate、通用 benchmark/cache/sandbox 框架。正式 `/2` 报告 `work/v80-p5-long-run-resource-growth-r4-20260817.json` 为 `32/32 passed`，SHA256 `9BC19054029595EC6647C2C026C98DE04E71A2D14C6466C6231ABE98921B507D`；candidate trace `161344 -> 173808` bytes、delta `12464` 仅观察不准入，网络、凭据、真实线程和生产写入为零，destroy 后受管资源全部清零。聚焦回归 `50 passed`；审计关闭 report-owned tracemalloc 斜率、mini profile 假发布、reference bool 类型混淆和动态异常类型泄露。首次 stage closure 只因 pytest 在 `1800s`、约 `90%` 处超时而失败；保留其 SHA256 `EEC631A06A4E258F6E89EE063A723DE263C815E3CE2C96B771C2263783C9C34D` 后续跑，成功 closure `work/v80-p5-5c-long-run-resource-growth-closure-r2-20260817.json` 为 `18/18 passed`、`6 executed / 12 reused`、pytest `1966 passed`、稳定树 `167 / C7CE536D...B6A026`，SHA256 `7977DDC3FC4EB0B9136A6B419BDDE136E703EF549365F0FAFC601EA76A3C76E7`。结论不外推到真实网络、并发、wall-clock endurance、服务器、MuMu 或实机。

P5-5D **搜索调用族并发与隔离基线** 已于 2026-08-17 完成第二轮专项实现、聚焦回归、三路复审和正式 18 步 stage closure。中文别名“搜索并发所有权覆盖层”表示一个固定覆盖层，不表示单一文本锚点；该层以 P5-5A `848540 / A14571...5280` 为精确输入，执行 24 个显式唯一替换，收口 generation 从 mode 到 API 的贯通、supplement 跨代拒绝、resource response exactly-once owner、search job/bulkhead owner 和 live-init runtime 轮换，不引入通用 token/cache/sandbox/压力框架。DNS/media executor 是搜索可播放性验证与播放探测共享的底层依赖，本包只迁移其 owner/slot 生命周期；共享 reader 未修改，四个播放探测算法保持 AST 不变，两个 owner 方法归一化后 AST 等价，不能据此宣称 P5-5E 播放并发完成。当前候选为 `854833 / 3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766`。schema `/3` runner 报告 `work/v80-p5-search-concurrency-runtime-owner-final-r3-20260817.json` 为 `7/7 passed`，SHA256 `A26D93477EF9E7798EBE023F2ECE110E10C32D6E862640F609FC21C9999CA0EE`；live init 轮换六 executor/四 slot，旧 API 与排队任务不使用新 session，cleanup 为 Session `18/18`、executor `6/6`，worker/job/refresh/timeout 全部为零。runtime ownership `43 passed`、共享播放边界 `6 passed`、runner `15 passed`、stage-gate 单测 `242 passed`；第二轮 simplify/spec/security 复审均 `findings=0`。首次完整 closure 仅暴露 9 个固定测试/runner 的过期 owner 假设和错误的 `1.46.1` upstream 根，不是生产实现失败；最小更新后以失败报告可信 SHA 续跑，`work/v80-p5-5d-search-concurrency-runtime-owner-resume-closure-r2-20260817.json` 为 `18/18 passed`、`8 executed / 10 reused`、pytest `2044 passed`、稳定树 `171 / D24ECF6C92C16A1687CB331B81977D71642ADE629501C786BE5946D267C48050`、敏感扫描 `165/0`、`admit=true`，且无生产写入或部署。该证据不外推真实网络、设备或播放/History 并发。

P5-5E **播放调用族并发与隔离基线** 已于 2026-08-17 完成小范围实现、证据加固、聚焦回归、三路最终复审和正式 18 步 stage closure。中文别名“播放并发所有权覆盖层”对应 7 个显式唯一替换，以 P5-5D `854833 / 3C734E...9766` 为精确输入，只收口 player generation/backend/session、旧 ATVP session、response/connection owner、media slot、前后台隔离、live init、陈旧 route-quality/probe/History 副作用和 destroy 清理，不新增通用 executor/cache/retry/sandbox/token/压力框架。候选为 `857088 / 3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F`。正式 `/1` 报告 `work/v80-p5-playback-concurrency-r2-20260817.json` 为 `8/8 passed`，SHA256 `ABFB274DD4C98C282FDBB13F8329DF32BC1AA58DE77AA3C5CB302904EADC36E0`；runner 统一编译启动时已哈希候选字节、恢复 `base/base.spider`，live-init 明确绑定 `cancelled`，关闭候选 TOCTOU、测试进程污染和异常假绿缺口。定向 `31 passed`，simplify/spec/security 最终均 `findings=0`。技术 closure `work/v80-p5-5e-playback-concurrency-closure-r1-20260817.json` 为 `18/18 passed`、pytest `2079 passed`、稳定树 `176 / F59312A671B1B2E275A74F93E96478AF9C3EEA47CE12A89B2F50E8A85B99BADA`、敏感扫描 `170/0`、`admit=true`，SHA256 `1E0D3ACB2B7C3041917E75E386C935BEE895AA47C10BDA09A5E06775AD5246AA`；无生产写入或部署，结论不外推真实网络、服务器、MuMu、FongMi、实机或 History 自身并发。

P5-5F **History 调用族并发与隔离基线** 已于 2026-08-17 完成小范围实现、确定性回归、三路最终复审和技术 closure。中文别名“History 并发所有权覆盖层”对应 13 个显式唯一替换，以 P5-5E `857088 / 3DAB5769...299F` 为精确输入，只收口 History job identity、background/manual/replacement owner、同一 context lock 内的 generation/category refresh 与临界区外持久化；`_history_sync_lock` 和 History 事件队列保持独立，不新增通用 executor/cache/retry/concurrency 框架。候选为 `859732 / B42B37C097AA989F0FE82EF380A71865A4FDA02F6606A295E120FD79DA610700`。正式 `/1` 报告 `work/v80-p5-history-concurrency-r3-20260817.json` 为 `8/8 passed`，SHA256 `9B00F4A4FCDBF4556CC764D706E67BC73EA0E4A5A6660D595BBB043050BC5E9C`；overlay/runner `34 passed`、构建消费者 `4 passed`、stage selector `12 passed`、Chaos `7 passed`、旧消费者修复后 `53 passed`，simplify/spec/security 最终均 `findings=0`。closure r1 只因 pytest 在 `2400s`、约 `75%` 超时；r2 只暴露 53 个历史测试消费者未禁用更晚 History overlay，两份报告均只读保留。最终技术 closure `work/v80-p5-5f-history-concurrency-closure-r3-20260817.json` 为 `18/18 passed`、`7 executed / 11 reused`、pytest `2117 passed`、稳定树 `180 / FE0ADBCF7628CFCE1E10D55FAF3B0780394CEFE1518755BBD388BDCDC5F87609`，SHA256 `77E0FF352DA25FAE2D76311584F70D1585CBB4E68274BD2CFCD505023F8D8648`；无生产写入或部署。

后续不再扩建通用并发、缓存、重试、executor 或跨项目框架。最终 r6 closure 与本地 Git 候选提交已经完成；V80 剩余发布路径固定为：私有灰度、真实服务器/MuMu/FongMi 验证、完整回退演练、人工发布批准和生产晋升。任何生产切换前仍必须保持公开 V70 指纹锁，并生成新的只读证据报告。
