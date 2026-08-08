# 发布与部署状态

## 当前发布

| 项目 | 状态 |
| --- | --- |
| 仓库索引 | `spiders_v2.json` 已登记并启用 |
| 插件 ID | `douban_tmdb_follow_single` |
| 发布版本 | `49` |
| 源码格式 | 明文 `.py` |
| AList-TVBox 基线 | `1.42.0` |
| 源码大小 | `374558` 字节 |
| 源码 SHA256 | `021A962A925714BD2D1E3EA68F5B860E6FE85779D84A93DBC6BA46D252243820` |
| 仓库部署 | 公开发布 |
| 用户容器部署 | 不由本仓库自动执行或记录 |

## 发布验证

- v49 History 后台与并发专项：`22/22`。
- v48 刷新与资源匹配专项：`17/17`。
- 完整逻辑回归：`235/235`。
- AList-TVBox raw 插件合同：通过。
- FongMi 分类调用合同：通过。
- AList-TVBox/FongMi 双运行时形状检查：通过。
- AList-TVBox `1.42.0` 上游源码合同：通过。
- 三轮 simplify、harden、spec 审计完成，发现项均已修复并回归。
- 私有地址、订阅令牌、Cookie、账号密码和调试快照检查：通过。

`公开发布` 只表示仓库入口和源码可访问，不代表已部署到任何 AList-TVBox 容器。容器部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 执行。
