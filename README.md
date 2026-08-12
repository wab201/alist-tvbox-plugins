# AList-TVBox 插件仓库

这是一个遵循 [har01d5/tvbox](https://github.com/har01d5/tvbox) `spiders_v2.json` 导入格式的精简插件仓库，仅保留 AList-TVBox 导入、插件运行和公开维护所需文件。

## Web 插件管理导入

在 AList-TVBox Web 界面打开插件管理，把以下地址填入 **仓库地址** 后选择 **导入仓库**：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

这是本仓库插件发布后的正式安装和更新路径。首次导入会新增插件；以后保持插件 `id` 不变并递增仓库版本号，再次导入同一仓库地址即可刷新现有插件源码，不需要删除旧插件或改用源码直链。插件 EXT 和启用状态由现有插件记录继续保留。

仓库导入完成后，刷新正在使用的客户端订阅即可加载新版。

只部署 SeedHub 时使用仓库内的单插件索引，避免刷新或重复导入无关插件：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/plugins/seedhub/spiders_v2.json
```

## 插件列表

| 插件 | 版本 | 索引状态 | 说明 |
| --- | ---: | --- | --- |
| 豆瓣 TMDB 追更助手 | 63 测试版 | 可导入 | [能力与配置](plugins/douban_tmdb_follow_single/README.md) |
| SeedHub 磁力与多网盘 | 1 | 可导入 | [能力与配置](plugins/seedhub/README.md) |

### 豆瓣 TMDB 追更助手 v63 测试版

- 动态页改为只读取云端 History 快照，不再触发本机 History 导出、全量合并和导入；完整双向同步保留在“立即同步 History”和播放结束同步路径。
- History 无云端差异时跳过第二次本机导出和整表导入，减少动态页和详情页等待。

- 统一管理后台任务、定时器和执行器，插件重新初始化或销毁后，旧任务不能继续覆盖新配置下的状态。
- 统一响应缓存与线路质量缓存的保存、重试和退避；过期数据刷新采用单任务所有权，减少重复刷新和旧任务回写。
- 豆瓣、TMDB、追更持久化与 History 协调逻辑拆分为内部组件，保持单文件发布和双运行时兼容。
- 新增脱敏诊断事件与诊断快照，关键失败可定位到具体阶段，同时避免令牌、Cookie 和认证信息进入诊断内容。
- 修复跨生命周期缓存保存、线路质量失败重试、追更页刷新任务和资源搜索名额释放等并发边界问题。
- 修复首次详情云端 History 时序、追更确认反馈与候选记录清理；广域网 History 默认复用订阅 HTTPS 地址，并兼容 AList-TVBox 1.44.0 单条删除接口异常。
- 本测试版继续保留 v57 源码和 v60 上一版回退文件；仓库入口可通过一次索引切换原子回退。

## 精简结构

```text
spiders_v2.json                       # AList-TVBox 仓库导入入口
py/                                   # 可发布插件源码
plugins/
  douban_tmdb_follow_single/          # 单个插件的文档与维护记录
    README.md                          # 能力与配置概览
    DEPLOYMENT.md                      # 完整部署步骤
    FILTER.md                          # 过滤器复用说明
    CHANGELOG.md                       # 插件更新记录
    STATUS.md                          # 发布和验证状态
    extend.example.json                # 插件 EXT 示例
    filter.example.json                # 过滤器配置示例
  seedhub/                             # SeedHub 插件文档与维护记录
    README.md                           # 能力、链路与使用边界
    DEPLOYMENT.md                       # 部署和人工客户端验证步骤
    CHANGELOG.md                        # 插件更新记录
    STATUS.md                           # 发布和验证状态
    extend.example.json                 # 可选插件 EXT 示例
    spiders_v2.json                     # 仅导入 SeedHub 的仓库索引
```

仓库不复制官方项目中的旧索引、JAR、验证工具、测试缓存或第三方插件集合。

## 索引维护规则

- 插件 `id` 发布后保持稳定，更新时只递增 `version`。
- 每次源码更新必须同时修改源码中的 `//@version` 和对应 `spiders_v2.json` 中的 `version`，两处版本保持一致。
- `file` 必须指向仓库中存在的公开插件文件。
- 明文 raw Python 插件的 `file` 必须以 `.py` 结尾。
- 只有通过兼容与安全检查的版本才设置 `valid: true`。
- 每次发布同步更新仓库根 `README.md` 的插件版本与当前版本摘要，以及对应插件的 `README.md`、`DEPLOYMENT.md`、`CHANGELOG.md` 和 `STATUS.md`。
- 每个插件的每个版本都必须在自己的 `CHANGELOG.md` 中书写更新说明。
- 更新说明只描述用户可感知的功能新增、功能调整、体验优化和问题修复，不写测试过程、测试数量、审计过程、发布命令、日志、源码大小、哈希或其他验证数据。
- 对应单插件索引存在时优先使用 `plugins/<id>/spiders_v2.json`，避免整仓导入影响其他已配置插件。

## 安全边界

本仓库不保存服务器地址、订阅令牌、Cookie、账号密码、网盘凭据或调试快照。示例中的凭据均为空值或明确占位值。实际 EXT 会随 AList-TVBox 订阅下发，应妥善保护订阅地址和容器访问权限。
