# 每日 AI 热点 + GitHub 热门 → Telegram

每天固定时间，抓 AI 新闻和 GitHub 热门，用大模型浓缩成一条简报，推到 Telegram。
跑在 GitHub Actions 上，**不需要你的电脑开机**。

代码在 `daily_ai.py`，纯标准库（`feedparser` 可选，装了更稳）。

---

## 一、先说清楚一个前提（重要）

你想用「WKBD 号池」的 API。它现在的地址是 `http://127.0.0.1:7863/v1`，只监听本机。
**GitHub Actions 的机器在微软的云上，访问不到你电脑的 127.0.0.1。** 这不是配置问题，
是网络拓扑的确定性结论 —— 内网回环地址在另一台机器上没有意义。

所以只有三条路：

| 方案 | 做法 | 云端可用 | 代价 |
|---|---|---|---|
| **A. 单号直连上游** | `LLM_MODE=wkbd` + 一个号的 token | ✅ | 凭证 30 天要续，单号额度/风控 |
| **B. 号池搬公网** | 号池带 Docker 镜像，部署到有公网 IP 的机器 | ✅ | 要服务器 |
| **C. 公开端点** | 智谱 `glm-4-flash`（永久免费）等 | ✅ | 要注册个 key |
| **D. 只在本机跑** | 号池 `127.0.0.1:7863` | ❌ | 电脑要开机 |

## 但是：单个 WKBD 号可以绕过号池，直连腾讯上游

我实测过，单账号凭证能直接打 `https://copilot.tencent.com/v2/chat/completions`，
**这是公网地址，Actions 能访问**。所以你说的「不用号池、用单个 WKBD 号」完全可行，
已经是本脚本的 `LLM_MODE=wkbd` 模式，并且本地跑通过、出过完整简报。

---

## 二、三种模式怎么切

全靠环境变量，代码不用改：

| `LLM_MODE` | 需要配什么 |
|---|---|
| `openai`（默认） | `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` |
| `wkbd` | `WKBD_CRED`（整段 JSON）或 `WKBD_ACCESS_TOKEN` + `WKBD_REFRESH_TOKEN`，加 `LLM_MODEL` |
| 留空 / 配不全 | 直接走降级版（纯列表） |

`LLM_MODEL` 支持逗号分隔多个，按顺序试：`deepseek-v4.1-flash,glm-5.3-flash`

### WKBD 模式的三条实测约束

1. **上游只接受 `stream: true`**，非流式会被拒，所以脚本自己解析 SSE 拼接文本。
2. **模型名是裸名**，不带 `cn:` 前缀（`cn:` 是号池自己加的路由标记）。
3. **必须带 `X-CodeBuddy-Request: 1` 和 `Origin`/`Referer`**，否则风控直接拒。

### 凭证怎么来、怎么续

从 `auths/workbuddy-<uid>.json` 里取 `auth.accessToken` 和 `auth.refreshToken`。

- `accessToken` 有效期 **30 天**（`expiresIn: 2592000`）
- `refreshToken` 有效期 **约 60 天**（`refreshExpiresIn: 5183999`）
- 脚本每次运行**先 refresh 再请求**，只要 refreshToken 没过期，accessToken 永远是新的

⚠️ **需要你知道的风险**：我本机连续两次用同一个 refreshToken 刷新都成功，说明它不是一次性的。
但云端和号池同时用一个 refreshToken 刷新会不会冲突，我没有长期数据。
如果号池那边开始报登录失效，大概就是这个原因。稳妥做法是**单独拿一个号给这个任务用**。

---

## 三、在本地先跑通（可选，但建议）

```powershell
cd D:\小美\_work\daily_ai

# 模式一：号池（本机跑才行）
$env:LLM_MODE     = "openai"
$env:LLM_BASE_URL = "http://127.0.0.1:7863/v1"
$env:LLM_API_KEY  = "wb2a-xxxxxxxx"
$env:LLM_MODEL    = "cn:glm-5.3-flash"

# 模式二：单号直连（云端也能用）
# $env:LLM_MODE  = "wkbd"
# $env:WKBD_CRED = Get-Content cred.json -Raw
# $env:LLM_MODEL = "deepseek-v4.1-flash,glm-5.3-flash"

$env:DRY_RUN = "1"      # 只打印，不发 Telegram

python daily_ai.py
```

顺手验证两件事：

```powershell
python _selftest.py      # Markdown 转换 + 字节切分自检
```

---

## 三、部署到 GitHub（正式用）

### 1. 建仓库

新建一个仓库，**建议设为 Public**（公开仓库的 Actions 完全免费，私有仓库扣额度），
把 `daily_ai.py`、`requirements.txt`、`.github/workflows/daily-ai.yml` 三个文件推上去。

### 2. 拿 Telegram 的两个值

1. Telegram 里搜 **@BotFather** → `/newbot` → 按提示起名 → 拿到 **token**（形如 `123456:ABC-DEF...`）
2. **给这个 bot 发一条消息**（必须主动发，bot 不能先开口）
3. 浏览器打开 `https://api.telegram.org/bot<你的token>/getUpdates`，
   找 `"chat":{"id":123456789,...}`，那个数字就是 **chat_id**

### 3. 填 Secrets

仓库 → Settings → Secrets and variables → Actions

**Secrets**（加密，日志里看不到）：

| 名字 | 值 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 上一步的 token |
| `TELEGRAM_CHAT_ID` | 上一步的 chat_id |
| `WKBD_CRED` | （用 wkbd 模式时）整段 `{"account":{...},"auth":{...}}` JSON |
| `LLM_BASE_URL` | （用 openai 模式时）端点根地址 |
| `LLM_API_KEY` | （用 openai 模式时）对应 key |

**Variables**（明文，方便改）：

| 名字 | 值 |
|---|---|
| `LLM_MODE` | `wkbd` 或 `openai` |
| `LLM_MODEL` | 裸模型名，如 `deepseek-v4.1-flash,glm-5.3-flash` |

> 注意：在 Actions 里用 wkbd 模式，`LLM_MODEL` 要写**裸名**（不带 `cn:`）。
> 裸名会直接透传给上游；带前缀的话脚本会自动剥掉，两种写法都能跑。

### 4. 手动跑一次

Actions 标签页 → `daily-ai` → `Run workflow`。跑通后再等每天的定时。

### 5. 改推送时间

改 `.github/workflows/daily-ai.yml` 里的 cron，**注意是 UTC**：

```
0 1 * * *    → 北京 09:00
0 11 * * *   → 北京 19:00
30 12 * * *  → 北京 20:30
```

---

## 四、故障与降级

脚本设计成「宁可糙，不能断」：

```
取数 → 有素材？──否──→ 直接退出，不推空消息
         │是
         ▼
   调模型生成摘要 ──失败──→ 降到「纯列表版」照样推
         │成功                  （标题+链接+star，无摘要）
         ▼
     推 Telegram
```

所以你能收到三种东西：

1. **正常版**：带判断的浓缩简报
2. **降级版**：开头有 ⚠️ 标记，只有标题和链接
3. **什么都没有**：说明连数据源都挂了，或者 Actions 本身失败

**「模型挂了」具体指什么**：key 额度用完 / key 过期或被重置 / 供应商限流 /
模型版本下线改名 / 接口格式变更 / 账号欠费。任一命中，当天就是降级版。

**Telegram 侧的两个坑**（代码已处理）：

- 单条消息上限是 **4096 UTF-8 字节**，中文一个字 3 字节，实际约 1365 字。
  代码按字节切分成多条，不会切断多字。
- `Markdown` 解析失败会退回纯文本重发一次，不会因为格式问题整条丢。

**已知的不确定性**：

- GitHub 的 `schedule` 不精确，高峰期可能延迟几分钟到半小时。
- 公开仓库 **60 天没有任何提交**，定时任务会被 GitHub 自动停用。偶尔手动跑一次即可。
- 数据源是第三方整理的 GitHub Trending 快照（`hanishrao/trending-collection`），
  它挂了会退回直抓 `github.com/trending` 的 HTML。

---

## 五、文件

| 文件 | 作用 |
|---|---|
| `daily_ai.py` | 主脚本：取数 + 摘要 + 推送 + 降级 |
| `auth_wkbd.py` | 刷新单个号的凭证，输出可填 Secret 的 JSON |
| `requirements.txt` | 只一个 `feedparser` |
| `.github/workflows/daily-ai.yml` | Actions 定时配置 |
| `_selftest.py` | 离线自检（Markdown 转换、字节切分） |
| `RESEARCH.md` | 方案检索与选型记录 |
| `run_local_test.ps1` | 本地一键试跑（参数化） |
| `.gitignore` | 排除 `private/` 等敏感与临时产物 |

`private/` 目录**不入库**，里面是：

- `wkbd_cred.json` — 刷好的凭证（就是 `WKBD_CRED` 要填的内容）
- `pool_removed/` — 从号池移出的原始凭证（备份用）
