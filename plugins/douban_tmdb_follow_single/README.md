# 豆瓣 TMDB 追更助手

- 插件 ID：`douban_tmdb_follow_single`
- 当前版本：`48`
- 运行环境：AList-TVBox raw Python 插件
- 已验证基线：AList-TVBox `1.42.0`
- 发布状态：索引已启用，可通过仓库导入

## 主要能力

- 浏览豆瓣和 TMDB 的电影、剧集与季集信息。
- 建立追更列表，显示追更动态并管理已看、取消和同步操作。
- 操作结果以页面状态卡持续显示，不依赖 Toast 作为唯一反馈。
- 首次追更没有播放记录时，也能请求 AList-TVBox 搜索真实资源。
- 使用标题、别名、年份和季号进行保守匹配；单季剧不把季号作为硬性门禁。
- 自动发现后端已提供的资源搜索模式，隐藏明确缺失的模式。
- 按首开时间、稳定性、编码兼容性、分辨率和字幕情况评估线路。
- 使用 AList-TVBox History 匹配选集、续播位置和最近可播线路。
- 同一源码可选作为 AList-TVBox 详情/播放过滤器复用。

## 必要配置

首次使用只需在插件 EXT 中保留：

```json
{
  "atvp_plugin_mode": "alist-tvbox-raw",
  "tmdb_access_token": "YOUR_TMDB_READ_ACCESS_TOKEN"
}
```

`tmdb_access_token` 从 TMDB 网站的 **设置 -> API -> API Read Access Token** 获取。需要把追更结果写回 AList-TVBox History 时，再填写可登录当前容器的 `USER` 或 `ADMIN` 用户名和密码；留空仍可读取 History。

推荐直接使用带中文说明的 [extend.example.json](extend.example.json)。不要手工添加 AList-TVBox 生成的 `api`、`token`、`secret`、`loader`、`source` 或 `raw` 外层字段。

## 文档

- [完整部署步骤](DEPLOYMENT.md)
- [过滤器复用](FILTER.md)
- [更新记录](CHANGELOG.md)
- [发布与验证状态](STATUS.md)

插件源码公开地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/py/豆瓣TMDB追更单入口.py
```
