# 发布与部署状态

更新日期：2026-08-20

## 当前公开版本

| 项目 | 状态 |
| --- | --- |
| 插件 ID | `douban_tmdb_follow_single` |
| 公开版本 | `90` |
| 根索引 | `spiders_v2.json` 已指向 V90 |
| 公共源码 | `py/豆瓣TMDB追更单入口.py` |
| 公共源码大小 | `981711` 字节 |
| 公共源码 SHA256 | `C5FA2CDD02ABAC809099769758D8CE50053C9AE09D11DDAA0F65719AD12ECA82` |
| 历史 V70 | 保留在 Git 标签 `v70`，不再是活动公开入口 |
| 私有部署 | plugin `421` 保持独立 V90，不由本次公共发布覆盖 |

## 构建状态

| 项目 | 状态 |
| --- | --- |
| 开发合同 | `v80-source/2 / independent_v80_modular` |
| 冻结基线 | V80 `872002 / B6319D2925AF60F5068DC84C2AA6B1AF753666CA4DA294533EB39736B5004CD7` |
| 活动 owner | 版本元数据、追更交互、候选识别、播放记录合并、线路预热与恢复、播放列表输出 |
| 过滤器 owner | 资源名过滤与规范化独立分片 |
| canonical | `981757 / B81CCB95119B6A676CA7CBE93166EE2A7FC4D5AECE79EE78FC1852FBA0619CA9` |
| 公共生成器 | `tools/build_v90_public_release.py` |
| 公共闭包 | `plugins/douban_tmdb_follow_single/public-release.json` |

canonical、private staging 和公共源码都由构建器生成，不作为手工编辑源。

## 兼容和验证

| 项目 | 状态 |
| --- | --- |
| AList-TVBox 源码合同 | `1.51.1 / 47432df300c1ee54e799fe9c7a3eb169823c2f0e` |
| FongMi 源码合同 | `5.6.0 / 1a19fee278fa2234da725d61a53bf59b69fe9127` |
| V89/V90 定向合同 | `20 passed` |
| 模块化构建 | 通过 |
| Python 编译 | 通过 |
| ATVP direct-play | 通过 |
| FongMi 双运行时 | 通过 |
| 全量 pytest | 本次未重复运行；复用输入未变化的既有证据 |
| 旧十八步门禁 | 本次未运行；已退出日常 V80.1 发布链 |
| Macro / Chaos | 本次未运行；受影响 owner 未要求重算 |

## 功能状态

- Playback/History 增量同步、墓碑、身份和播放进度单调合并已启用。
- 主动预热入口、进度卡、可播放状态和长期线路绑定已启用。
- AList 搜索、PanSou、Telegram 和受控其他插件候选已接入。
- 临时剧集身份及后续 TMDB 身份迁移已启用。
- 客户端优先、`800ms` 后服务端补位的选择性 TMDB 热备已启用。
- 多集电视剧/综艺允许追更；电影、独立视频和已知单集项目拒绝。

## 未替代的人工验证

公开仓库发布和本地合同通过不等于异地 FongMi 已完成刷新、追更确认、主动预热和真实播放。客户端现场结果需要单独记录；出现问题时从具体失败动作和受影响 owner 继续，不回到旧全量门禁。
