# SeedHub 部署与使用

## 前提

- AList-TVBox `1.42.0`。
- AList-TVBox 已配置需要使用的网盘账号或磁力离线能力。
- AList-TVBox 容器可以访问 GitHub raw 地址和 SeedHub 的至少一个已确认域名。

## 从仓库导入

1. 打开 AList-TVBox Web 管理界面。
2. 进入 **订阅 -> 订阅源管理**。
3. 在仓库地址中填写：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

4. 点击 **导入仓库**。
5. 在插件列表确认出现 **SeedHub磁力与多网盘**，插件 ID 为 `seedhub`，版本为 `1`。
6. 保持插件启用。EXT 默认留空；需要调整时填写合法 JSON。
7. 刷新正在使用的 AList-TVBox 订阅，再由客户端重新加载订阅。

不要把源码作为普通静态 Python 站点手工写入订阅。正确导入后，AList-TVBox 会生成：

- `api=csp_PyProxy`
- `jar=<容器地址>/spring.jar`
- `loader=<容器地址>/Atvp.py?v=...`
- `source=<容器地址>/plugins/.../seedhub.py`
- `raw=true`

## 可选 EXT

```json
{
  "host": "https://sidhub.cc",
  "hosts": [
    "https://sidhub.cc",
    "https://seeduck.cc",
    "https://hubdog.cc"
  ],
  "timeout": 12,
  "max_magnets": 24,
  "max_pan_per_provider": 20
}
```

字段说明：

- `host`：首选域名，只接受插件内置的三个已确认域名。
- `hosts`：故障转移顺序。未知域名会被忽略，缺少的内置域名会自动补回。
- `timeout`：单次请求超时秒数，允许 5 到 30。
- `max_magnets`：单个详情最多显示的磁力数，允许 1 到 60。
- `max_pan_per_provider`：每种网盘最多显示的入口数，允许 1 到 60。

## Web 界面检查

导入后在插件列表检查：

- 名称为 **SeedHub磁力与多网盘**。
- ID 为 `seedhub`。
- 版本为 `1`。
- 状态已启用，最近错误为空。
- 源地址以 `py/SeedHub.py` 结尾。

刷新订阅后，可在生成站点中检查 `csp_PyProxy`、`spring.jar` 和 Base64 EXT。不要修改容器数据库或手工拼接外层 EXT。

## 客户端人工验证

1. 重新加载包含 SeedHub 的订阅，不使用旧的最近观看卡片。
2. 打开 SeedHub，确认电影、动漫、剧集三个分类可见。
3. 打开任意影片详情，确认资源按磁力和网盘提供方分组。
4. 选择一个具体资源，确认此时才进入网盘文件列表或磁力文件列表。
5. 选择一个 `1@...` 文件并播放。
6. 至少人工检查磁力、百度、夸克、迅雷、UC 各一个；缺少对应容器账号时，应记录为账号能力缺失，不判断为页面解析失败。

## 常见问题

### 分类为空

检查容器是否能访问三个已确认域名。插件会自动切换域名，但三个域名全部不可用时会返回空列表。

### 详情显示加载失败

页面可能缺少标题或资源业务标记。此时插件会显示明确错误，不会把广告或发布页当成详情。

### 选择资源后解析失败

可能是 `/link_start/` 已失效、返回验证码、最终地址类型漂移，或三个镜像均不可用。插件会先完成多域重试，再返回最后一次错误。

### 能看到资源但没有文件

最终分享可能已失效，或 AList-TVBox 没有配置该网盘账号。查看容器 `/parse` 返回，不要在插件 EXT 中添加账号 Cookie。

### 文件可见但不能播放

检查 `/play?type=client-proxy` 返回、网盘账号状态、最终媒体请求头和 Range 响应。此阶段属于 AList-TVBox 播放链路，不是 SeedHub HTML 解析阶段。
