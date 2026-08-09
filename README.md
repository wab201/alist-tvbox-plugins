# AList-TVBox 插件仓库

这是一个遵循 [har01d5/tvbox](https://github.com/har01d5/tvbox) `spiders_v2.json` 导入格式的精简插件仓库，仅保留 AList-TVBox 导入、插件运行和公开维护所需文件。

## 仓库导入地址

在 AList-TVBox Web 界面打开 **订阅 -> 订阅源管理**，把以下地址填入 **仓库地址** 后选择 **导入仓库**：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

导入后启用需要的插件、填写其 EXT，再刷新插件和客户端订阅。

只部署 SeedHub 时使用仓库内的单插件索引，避免刷新或重复导入无关插件：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/plugins/seedhub/spiders_v2.json
```

## 插件列表

| 插件 | 版本 | 索引状态 | 说明 |
| --- | ---: | --- | --- |
| 豆瓣 TMDB 追更助手 | 49 | 可导入 | [能力与配置](plugins/douban_tmdb_follow_single/README.md) |
| SeedHub 磁力与多网盘 | 1 | 可导入 | [能力与配置](plugins/seedhub/README.md) |

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
- `file` 必须指向仓库中存在的公开插件文件。
- 明文 raw Python 插件的 `file` 必须以 `.py` 结尾。
- 只有通过兼容与安全检查的版本才设置 `valid: true`。
- 每次更新同步维护对应插件的 `CHANGELOG.md` 和 `STATUS.md`。
- 单插件部署优先使用对应 `plugins/<id>/spiders_v2.json`，避免整仓导入影响其他已配置插件。

## 安全边界

本仓库不保存服务器地址、订阅令牌、Cookie、账号密码、网盘凭据或调试快照。示例中的凭据均为空值或明确占位值。实际 EXT 会随 AList-TVBox 订阅下发，应妥善保护订阅地址和容器访问权限。
