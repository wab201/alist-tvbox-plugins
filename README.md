# AList-TVBox 插件仓库

本仓库提供符合 AList-TVBox `spiders_v2.json` 格式的公开插件。豆瓣 TMDB 追更助手当前公开版本为 V90。

## 仓库导入

在 AList-TVBox Web 管理页打开插件管理，将以下地址作为仓库地址导入：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

后续继续导入同一地址即可按插件 ID 和递增版本刷新源码。刷新 AList-TVBox 插件后，还需要在实际使用的 FongMi/TvBox 客户端刷新订阅。

## 插件列表

| 插件 | 版本 | 状态 | 文档 |
| --- | ---: | --- | --- |
| 豆瓣 TMDB 追更助手 | 90 | 公开 | [功能与配置](plugins/douban_tmdb_follow_single/README.md) |
| SeedHub 磁力与多网盘 | 1 | 公开 | [功能与配置](plugins/seedhub/README.md) |

## 豆瓣 TMDB 追更助手 V90

V90 在 V70 的豆瓣/TMDB 浏览、剧集追更、AList 资源搜索和 History 续播基础上完成以下升级：

- 播放记录使用 AList-TVBox Playback/History 通道做增量同步、墓碑处理和单调合并，TMDB 空进度不能覆盖较新的本地进度。
- 追更管理提供简体中文操作反馈、取消追更、同步检测和全追更条目主动预热；已验证线路持久绑定，失效后再刷新。
- 资源候选除 `/vod`、`/vod1`、PanSou、Telegram 外，还可从受控的活动订阅插件补充，并继续经过标题、详情、播放器、安全输出和 Range 验证。
- 未被 TMDB 收录的新剧可先使用本地或豆瓣临时身份，后续迁移到正式 TMDB 剧集身份并保留进度、线路和来源别名。
- TMDB 使用选择性双链路热备：客户端冷查询先发，`800ms` 后或空结果/传输失败时再由 AList-TVBox 服务端通道补位；连续失败只短期降级，不无限重试。
- 图片、分类、详情、身份和可播放线路使用有界缓存；网络响应、重定向、请求头、超时、并发和诊断信息均有明确边界。

完整更新记录见 [V70 到 V90 发布说明](docs/V70_TO_V90_RELEASE_NOTES.md)。

## 构建架构

开发态维护冻结 V80 基线和以下 owner：

- 版本元数据
- 追更交互
- 候选识别
- 播放记录合并
- 线路预热与恢复
- 播放列表输出
- 资源名过滤与规范化

`tools/build_v80_private_release.py` 生成 canonical/private staging，`tools/build_v90_public_release.py` 再生成公共身份的固定单文件和根索引。`py/豆瓣TMDB追更单入口.py` 是发布产物，不是长期手工维护源。

公共 V90 源码为 `981711` 字节，SHA256：

```text
C5FA2CDD02ABAC809099769758D8CE50053C9AE09D11DDAA0F65719AD12ECA82
```

## 兼容与验证

- AList-TVBox 源码合同：`1.51.1 / 47432df300c1ee54e799fe9c7a3eb169823c2f0e`
- FongMi 源码合同：`5.6.0 / 1a19fee278fa2234da725d61a53bf59b69fe9127`
- V90 定向合同：`20 passed`
- 模块化构建、Python 编译、ATVP direct-play、FongMi 双运行时通过

本地合同不等同于用户异地客户端的真实刷新和播放验收。V70 可通过 Git 标签 `v70` 回看；活动公开索引已经指向 V90。
