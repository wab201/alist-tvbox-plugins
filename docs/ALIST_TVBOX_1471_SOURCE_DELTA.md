# AList-TVBox 1.47.1 源码变化与 V80 证据

## 结论

AList-TVBox `1.47.1` 于 2026-08-16 发布。本项目把它作为 V80 当前上游源码合同目标，并保留 `1.45.1`、`1.46.1` 验证器作为历史兼容链。

从 `1.46.1` 到 `1.47.1` 的官方 compare 为 6 个提交、22 个变更文件，范围集中在网络直播关注。`Atvp.py`、`History.java`、`PlaybackSyncInput.java` 和 `PlaybackSyncService.java` 的 Git blob 均未变化；1.46.1 raw plugin、认证、播放、History 与多级续播合同继续通过。该结论只证明源码和本地合同兼容，不等同于服务器、MuMu、实机或直播关注端到端联调。

## 固定身份

| 项目 | 固定值 |
| --- | --- |
| 基线标签 | `1.46.1` |
| 基线提交 | `8d601fd1e0fc25f92cca48e96a32bb0155046fd0` |
| 目标标签 | `1.47.1` |
| 目标提交 | `05397d10cd1b8085670a628eb56cb94182fa885e` |
| 提交数 | `6`（GitHub 官方 compare；本地 shallow checkout 不用于提交数证明） |
| 变更文件数 | `22` |
| 本地只读源码树 | `D:\自写爬虫\work\alist_tvbox_latest_1.47.1_20260816` |
| 合同报告 | `work/v80-upstream-1471-source-contract-r2-20260816.json` |

## 源码变化

1. 新增 `LiveFollow` 实体、Repository、DTO、Service、管理 Controller 和 `V19__LiveFollow` 迁移。
2. TVBox 直播分类增加 `follow`；关注列表按 uid 隔离，开播项优先展示。
3. 无 token 的 `/live/follow`、`/live/unfollow` 显式委托空共享订阅上下文；`/live/{token}/follow`、`/live/{token}/unfollow` 在 uid 解析和写入前调用订阅 token 检查。空/共享上下文的默认用户归属沿用服务端现有规则。
4. `/api/live/follows/**` 管理接口要求 `ADMIN` 或 `USER` 登录权限，并从当前 SecurityContext 取得 uid。
5. V19 同时登记到 Flyway service、Native Flyway 配置和 reflect config；唯一键为 `(uid, platform, room_id)`。
6. `spring.jar` 更新为直播关注配套版本，但 `classes.dex` 仍包含 `PyProxy`、`playerContent`、`PlaybackSyncer` 和多级续播标记。
7. `Atvp.py`、History DTO/实体/Service 未变化，因此 V80 不新增 History 语义 owner，也不修改插件候选逻辑。

## 工件指纹

| 工件 | Git blob | 字节 | SHA256 / MD5 |
| --- | --- | ---: | --- |
| `Atvp.py` | `9d47b50a6160a4301b37865a14f212e77165f84f` | `67750`（规范 LF UTF-8） | SHA256 `3C73B5CEA7276B0A26D56EDF8A2625CF15477BC905105A013DD62E1D328D4B34` |
| `spring.jar` | `0dbefae36d9d41c313ad50ad9de1fb1b98067e47` | `374888` | SHA256 `F329B05DD2B92FCF40F69FEEC85641079A916064929AF87E011D0A80D15607FD`; MD5 `3ef2c42368e57a86786a614213197c76` |
| `spring.jar!classes.dex` | JAR 内部条目 | `1334504` | SHA256 `1FECE3B9CFB57723A59D7C22AE259F61D765B725F73D64F13822B7F0BE26C2C3` |

## 证据获取方法

1. 固定 `1.45.0`、`1.45.1`、`1.46.1`、`1.47.1` tag commit、base/head、发布日期和 release notes；提交数只采用 GitHub 官方 compare，不采用 shallow checkout 的 `rev-list --count`。
2. 用 `git diff --name-only 1.46.1..1.47.1` 固定精确 22 文件集合。
3. 先运行 1.46.1 验证器，只允许 7 个版本、release notes 和 `spring.jar` 身份检查失败；任何额外失败都阻断继承。
4. 重新固定 `spring.jar` blob/bytes/SHA256/MD5 与 `classes.dex` 哈希，并只读确认既有 PyProxy/续播标记。
5. 固定 V19 注册、完整 Native reflect 能力、管理端权限，以及 TVBox 空共享/tokenized 两条调用链，不把新增直播关注误写为 V80 插件运行时能力。

复现项目源码合同：

```powershell
$env:PYTHONIOENCODING='utf-8'
python -X utf8 tools\verify_alist_tvbox_1471_contract.py `
  "D:\自写爬虫\work\alist_tvbox_latest_1.47.1_20260816" `
  --json-out work\v80-upstream-1471-source-contract-r2-20260816.json
```

上游当前没有 LiveFollow 专项测试。本轮只复跑既有播放同步和订阅合同：

```powershell
.\mvnw.cmd '-Dtest=PlaybackSyncServiceTest,SubscriptionServiceTest' test
```

## 验证边界

- 历史固定 checkout 的 1.45.1、1.46.1 合同分别为 `62/62`、`34/34`；当前 1.47.1 叶验证器为 `26/26`，并显式拒绝 Git status 不可用、dirty worktree 和错误的 1.45.0 历史基线。
- 三个版本的验证器单测为 `16 passed`；与构建管线合并为 `33 passed in 37.36s`。stage-gate 文件当前收集 `224` 项；fail-closed 加固后两个旧夹具失败、拒绝/partial 语义和 FongMi requirements 候选输入均已按失效闭包以 `7 passed` 定向关闭。
- 第一次完整 P5-5 closure 为 `15/18 passed`，完整 pytest `1801 passed in 747.87s`；唯一根失败是 stage 输入把 FongMi 两个 requirements 候选误当成同时必需，`dual_runtime` 命令本身已通过，准入与 V70 锁按 DAG 正确失败。失败报告 `work/v80-p5-5-upstream-1471-closure-final-20260816.json` 为 `179528` bytes、SHA256 `1A101E2F796441862A424875EBEB150074F1DFB58BFEBD28D30E195F055C11EB`，仅作诊断证据；最终统一结果留给修复后的新 closure，不提前宣称全量绿色。
- 上游 `PlaybackSyncServiceTest` 44 项、`SubscriptionServiceTest` 14 项，共 `58/58` 通过。
- 1.47.1 `r2` 合同报告为 `7956` bytes，SHA256 `3194381CEE9E1D1A8537239D4D883E59B678447206B72F04E8E11A6BAAA7E756`；旧报告保持只读，仅作为修复前历史证据。
- 不虚构 LiveFollow 自动化覆盖；源码检查不能替代服务端或客户端实际关注/取关验证。
- 不使用用户 Cookie，不上传服务器，不操作 MuMu，不改变生产配置。
- 公开 V70、根 `spiders_v2.json`、V80 插件候选和双运行时返回合同保持不变。

## 失败即停止条件

- 1.45.0 至 1.47.1 任一固定 tag commit、三段 delta、22 文件集合或固定工件指纹不一致。
- 1.46.1 验证器出现允许的 7 个身份失败之外的任何回归。
- `Atvp.py`、History 或 Playback 关键 blob 相对 1.46.1 变化。
- V19 注册、管理端权限、空共享上下文或 tokenized 调用链证据不完整。
- 任何验证需要凭据、生产写入、部署或未授权模拟器操作。
