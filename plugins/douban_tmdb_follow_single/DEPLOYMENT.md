# 豆瓣 TMDB 追更助手（AList-TVBox 专用）

仓库导入地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/spiders_v2.json
```

插件源码地址：

```text
https://raw.githubusercontent.com/wab201/alist-tvbox-plugins/master/py/豆瓣TMDB追更单入口.py
```

本插件用于豆瓣/TMDB 浏览、剧集追更、AList-TVBox 资源搜索、线路评分和 History 续播。当前发布版本为 v51，适配 AList-TVBox 1.42.0 raw Python 插件，由 AList-TVBox 生成订阅后交给 FongMi/TvBox 使用。同一源码空 EXT 直载时保留 FongMi 元数据分类、搜索、详情和直链播放合同，但追更、History 与网盘资源功能必须使用 AList-TVBox 生成的订阅。

完整功能不要把 `.py` 文件直接添加为普通 FongMi 站点，也不要手工填写外层 `api`、`token`、`secret`、`loader`、`source` 或 `raw`。

## 使用前准备

只需准备两项：

1. 可从 AList-TVBox 访问的本仓库 `spiders_v2.json` 地址。
2. TMDB API Read Access Token，用于 TMDB 数据和完整追更功能。

TMDB Token 获取方法：

1. 登录 [TMDB](https://www.themoviedb.org/)。
2. 打开“头像 → 设置 → API”，也可直接访问 [API 设置页](https://www.themoviedb.org/settings/api)。
3. 申请 API 权限后，复制页面中的 **API Read Access Token**。
4. 把完整 Token 填入 `tmdb_access_token`，不要填写账号密码。

如需把本地追更结果写回 AList-TVBox History，还需一个能登录容器 Web 后台的 `USER` 或 `ADMIN` 账号。只读取 History 不需要填写账号。

## 仓库结构

把以下文件放到同一个 HTTPS 静态仓库：

```text
spiders_v2.json
py/
  豆瓣TMDB追更单入口.py
```

源码地址必须以 `.py` 结尾。AList-TVBox 会自动生成 `csp_PyProxy`、`spring.jar`、`loader=/Atvp.py?v=...`、`.py source` 和 `raw=true`。

## Web 界面部署

以下名称对应 AList-TVBox 1.42.0 Web 页面。

### 1. 导入插件

1. 使用管理员账号登录 AList-TVBox。
2. 打开顶部菜单 **订阅**。
3. 点击 **订阅源管理**。
4. 在 **仓库地址** 中粘贴 `spiders_v2.json` 地址，点击 **导入仓库**。
5. 在下方列表找到“豆瓣 TMDB 追更助手”，确认 **启用** 已打开，状态为“正常”。

也可在 **插件地址** 中直接填写公开的 `.py` 地址并点击 **添加插件**，但使用本包时推荐导入仓库，便于后续刷新版本。

### 2. 填写插件 EXT

1. 在插件所在行点击 **配置**，打开 **扩展配置**。
2. 复制 `extend.example.json` 的全部内容到文本框。
3. 只需把 `YOUR_TMDB_READ_ACCESS_TOKEN` 替换成自己的 TMDB Token。
4. 需要 History 双向同步时，再填写 `history_username` 和 `history_password`。
5. 点击 **保存配置**，回到列表后点击该插件的 **刷新**。

示例中的 `_说明_*` 是合法 JSON 字段，仅用于中文注释，插件会忽略，可以保留。

### 3. 加载订阅

1. 回到 **订阅管理** 页面。
2. 使用已有订阅，或点击 **添加** 新建订阅。
3. 复制列表中的 **TvBox 配置地址**，地址形如 `/sub/{安全Token}/{订阅ID}`。
4. 在 FongMi/TvBox 中把该地址设为配置地址并刷新配置。
5. 进入“豆瓣 TMDB 追更助手”。

需要追更、History 和网盘资源时，不要把插件 `.py` 地址直接填入 FongMi/TvBox。

## EXT 必要字段

| 字段 | 是否必填 | 填写方法 |
| --- | --- | --- |
| `atvp_plugin_mode` | 必填 | 固定为 `alist-tvbox-raw`，不要修改。 |
| `tmdb_access_token` | 完整功能必填 | 从 TMDB 的“设置 → API → API Read Access Token”复制。只浏览豆瓣公开内容时可留空，但 TMDB 和相关追更功能不可用。 |
| `history_username` | 云写入可选 | 使用能登录当前 AList-TVBox 的 `USER` 或 `ADMIN` 用户名。后台有 **用户** 菜单时，也可在其中添加用户。 |
| `history_password` | 云写入可选 | 与上面用户名对应的登录密码。用户名和密码必须同时填写。 |
| `resource_search_modes` | 推荐保留 | 默认示例启用 `vod1`、`vod`、`pansou`、`telegram`；插件会自动隐藏后端缺少的模式。 |

其余性能参数已有安全默认值，首次使用无需填写。插件 EXT 会随订阅下发，应保护订阅地址。

## 首次使用

1. 先在 FongMi 其他站点收藏或播放剧集；也可从本插件导航卡直接打开全局搜索后完成收藏或播放。
2. 打开“追更确认”，检查本机收藏和播放记录中的待选剧集，点击后确认加入追更。
3. 导航页点击电影或剧集卡始终直接打开 FongMi 全局搜索，不在导航页切换追更方式。
4. 在“追更动态”查看新集，在“追更管理”查看全部已追更记录。
5. 标记已看或取消追更时，进入“追更管理”选择对应操作，再点击项目和确认卡。
6. 需要查看同步状态、立即重试或检测通讯时，打开“追更管理”；首页不再提供独立“云端历史”分类。
7. 在详情中先选季集，再选择评分较高或已有续播记录的线路。

添加、取消和标记已看的结果会显示持久状态卡，不需要依赖 Toast 判断操作是否成功。History 同步成功仅在“追更管理”保留最近结果；同步中或失败时，“追更动态”也会显示可重试告警。

首次加入追更时即使还没有播放记录，打开详情也会按标题和别名直接搜索 AList-TVBox。History 只用于续播集和播放位置，不是资源搜索的前置条件。搜索结果必须继续通过详情解析、链接盘检和真实播放探测；没有可信结果时保持空线路，不生成假播放项。

追更动作在开始、完成或失败等每个状态变化时各提交一次追更页定向刷新。直接刷新失败时最多等待约 1 秒再检查一次当前可见追更页，普通浏览分类不会被后台补全反复刷新。

## 资源匹配规则

- 优先接受标准化后完全相同的标题。
- 可接受标题前后的季号、年份、集数、画质、字幕、编码和剧集类别等资源说明。
- 不使用编辑距离或任意近似匹配，例如“测试剧集2”不会匹配“测试剧集”。
- 解说、剪辑、预告、花絮、幕后、制作特辑、特别节目和衍生内容会被拒绝。
- 明确多季剧必须匹配当前追踪季；同季资源优先于无季号资源。
- 单季剧不把候选季号当作硬门禁，季号一致时仍有排序加分，错标候选只作为较低优先级备用。
- 多季剧当前季的资源年份可以不同于整部剧的首播年份；没有季号时，年份冲突仍会被拒绝。

## History 说明

- History 会在进入追更、资源详情等需要记录的页面时后台刷新，不需要日常手动操作。
- “追更确认”每次进入都会直接读取 FongMi 本机收藏和播放记录；未确认的条目保持待选，确认后才写入追更列表。
- “追更管理”始终提供“立即同步 History”和“检测通讯”，即使还没有追更剧集也可使用。
- `GET /history/{token}`：只读，不要求插件登录。
- `POST /history/{token}`：写入，需要 EXT 中配置 `USER` 或 `ADMIN` 账号。
- 用户名或密码任一留空：严格保持只读，不发送 POST，不影响 History 匹配、导入、追更进度、续播和过滤器。
- 云端读取暂时失败时，插件会使用过期缓存或本机记录继续处理，并禁止本轮上传；失败阶段和时间会保留在管理页。
- 上传、本机导入或追更进度回写单项失败时，其余已取得的有效结果仍会继续应用，管理页会保留失败阶段和时间。
- 自动同步与手动同步不会并发执行；重复点击只会提示当前任务仍在运行。
- 登录凭据只用于当前容器的 History 写入，不写入发布包。

## 过滤器复用

过滤器是可选功能，用于给其他 AList-TVBox 受管站点补充 History 选集、续播位置和最近可播线路。它不搜索资源，也不替换外站最终播放地址。

简要设置：

1. 打开 **订阅 → 过滤器管理**。
2. **过滤器地址** 填同一份 `豆瓣TMDB追更单入口.py` 的 HTTPS 直链。
3. **拦截点** 选择“详情”和“播放”。
4. **作用范围** 选择“除外”，在 **插件** 中选择本追更助手，避免自身被重复处理。
5. 点击 **添加过滤器**。
6. 在过滤器所在行点击 **配置**。保持表单默认值即可，也可在 **JSON 编辑** 中粘贴 `filter.example.json`。
7. 点击 **保存配置**，再点击该行 **刷新**。
8. 让 FongMi/TvBox 刷新订阅配置。

完整说明见 `FILTER.md`。插件和过滤器是两条独立记录，源码更新后需要分别点击 **刷新**。

## 常见问题

### 插件状态异常或看不到插件

确认仓库可由 AList-TVBox 访问，索引文件名为 `spiders_v2.json`，且其中的源码路径以 `.py` 结尾。重新导入仓库或点击插件行的 **刷新**。

### 提示不是 AList-TVBox raw 订阅

确认 EXT 中保留：

```json
{"atvp_plugin_mode":"alist-tvbox-raw"}
```

保存配置、刷新插件，再让 FongMi/TvBox 刷新配置。不要手填 `atvp_api` 或 `atvp_token`。

### TMDB 页面提示凭据无效

确认填写的是 TMDB **API Read Access Token**，没有多余空格，也没有误填 API Key、登录密码或整段网页内容。

### History 能读取但不能写入

确认 `history_username` 和 `history_password` 同时填写，且该账号能登录当前 AList-TVBox。`USER` 和 `ADMIN` 都允许。修改后保存配置并刷新插件。

### 过滤器没有生效

确认拦截点为“详情、播放”，作用范围覆盖目标插件，过滤器已启用且状态正常。更新源码后同时刷新插件和过滤器。

### 详情没有资源

插件只把 HTTP `404/405/501` 识别为后端缺失，并自动隐藏对应模式。如果所有模式都不可用，页面会明确显示无资源。

## 文件说明

- `../../py/豆瓣TMDB追更单入口.py`：明文源码。
- `../../spiders_v2.json`：插件仓库索引。
- `extend.example.json`：带中文说明、可直接粘贴的插件 EXT。
- `filter.example.json`：可直接粘贴到过滤器“JSON 编辑”的配置。
- `FILTER.md`：过滤器 Web 界面操作和边界。
- `CHANGELOG.md`：逐版本更新记录。
- `STATUS.md`：源码指纹、兼容基线和发布状态。

## 安全边界

- 发布包不包含服务器地址、订阅令牌、Cookie、账号密码、CK 或调试快照。
- 不接入网盘账号管理接口 `/api/pan/accounts/-/info`。
- 不修改 AList-TVBox 服务端、`Atvp.py`、`spring.jar` 或 FongMi APK。
- 本仓库公开提供明文源码；实际 EXT 会随订阅下发，应保护 AList-TVBox 订阅地址和容器访问权限。
