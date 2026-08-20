# 豆瓣 TMDB 追更助手

- 插件 ID：`douban_tmdb_follow_single`
- 当前公开版本：`90`
- 运行方式：AList-TVBox raw Python 插件生成订阅，再由 FongMi/TvBox 使用
- 固定源码入口：`py/豆瓣TMDB追更单入口.py`
- 当前 AList-TVBox 源码合同：`1.51.1`
- 当前 FongMi 源码合同：`5.6.0`

## 主要能力

### 追更和身份

- 从豆瓣、TMDB、FongMi 收藏和播放记录建立电视剧、动漫、综艺、真人秀等多集项目的追更状态。
- 电影、独立视频和已知 0/1 集项目拒绝加入追更。
- TMDB 尚未收录的新剧可建立 `local:tv:*` 临时身份；有豆瓣 ID 时保留 `douban:*` 来源别名。
- TMDB 后续收录后迁移为正式 `tmdb:tv:*` 身份，合并来源、播放进度和线路绑定。
- 追更动态按全局进度排序，区分更新至、已看、正在看和播放记录待确认。

### 播放记录同步

- 使用 AList-TVBox Playback/History 通道同步 FongMi 播放记录，支持增量变化、完整快照、墓碑和旧接口受控回退。
- 较新的本地进度优先；服务端空数据或 TMDB 空进度不能覆盖有效播放状态。
- 播放完成、重看、跨设备进度和迟到删除使用单调合并规则。
- “检查同步连接”和手动同步在追更管理中持续显示处理结果。
- 未配置可写 `USER`/`ADMIN` 账号时只读取云端记录，不上传本机新增进度。

### 资源搜索和主动预热

- 搜索 AList-TVBox `/vod`、`/vod1`、PanSou、Telegram 及受控的活动订阅插件候选。
- 统一清洗年份、季集、画质、网盘和其他资源名装饰，再按标题、别名、年份、季号和目标集覆盖评分。
- 主动预热可在短时间内有界并发处理全部追更条目，显示已处理和可直接播放数量。
- 只有经过详情、播放器、安全输出、Range 和目标集覆盖验证的线路才能进入可播放缓存和长期绑定。
- 绑定失效后再搜索替换；长期状态不保存签名 URL、Cookie、Token 或原始认证信息。

### TMDB 双链路

- 冷查询先使用客户端 TMDB 通道。
- 客户端超过 `800ms` 未完成，或返回空结果、降级、传输失败时，再启动 AList-TVBox 服务端通道。
- 显式多集证据可采用最先返回的可信电视剧；类型不明确时仍执行电影冲突检查。
- 每条通道保留最近 `8` 次健康样本，连续失败 `3` 次后降级 `60s`，不建立无限重试。

### 缓存和可靠性

- 图片、分类、详情、身份、History 快照和线路质量使用有界缓存；过期内容可先返回旧值并在后台刷新。
- 搜索、播放、History、资源补全和线路探测使用独立并发所有权和绝对超时预算。
- 外部媒体地址逐跳验证 DNS、重定向、HTTPS 降级和跨域请求头。
- JSON/HTML 响应、字段、集合和诊断输出均有大小限制；诊断会脱敏 Token、Cookie、账号和签名参数。

## 配置

最小配置示例：

```json
{
  "atvp_plugin_mode": "alist-tvbox-raw",
  "tmdb_access_token": "YOUR_TMDB_READ_ACCESS_TOKEN"
}
```

跨设备写回播放记录时，再配置当前 AList-TVBox 容器中具有 `USER` 或 `ADMIN` 角色的账号。订阅入口能承载 Playback/History API 时无需额外填写 `history_api`；只有另有客户端可访问的同步入口时才覆盖。

不要把账号、密码、Cookie、Token 或完整订阅地址提交到仓库、日志或问题报告。

## 安装和升级

使用根仓库索引导入：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

插件 ID 保持不变，重新导入同一仓库地址即可从 V70 升级到 V90。导入后刷新实际客户端订阅。

## 架构边界

- 开发态修改 `src/douban_tmdb_follow_v80/` 下的冻结基线和 owner。
- canonical、private staging 和公共 `.py` 都是生成产物，不直接编辑。
- 公共生成闭包记录在 `plugins/douban_tmdb_follow_single/public-release.json`。
- 私有 plugin `421` 是独立部署链，不由公共仓库导入覆盖。

详细版本变化见 [更新记录](CHANGELOG.md) 和 [V70 到 V90 发布说明](../../docs/V70_TO_V90_RELEASE_NOTES.md)。
