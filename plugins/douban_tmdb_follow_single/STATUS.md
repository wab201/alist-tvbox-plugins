# 发布与部署状态

## 当前发布

| 项目 | 状态 |
| --- | --- |
| 仓库索引 | `spiders_v2.json` 已登记并启用 |
| 插件 ID | `douban_tmdb_follow_single` |
| 发布版本 | `60`（公开测试版） |
| 源码格式 | 明文 `.py` |
| AList-TVBox 最低兼容基线 | `1.42.0` |
| AList-TVBox 当前验证环境 | `1.44.0` |
| 源码文件 | `py/豆瓣TMDB追更单入口_v60.py` |
| 源码大小 | `570622` 字节 |
| 源码 SHA256 | `BA6E42E61BF94F058A84C597FC8B2C2791E7C718FD02B1AC01824EF77FCB2B12` |
| 自动化回归 | `229` 项通过 |
| 仓库部署 | 公开测试版 |
| 回退基线 | v57，源码 SHA256 `A992254BDC0A2AC4AFB32DD6A1C6A6ED5B78158848C539BAEC11356F0C68D077` |
| 容器部署方式 | 仅通过仓库导入拉取，不在仓库保存容器凭据 |

`公开测试版` 只表示仓库入口和源码可访问，不代表已部署到任何 AList-TVBox 容器。容器部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 执行。
