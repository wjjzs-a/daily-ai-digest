#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_ai.py — 每日 AI 热点 + GitHub 热门，推到 Telegram。

设计原则：
  1. 只用标准库（feedparser 可选，装了就用，没装退回 xml.etree）
  2. 模型端点是 OpenAI 兼容，URL / KEY / MODEL 全走环境变量，不写死
  3. 模型调用失败 → 降级为「纯列表」照常推送，宁可糙不能断
  4. Telegram 单条硬上限 4096 UTF-8 字节，按字节切分，不切断多字节字符

环境变量：
  TELEGRAM_BOT_TOKEN   必填
  TELEGRAM_CHAT_ID     必填
  LLM_BASE_URL         OpenAI 兼容根，如 https://xxx/v1（留空则跳过摘要）
  LLM_API_KEY          对应 key
  LLM_MODEL            模型名，如 cn:deepseek-v4.1-flash
  DRY_RUN=1            只打印不发送
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CST = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-ai/1.0"

TRENDING_ALL = "https://cdn.jsdelivr.net/gh/hanishrao/trending-collection@main/api/daily/all.json"
TRENDING_FALLBACK = "https://github.com/trending?since=daily"

# 实测全部 200 可达；403/429 的源已剔除
FEEDS = [
    ("量子位", "https://www.qbitai.com/feed"),
    ("36氪", "https://www.36kr.com/feed"),
    ("雷锋网", "https://www.leiphone.com/feed"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("OpenAI", "https://openai.com/news/rss.xml"),
]

# 中文 AI 关键词，用于从综合科技源里筛 AI 相关条目（英文源不筛）
AI_HINTS = (
    "AI", "A.I.", "人工智能", "大模型", "模型", "智能体", "agent", "Agent",
    "推理", "训练", "算力", "芯片", "GPU", "机器人", "具身", "多模态", "开源",
    "OpenAI", "DeepSeek", "英伟达", "NVIDIA", "谷歌", "微软", "Meta", "豆包", "通义",
)
CN_FILTERED_SOURCES = {"36氪", "雷锋网"}

MAX_ITEMS_PER_FEED = 4

# 推理型模型（deepseek-v4.1 / glm 等）会先花大量 token 思考，预算给小了
# 会出现 finish_reason=length 且 content 为空。给足预算。
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS") or "16000")


def log(msg):
    print(f"[daily_ai] {msg}", file=sys.stderr)


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- GitHub 热门

def fetch_trending(limit=6):
    """优先 jsDelivr 的 JSON 快照，失败再抓 HTML。"""
    try:
        raw = json.loads(http_get(TRENDING_ALL))
        items = []
        for it in raw.get("items", []):
            items.append({
                "name": (it.get("title") or "").replace(" / ", "/").replace(" ", ""),
                "url": it.get("url", ""),
                "desc": (it.get("description") or "").strip(),
                "lang": it.get("language") or "",
                "stars": it.get("stars") or 0,
                "added": it.get("added_stars") or "",
            })
        if items:
            log(f"trending: JSON 源 {len(items)} 条")
            return items[:limit]
    except Exception as e:
        log(f"trending JSON 失败({e})，转 HTML")

    return _fetch_trending_html(limit)


def _fetch_trending_html(limit):
    html = http_get(TRENDING_FALLBACK).decode("utf-8", "replace")
    items = []
    # 每个仓库一块：<h2 class="h3 lh-condensed"><a href="/owner/repo">
    for m in re.finditer(
        r'<h2 class="h3 lh-condensed">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
    ):
        href, inner = m.group(1), m.group(2)
        name = re.sub(r"<[^>]+>", "", inner)
        name = re.sub(r"\s+", "", name)
        if not name or "/" not in name:
            continue
        block = html[m.end():m.end() + 2500]
        desc_m = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        desc = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else ""
        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
        star_m = re.search(r'/stargazers">\s*([\d,]+)', block)
        today_m = re.search(r"([\d,]+)\s+stars today", block)
        items.append({
            "name": name,
            "url": "https://github.com" + href,
            "desc": desc,
            "lang": lang_m.group(1) if lang_m else "",
            "stars": int(star_m.group(1).replace(",", "")) if star_m else 0,
            "added": f"{today_m.group(1)} stars today" if today_m else "",
        })
        if len(items) >= limit:
            break
    log(f"trending: HTML 兜底 {len(items)} 条")
    return items


# ---------------------------------------------------------------- RSS

def _strip_html(s):
    s = re.sub(r"<script.*?</script>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_rss_stdlib(data):
    """feedparser 缺失时的兜底解析，兼容 RSS2 / Atom。"""
    out = []
    try:
        root = ET.fromstring(data)
    except Exception:
        return out
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = desc = pub = ""
        for ch in node:
            t = ch.tag.split("}")[-1]
            if t == "title":
                title = _strip_html(ch.text or "")
            elif t == "link":
                link = (ch.text or "").strip() or ch.attrib.get("href", "")
            elif t in ("description", "summary", "content"):
                desc = _strip_html(ch.text or "")
            elif t in ("pubDate", "published", "updated"):
                pub = (ch.text or "").strip()
        if title:
            out.append({"title": title, "link": link, "desc": desc, "pub": pub})
    return out


def _parse_rss_feedparser(data):
    import feedparser
    d = feedparser.parse(data)
    out = []
    for e in d.entries:
        out.append({
            "title": _strip_html(e.get("title", "")),
            "link": e.get("link", ""),
            "desc": _strip_html(e.get("summary", "")),
            "pub": e.get("published", "") or e.get("updated", ""),
        })
    return out


def fetch_news():
    try:
        import feedparser  # noqa: F401
        parser = _parse_rss_feedparser
        log("RSS: 使用 feedparser")
    except ImportError:
        parser = _parse_rss_stdlib
        log("RSS: 无 feedparser，用标准库解析")

    news = []
    for feed in FEEDS:
        name, url = feed[0], feed[1]
        timeout = feed[2] if len(feed) > 2 else 20
        try:
            entries = parser(http_get(url, timeout=timeout))
        except Exception as e:
            log(f"feed 失败 {name}: {e}")
            continue
        picked = [e for e in entries if e.get("title")]
        if name in CN_FILTERED_SOURCES:
            picked = [
                e for e in picked
                if any(h in (e.get("title", "") + e.get("desc", "")) for h in AI_HINTS)
            ]
        picked = picked[:MAX_ITEMS_PER_FEED]
        for e in picked:
            e["source"] = name
        news.extend(picked)
        log(f"feed ok {name}: {len(picked)} 条")
    return news


# ---------------------------------------------------------------- 模型摘要

def build_prompt(news, trending):
    news_lines = []
    for i, n in enumerate(news[:26], 1):
        news_lines.append(f"{i}. [{n['source']}] {n['title']} :: {n['desc'][:180]}")

    gh_lines = []
    for i, g in enumerate(trending, 1):
        gh_lines.append(
            f"{i}. {g['name']} ({g['lang']}, ★{g['stars']}, {g['added']}) :: {g['desc'][:120]}"
        )

    return f"""你是给电子信息工程专业大学生（大二，正在找实习）写每日简报的编辑。

下面是今天抓到的原始素材。

【AI 新闻】
{chr(10).join(news_lines)}

【GitHub 热门】
{chr(10).join(gh_lines)}

请输出一条中文简报，严格按下面结构，不要开场寒暄、不要总结段：

## AI 热点
挑 3-5 条真正有信息增量的（模型发布、工程突破、产业动作、有意思的研究）。
每条一行：**标题** + 一句「为什么值得看」（不超过 40 字），关键数字必须保留。
不要搬运纯标题党，不要选「某某公司发布AI战略」这种没有硬信息的。

## GitHub 热门
挑 4 个。每个一行：`仓库名` — 一句话它是什么（不超过 30 字），语言 + star 数。
优先能动手玩、能学东西的；偏电子信息/嵌入式/AI 工程的加分。

## 今天可以点开的那个
从上面挑一个，说明具体理由（2-3 句）。要具体到「打开哪个文件、看什么」，
不要说「值得学习」这种空话。

语气自然，允许有判断和轻微吐槽。全文控制在 900 字以内。用 Markdown。"""


def llm_summarize(prompt):
    base = (os.environ.get("LLM_BASE_URL") or "").rstrip("/")
    key = os.environ.get("LLM_API_KEY") or ""
    mode = (os.environ.get("LLM_MODE") or "openai").strip().lower()

    models = [m.strip() for m in (
        (os.environ.get("LLM_MODEL") or "")
        + "," + (os.environ.get("LLM_MODEL_FALLBACK") or "")
    ).split(",") if m.strip()]
    if not models:
        log("摘要跳过：没配 LLM_MODEL")
        return None

    if mode == "wkbd":
        return _wkbd_summarize(models, prompt)

    if not base or not key:
        log("摘要跳过：LLM_BASE_URL / LLM_API_KEY 不全")
        return None

    # 主模型 + 备用模型依次尝试；任一成功即返回
    for model in models:
        text = _llm_once(base, key, model, prompt)
        if text:
            return text
    return None


# ----------------------------------------------------- WKBD 单账号直连模式
#
# 上游调用要点（从 wb2api 源码与实测得出）：
#   1. 强制 stream:true，非流式会被拒，所以必须自己解析 SSE
#   2. accessToken 30 天有效，可用 refreshToken 换新（refreshToken 约 60 天）
#   3. 模型名是裸名（deepseek-v4.1-flash），不带 cn: 前缀
#   4. 必须带 X-CodeBuddy-Request: 1 与 Origin/Referer，否则风控拒

WKBD_CHAT_URL = "https://copilot.tencent.com/v2/chat/completions"
WKBD_REFRESH_URL = "https://copilot.tencent.com/v2/plugin/auth/token/refresh"
WKBD_ORIGIN = "https://www.workbuddy.cn"


def _wkbd_headers(token, extra=None):
    h = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CodeBuddy-Request": "1",
        "Origin": WKBD_ORIGIN,
        "Referer": WKBD_ORIGIN + "/",
        "User-Agent": UA,
    }
    if extra:
        h.update(extra)
    return h


def _wkbd_load_cred():
    """从环境变量读凭证。支持两种写法：
    WKBD_CRED        整段 JSON（{"account":{...},"auth":{...}} 或扁平 {"accessToken":...}）
    WKBD_ACCESS_TOKEN / WKBD_REFRESH_TOKEN   分开两个变量
    """
    raw = (os.environ.get("WKBD_CRED") or "").strip()
    if raw:
        try:
            j = json.loads(raw)
        except Exception as e:
            log(f"WKBD_CRED 不是合法 JSON: {e}")
            return None
        auth = j.get("auth") or j
        return {
            "access": auth.get("accessToken") or "",
            "refresh": auth.get("refreshToken") or "",
        }
    return {
        "access": (os.environ.get("WKBD_ACCESS_TOKEN") or "").strip(),
        "refresh": (os.environ.get("WKBD_REFRESH_TOKEN") or "").strip(),
    }


def _wkbd_refresh(cred):
    """用 refreshToken 换新 accessToken。失败返回 None。"""
    rt = cred.get("refresh") or ""
    if not rt:
        return None
    req = urllib.request.Request(
        WKBD_REFRESH_URL,
        data=b"",
        headers=_wkbd_headers(cred.get("access") or "", {
            "X-Refresh-Token": rt,
            "X-Auth-Refresh-Source": "plugin",
        }),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        data = j.get("data") or {}
        new_token = data.get("accessToken") or ""
        if not new_token:
            log(f"refresh 无 accessToken: code={j.get('code')} msg={j.get('msg')}")
            return None
        log(f"refresh 成功，expiresIn={data.get('expiresIn')}s")
        cred["access"] = new_token
        if data.get("refreshToken"):
            cred["refresh"] = data["refreshToken"]
        return new_token
    except urllib.error.HTTPError as e:
        log(f"refresh HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        return None
    except Exception as e:
        log(f"refresh 失败: {e}")
        return None


def _wkbd_chat(token, model, prompt, max_tokens):
    """上游强制流式，这里拼 SSE 拿完整文本。"""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        WKBD_CHAT_URL,
        data=body,
        headers=_wkbd_headers(token, {"Accept": "text/event-stream"}),
        method="POST",
    )
    content, usage, finish = [], None, ""
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                j = json.loads(payload)
            except Exception:
                continue
            if j.get("usage"):
                usage = j["usage"]
            for ch in j.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    content.append(delta["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    return "".join(content), usage, finish


def _wkbd_summarize(models, prompt):
    cred = _wkbd_load_cred()
    if not cred or (not cred.get("access") and not cred.get("refresh")):
        log("WKBD 模式：没拿到凭证")
        return None

    # 先刷新拿新 token；刷新失败就用现有 accessToken 试一次
    token = _wkbd_refresh(cred)
    refreshed = token is not None
    if not token:
        token = cred.get("access") or ""
        if not token:
            log("WKBD 模式：refresh 和 access 都不可用")
            return None

    for model in models:
        bare = model.split(":", 1)[-1] if ":" in model else model
        for attempt in (1, 2):
            try:
                text, usage, finish = _wkbd_chat(token, bare, prompt, MAX_TOKENS)
                text = re.sub(r"<think.*?</think>", "", text, flags=re.S).strip()
                if text and len(text) >= 80:
                    u = usage or {}
                    log(
                        f"[{bare}] 摘要成功：{len(text)} 字 "
                        f"(in={u.get('prompt_tokens')} out={u.get('completion_tokens')})"
                    )
                    return text
                if not text:
                    log(f"[{bare}] 空回复 finish={finish}")
                else:
                    log(f"[{bare}] 摘要过短({len(text)}字)")
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:250]
                log(f"[{bare}] HTTP {e.code}: {detail}")
                # 401/403 且还没刷过 → 刷一次重试
                if e.code in (401, 403) and attempt == 1 and not refreshed:
                    token = _wkbd_refresh(cred) or token
                    refreshed = True
                    continue
                break
            except Exception as e:
                log(f"[{bare}] 调用失败: {e}")
                break
    return None


def _llm_once(base, key, model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")

    req = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            j = json.loads(r.read())
        ch = j["choices"][0]
        msg = ch.get("message") or {}
        text = (msg.get("content") or "").strip()
        # 部分模型会把推理过程塞进来，去掉 think 块
        text = re.sub(r"<think.*?</think>", "", text, flags=re.S).strip()

        if not text:
            u = j.get("usage") or {}
            rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            log(
                f"[{model}] 摘要为空：finish={ch.get('finish_reason')} "
                f"reasoning_tokens={rt}（推理吃满预算，调大 LLM_MAX_TOKENS）"
            )
            return None
        if len(text) < 80:
            log(f"[{model}] 摘要过短({len(text)}字)，视为失败")
            return None
        log(f"[{model}] 摘要成功：{len(text)} 字")
        return text
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        log(f"[{model}] 模型 HTTP {e.code}: {detail}")
        return None
    except Exception as e:
        log(f"[{model}] 模型调用失败: {e}")
        return None


# ---------------------------------------------------------------- 降级输出

def fallback_text(news, trending, reason):
    lines = ["⚠️ *今日简报降级版*", f"_摘要生成失败：{reason}_", ""]
    lines.append("## AI 新闻")
    for n in news[:10]:
        lines.append(f"• [{n['source']}] {n['title']}")
        if n["link"]:
            lines.append(f"  {n['link']}")
    lines.append("")
    lines.append("## GitHub 热门")
    for g in trending:
        lines.append(f"• `{g['name']}` {g['lang']} ★{g['stars']} ({g['added']})")
        if g["desc"]:
            lines.append(f"  {g['desc'][:100]}")
        lines.append(f"  {g['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 格式转换

def md_for_telegram(text):
    """把模型输出的 GFM 转成 Telegram legacy Markdown。

    Telegram 的 Markdown 只认单星号加粗，模型给的是双星；
    `##` 标题、表格分隔线在 Telegram 里都是乱码。这里做最小变换。
    """
    out = []
    for line in text.split("\n"):
        s = line.rstrip()
        # ## 标题 → 加粗
        m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", s)
        if m:
            out.append(f"*{m.group(1)}*")
            continue
        # **粗体** → *粗体*
        s = re.sub(r"\*\*(.+?)\*\*", r"*\1*", s)
        # 模型爱用的列表符统一成 •
        s = re.sub(r"^\s*[-*+]\s+", "• ", s)
        out.append(s)
    txt = "\n".join(out)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


# ---------------------------------------------------------------- Telegram

def tg_split(text, limit=3900):
    """按 UTF-8 字节切分，不切断多字节字符。"""
    chunks, buf, size = [], [], 0
    for line in text.split("\n"):
        piece = line + "\n"
        b = len(piece.encode("utf-8"))
        if size + b > limit:
            if buf:
                chunks.append("".join(buf))
                buf, size = [], 0
            # 单行就超限：按字符硬切
            while len(piece.encode("utf-8")) > limit:
                cut = len(piece)
                while len(piece[:cut].encode("utf-8")) > limit:
                    cut -= 1
                chunks.append(piece[:cut])
                piece = piece[cut:]
            if piece:
                buf.append(piece)
                size = len(piece.encode("utf-8"))
        else:
            buf.append(piece)
            size += b
    if buf:
        chunks.append("".join(buf))
    return chunks


def tg_send(text, dry=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    chat = os.environ.get("TELEGRAM_CHAT_ID") or ""
    if not token or not chat:
        log("Telegram 配置缺失，仅打印")
        print(text)
        return False

    chunks = tg_split(text)
    log(f"Telegram: 分 {len(chunks)} 条发送")
    for idx, part in enumerate(chunks, 1):
        if dry:
            print(f"\n===== chunk {idx}/{len(chunks)} =====\n{part}")
            continue
        body = json.dumps({
            "chat_id": chat,
            "text": part,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
            log(f"  chunk {idx} ok")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            log(f"  chunk {idx} HTTP {e.code}: {detail}")
            # Markdown 解析失败就退回纯文本重发一次
            if "can't parse entities" in detail or "parse" in detail.lower():
                body2 = json.dumps({
                    "chat_id": chat,
                    "text": part,
                    "disable_web_page_preview": True,
                }).encode("utf-8")
                req2 = urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=body2,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req2, timeout=30) as r2:
                        r2.read()
                    log(f"  chunk {idx} 纯文本重发 ok")
                except Exception as e2:
                    log(f"  chunk {idx} 重发也失败: {e2}")
                    return False
            else:
                return False
    return True


# ---------------------------------------------------------------- main

def main():
    dry = os.environ.get("DRY_RUN") == "1"
    now = datetime.now(CST)
    log(f"开始 {now:%Y-%m-%d %H:%M} CST  dry={dry}")

    trending = fetch_trending(limit=6)
    news = fetch_news()
    log(f"素材：news={len(news)} trending={len(trending)}")

    if not news and not trending:
        log("两个源都空，终止（避免推空消息）")
        return 1

    body = None
    fail_reason = ""
    if news and trending:
        body = llm_summarize(build_prompt(news, trending))
        if body is None:
            fail_reason = "模型不可用"
    else:
        fail_reason = "素材不足"

    if body:
        header = f"*{now:%m月%d日} AI 简报*\n\n"
        text = header + md_for_telegram(body)
    else:
        text = md_for_telegram(fallback_text(news, trending, fail_reason or "未知"))

    ok = tg_send(text, dry=dry)
    log("推送完成" if ok else "推送失败")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
