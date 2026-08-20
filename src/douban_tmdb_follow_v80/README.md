# 豆瓣 TMDB 追更助手 V80 独立源码

本目录是 V80/V80.1 的唯一可写源码 owner。运行时仍发布单文件，但单文件只由构建器生成，不再作为开发源码。当前 v90 canonical 身份为：

- `981757` 字节
- SHA256 `B81CCB95119B6A676CA7CBE93166EE2A7FC4D5AECE79EE78FC1852FBA0619CA9`

## 构建边界

- `tools/build_v80_private_release.py` 只读取冻结基线 `parts/00_runtime_v80.pyinc`、六个 `owners/*.json`、过滤器分片和 `release.json`。
- 六个 owner 按 manifest 固定顺序生成唯一单文件；`src/douban_tmdb_follow_v80/豆瓣TMDB追更单入口.py` 与 `private/v80/staging/豆瓣TMDB追更单入口.py` 都是可重建产物，不得手工编辑。
- 构建不读取 V70 baseline、旧十段 `parts/*`、`build/v80-dev`、V70 behavior golden 或历史 overlay。
- `private/v80/spiders_v2.json` 与 `private/v80/private-release.json` 记录发布索引、来源 owner 指纹和产物指纹；它们与单文件一起作为 V80 发布封包的审计闭包。
- `release.json.release_lineage` 固定 v80-v90 的发布指纹：v80 是只读冻结基线，v81-v89 是只读历史包，v90 是 V80 基线叠加六个 owner 的生成物。累计业务变化全部归入 owner，历史发布包不再充当开发模板。
- v90 包含全追更主动预热、长期线路绑定、受控其他插件候选、临时剧集身份和选择性 TMDB 双链路热备。
- `tools/build_v90_public_release.py` 从 canonical 生成公共插件身份、固定入口和根索引；公共 `.py` 同样不得手工编辑。
- V70 仅作为 Git 标签历史保留，不参加 V90 构建、验证或运行时回退。

## 后续迭代

后续播放状态、追更影视身份、单调进度、交互文案、候选识别和线路变化应先落入对应 owner。验证只按改动 owner 运行聚焦节点、AST/重复方法检查、AList-TVBox 与 FongMi 双运行时合同，不恢复旧十八步日常门禁。
