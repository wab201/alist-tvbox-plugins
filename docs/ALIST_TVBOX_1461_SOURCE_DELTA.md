# AList-TVBox 1.46.1 源码变化与 V80 证据

## 结论

AList-TVBox `1.46.1` 于 2026-08-15 发布。本项目将其作为 V80 当前上游源码合同目标；`1.45.1` 验证器继续保留为历史兼容证据。

从 `1.45.1` 到 `1.46.1` 的变化集中在播放记录同步：既有 raw plugin、路由和认证合同保持兼容；续播 ID、History 线协议和服务端持久化增加多级导航与网盘路径信息。该结论只证明源码和本地合同兼容，不等同于已完成服务器、MuMu、实机或跨设备语义联调。

## 固定身份

| 项目 | 固定值 |
| --- | --- |
| 基线标签 | `1.45.1` |
| 基线提交 | `9cd22bb91bbaaf2bb4f4e0cd9b9d8da00841db81` |
| 目标标签 | `1.46.1` |
| 目标提交 | `8d601fd1e0fc25f92cca48e96a32bb0155046fd0` |
| 提交数 | `8` |
| 变更文件数 | `16` |
| 本地只读源码树 | `D:\自写爬虫\work\alist_tvbox_latest_1.46.1_20260816` |
| 合同报告 | `work/v80-upstream-1461-source-contract-20260816.json` |

## 源码变化

1. `PlaybackSyncInput` 与 `History` 增加可选 `driveShareKey`、`drivePath`，并兼容 snake_case 输入别名。
2. `PlaybackSyncService` 将 `1@proxyId@...` 通过 `ProxyService.getPath()` 规范化为网盘 share/path；代理 ID 变化时用规范路径判断是否仍为同一内容。
3. 只有确认内容变化时才清除旧的 group/source/drive 导航坐标；相同文件重放保留导航数据。
4. change sequence 改为 `max(nextVal + 1, currentTimeMillis())`，避免迁移后的水位倒退。
5. 新增 `V17__FixChangeSequenceWatermark` 与 `V18__PlaybackDrivePath`，Native Flyway 显式注册 V10 至 V18。
6. `Atvp.py` 保留旧 `id + playlist` 续播 ID 解码，同时增加可选 `group`、`source`、`subgroup`、`subgroupName`；优先按坐标恢复，平面 playlist 作为回退。
7. `Atvp.py` 在应用续播 ID 前先把记录的 subgroup 调整到可恢复位置。
8. 订阅 loader revision 从 `link-check-v1` 更新为 `resume-group-v1`。
9. `spring.jar` 的 `PlaybackSyncer` 增加多级恢复标记；`PyProxy/playerContent` 合同仍存在。

## 工件指纹

| 工件 | Git blob | 规范字节 | SHA256 / MD5 |
| --- | --- | ---: | --- |
| `Atvp.py` | `9d47b50a6160a4301b37865a14f212e77165f84f` | `67750`（LF UTF-8） | SHA256 `3C73B5CEA7276B0A26D56EDF8A2625CF15477BC905105A013DD62E1D328D4B34` |
| `spring.jar` | `370a7069f6decb5226f49d9d657227f26cdadb98` | `374208` | SHA256 `BC68D079FA53B4087FDB5B7F1A69A8900AF4F4634AFEAD6C701541DDEBBC9DB9`; MD5 `44d8a3a64d477459be90895825820861` |

Windows checkout 中 `Atvp.py` 可能因 CRLF 展开成为 `69470` bytes。验证器使用 Git blob 和规范 LF 字节，避免把行尾转换误判为源码漂移；不得用 PowerShell 文本往返后的文件哈希替代 Git 对象证据。

## 证据获取方法

证据按四层获取，任一层缺失都不能扩大结论：

1. 发布身份：固定 tag、base/head commit、发布日期和 release notes。
2. 源码差异：用 `git diff --name-only 1.45.1..1.46.1` 固定精确 16 文件集合，并检查 Java、迁移、`Atvp.py` 和订阅 revision 的语义标记。
3. 运行时工件：固定 `Atvp.py` Git blob、规范 LF 哈希及 `spring.jar` blob/bytes/SHA256/MD5；从 `classes.dex` 只读确认必要类和多级续播标记。
4. 消费方合同：运行上游相关 Maven 测试、项目 1.46.1 源码验证器、V80 History 前向兼容回归和 FongMi category/Chaquopy 合同。

复现项目源码合同：

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\verify_alist_tvbox_1461_contract.py `
  "D:\自写爬虫\work\alist_tvbox_latest_1.46.1_20260816" `
  --json-out work\v80-upstream-1461-source-contract-20260816.json
```

复现上游相关测试时，PowerShell 必须把逗号测试列表作为一个完整参数：

```powershell
.\mvnw.cmd '-Dtest=PlaybackSyncServiceTest,SubscriptionServiceTest' test
```

## 已有验证

- 项目 1.46.1 验证器：`34/34` 源码合同检查通过。
- 上游 Maven：`PlaybackSyncServiceTest` 44 项、`SubscriptionServiceTest` 14 项，共 `58` 项通过。
- 项目 1.45.1/1.46.1、P3 History 与 stage-gate 聚焦范围在历史验证器冻结修复后复跑：`219 passed in 383.50s`。
- P4-7 封板候选仍为 `839093` bytes，SHA256 `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`；公开 V70 和根 `spiders_v2.json` 未变化。

## 对 V80 的影响

- P3 History importer 已接受但有意忽略新增的 drive/navigation 可选字段，因此当前证明的是 wire forward compatibility。
- 不得据此宣称 Python History 已实现 1.46.1 的跨设备多级导航恢复。必须先用运行时证据确认 `spring.jar PlaybackSyncer` 与 Python History 路径谁是实际 owner。
- 如果 Python 必须承担语义所有权，应另立 P3 兼容工作包，保存并编码新坐标，再进行经授权的服务器与客户端联调；不得把这项语义扩展夹带进 P4-8。
- P4-8 继续只归属 `_DoubanClient.request_text`。在取得匿名或用户提供的脱敏、完整解压 wishlist envelope 前，`256 KiB` 仅是暂定 floor，`selected_bytes` 必须保持 `null`，不得接入生产 policy。

## 失败即停止条件

- tag、commit、16 文件集合或任一固定工件指纹不一致。
- `1.45.1` 兼容合同出现超出三个版本身份检查之外的失败。
- FongMi category/Chaquopy 参数合同在目标 `Atvp.py` 上失败。
- 任何验证需要凭据、生产写入、部署或未授权服务器/模拟器操作。
- 只能证明字段可接受，却试图宣称多层续播语义已等价。
