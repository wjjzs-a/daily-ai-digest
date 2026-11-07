# RESEARCH — 每日 AI 热点 + GitHub 热门（云端定时推送）

创建日期：2026-11-07

## 需求

每天固定时间，把「AI 行业热点 + GitHub 热门项目」推到手机（Telegram）。要求不依赖
本机开机。模型优先用本机 WorkBuddy 号池网关（wb2api，OpenAI 兼容）。

## 检索记录

### 轮次 1 · 调度器（中英文）

| 关键词 | 平台 | 结果 |
|---|---|---|
| `HanaAgent OpenHanako 定时任务 云端` | web_search | 只捞到 issue 列表，无云端执行 |
| `云端执行` / `remote executor` / `server-side cron` | 本地 asar 全文检索 | 0 命中 → Hana 的 cron 只有本机实现 |
| `GitHub Actions 访问 localhost 本地服务` | web_search | 确认 Actions 跑在微软托管 runner，**无法**访问 127.0.0.1 |
| `GitHub Actions 定时任务 cron` | web_search | 标准做法：`on.schedule.cron`，UTC 时区 |

**采用**：GitHub Actions 作为调度器。理由：免费额度 2000 分钟/月、公开仓库无限、
服务器常驻、无需自备机器。

**弃用**：Cloudflare Tunnel 反向暴露本机网关 —— 需要本机 7×24 开机，等于没解决原问题。
**弃用**：自建 VPS —— 有月费，且当前无可用服务器（本机无 docker、无 ssh known_hosts）。

### 轮次 2 · GitHub Trending 数据源（英文）

| 关键词 | 平台 | 候选 |
|---|---|---|
| `github trending api python` | GitHub API | `doforce/github-trending`(★67)、`NiklasTiede/Github-Trending-API`(★64)、`hanishrao/trending-collection`(★13) |
| `github-trending` | PyPI | `github-trending` v1.0.6、`github-trending-api` v0.2.2 |
| `github-trending-scraper` | GitHub | `LittleBreak/github-trending-scraper`(★3) |

**采用**：`hanishrao/trending-collection` 的 jsDelivr JSON
`https://cdn.jsdelivr.net/gh/hanishrao/trending-collection@main/api/daily/all.json`

理由（实测）：返回字段完整 `title/url/description/language/stars/added_stars`，
直接给「今日新增 star」，比裸抓 HTML 稳；jsDelivr 走 CDN，Actions 里访问快、不受
GitHub 页面结构改版影响。实测 17 条 / 语言维度也可用 `.../daily/python.json`。

**弃用**：PyPI 的 `github-trending` 包 —— 依赖解析 HTML，页面改版即挂，且无 added_stars。
**弃用**：自己写爬虫 —— 除非 JSON 源挂了，作为 fallback 保留（已实现 HTML 兜底）。

### 轮次 3 · AI 新闻源（中英文、抓取可达性实测）

| 源 | URL | 实测 |
|---|---|---|
| 量子位 | `https://www.qbitai.com/feed` | ✅ 200 / 6.6KB |
| 机器之心 | `https://www.jiqizhixin.com/rss` | ✅ 200 / 7.6KB |
| TechCrunch AI | `https://techcrunch.com/category/artificial-intelligence/feed/` | ✅ 200 / 17.8KB |
| The Verge AI | `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` | ✅ 200 / 64.8KB |
| OpenAI News | `https://openai.com/news/rss.xml` | ✅ 200 / 832KB |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | ✅ 200 / 265KB |
| Google AI Blog | `https://blog.google/technology/ai/rss/` | ✅ 200 / 30.8KB |
| 机器之心 RSSHub 36kr | `https://rsshub.app/36kr/newsflashes` | ❌ 403（公共实例限流） |
| VentureBeat AI | `https://venturebeat.com/category/ai/feed/` | ❌ 429（限流，不稳定，弃用） |

**采用**：qbitai + jiqizhixin（中文视角）+ TechCrunch AI + The Verge AI + OpenAI News +
HuggingFace Blog。中英文混合，避免单一来源的立场偏斜。

**解析库**：优先 `feedparser`，缺失时退回标准库 `xml.etree`（Actions 里装一次即可，本地无依赖也能跑）。

### 轮次 4 · 推送通道（中文）

| 关键词 | 平台 | 结论 |
|---|---|---|
| `Server酱 微信推送 免费` | web_search | sct.ftqq.com，免费版每天条数有限 |
| `pushplus 微信推送` | web_search | 免费版带广告 |
| `Telegram Bot API sendMessage 4096` | web_search | 单条上限 4096 字节，建议 3800~4000；**中文 1 字 3 字节**，需按字节切分 |

**采用**：Telegram Bot API `sendMessage`。
**弃用**：Server酱 / PushPlus —— 用户明确指定 Telegram，且 TG 无广告、无每日额度。

**踩坑记录**：4096 是 **UTF-8 字节**上限而非字符数，纯中文安全上限约 1365 字。
切分必须按字节累加，且不能切断多字节字符。

### 轮次 5 · 模型端点（关键约束）

| 方案 | 可行性 |
|---|---|
| Actions 直连本机 `http://127.0.0.1:7863` | ❌ 不可能，runner 在微软云 |
| 本机 Cloudflare Tunnel 暴露 | ⚠️ 可行但需本机常开，抵消方案价值 |
| 把 wb2api 部署到 VPS（有 Docker 镜像） | ⚠️ 可行，需服务器 + 账号凭证迁移 |
| Actions 内用公开模型 API | ✅ 最省事，URL/key/模型名三者都做成环境变量 |

**决策**：代码全部走环境变量 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`，**不写死**。
今天指向任何公开端点，将来号池网关上了公网，改一个 secret 即可切换，无需动代码。
模型调用失败时**降级为纯列表推送**（不生成摘要），保证「宁可糙，不能断」。

## 未解决的 / 需要注意

- GitHub 免费仓库的 `schedule` 在**仓库 60 天无提交**后会自动停用，需偶尔 touch 一下。
- `schedule` 触发不精确，高峰期可能延迟几分钟到半小时，不适合对分钟级精度有要求的任务。
- Actions runner 的出口 IP 是微软机房 IP，部分国内站点可能拒绝，所以新闻源优先选已验证可达的。
