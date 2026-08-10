# 发布与部署状态

## 当前发布

| 项目 | 状态 |
| --- | --- |
| 仓库索引 | `spiders_v2.json` 已登记并启用 |
| 插件 ID | `douban_tmdb_follow_single` |
| 发布版本 | `51` |
| 源码格式 | 明文 `.py` |
| AList-TVBox 基线 | `1.42.0` |
| 源码大小 | `405432` 字节 |
| 源码 SHA256 | `FEE7520D1E830C6027671CC3F876B63AD68EF5A3DFE7CB8C36584BF4D5CEF17C` |
| 仓库部署 | 公开发布 |
| 容器部署方式 | 仅通过仓库导入拉取，不在仓库保存容器凭据 |

## 发布验证

- v51 追更确认、实时反馈、同盘补集与输入边界专项：`38/38`。
- v49 History 后台与并发专项：`22/22`。
- v48 刷新与资源匹配专项：`17/17`。
- v49 完整改版前逻辑回归基线：`235/235`。
- v51 源码编译、JSON 解析和差异格式检查：通过。
- AList-TVBox raw direct-play 插件合同：`20/20` 通过。
- 空 EXT 直接 FongMi 元数据详情与直链播放行为测试：通过。
- FongMi 分类调用合同：通过。
- AList-TVBox/FongMi 双运行时合同：通过。
- AList-TVBox `1.42.0` 上游源码合同：通过。
- simplify、harden、spec 最终审计：零中高风险发现。
- 私有地址、订阅令牌、Cookie、账号密码和调试快照检查：通过。

`公开发布` 只表示仓库入口和源码可访问，不代表已部署到任何 AList-TVBox 容器。容器部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 执行。
