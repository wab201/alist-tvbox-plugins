# V90 部署说明

## 仓库升级

在 AList-TVBox 插件管理中导入以下仓库地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

公开插件 ID 继续使用 `douban_tmdb_follow_single`。已有 V70 安装重新导入同一地址后会升级到 V90，不需要删除原插件记录；现有 EXT 和启用状态应由 AList-TVBox 保留。

导入完成后，在实际使用的 FongMi/TvBox 客户端刷新订阅，并确认插件名称显示为“豆瓣TMDB追更助手 v90”。

## 配置检查

至少配置 TMDB Read Access Token：

```json
{
  "atvp_plugin_mode": "alist-tvbox-raw",
  "tmdb_access_token": "YOUR_TMDB_READ_ACCESS_TOKEN"
}
```

需要把本机播放进度写回 AList-TVBox 并供其他客户端读取时，配置当前容器中具有 `USER` 或 `ADMIN` 角色的账号。账号配置不完整时，插件按只读模式运行。

默认使用当前订阅的 AList-TVBox 地址访问 Playback/History API。只有同步服务位于另一个客户端可达入口时才配置 `history_api`。公网账号登录应使用 HTTPS、VPN 或受保护的内网通道。

## 升级后检查

1. 打开“追更管理”，运行同步连接检查，确认页面出现明确成功或失败反馈。
2. 执行主动预热，确认进度卡持续更新，完成后有条目标记为可直接播放。
3. 打开一个已追更剧集，确认优先出现已绑定线路并能进入播放器。
4. 播放数分钟后退出，再刷新追更动态，确认本地进度没有被空云端或空 TMDB 数据回退。
5. 对一部未被 TMDB 收录但有明确多集证据的新剧确认追更，检查是否建立临时剧集身份。

## 发布产物校验

公共源码：

```text
path: py/豆瓣TMDB追更单入口.py
bytes: 981711
sha256: C5FA2CDD02ABAC809099769758D8CE50053C9AE09D11DDAA0F65719AD12ECA82
```

公共索引必须登记：

```json
{
  "id": "douban_tmdb_follow_single",
  "file": "py/豆瓣TMDB追更单入口.py",
  "version": 90,
  "valid": true
}
```

## 回看 V70

V70 不再作为活动公开入口，也不执行运行时原子回退。需要比较或恢复历史源码时，使用 Git 标签 `v70` 创建单独维护分支，再按正常仓库发布流程提高版本号；不要在活动 V90 安装中混用旧源码和 V90 索引。

## 安全边界

- 不在仓库或发布记录中保存服务器密码、Cookie、Token、TMDB 密钥或完整订阅地址。
- 不把本地 ATVP/FongMi 合同描述为真实异地客户端验收。
- 私有 plugin `421` 保持独立 V90 部署，公共仓库升级不应修改其配置或源码。
