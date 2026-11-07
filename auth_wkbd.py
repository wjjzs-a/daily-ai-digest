#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auth_wkbd.py — 刷新一个 WKBD 号的凭证，输出可直接填进 GitHub Secret 的 JSON。

用途：
  1. 首次部署时，从号池 auths/ 里取一个号，刷出一份干净的凭证
  2. 万一 60 天没跑、链断了，用它重新生成一份

用法：
  python auth_wkbd.py --src "D:/小美/workbuddy2api/auths/workbuddy-xxx.json" --out my_cred.json

输出格式（就是 WKBD_CRED 要填的内容）：
  {"account": {...}, "auth": {"accessToken": "...", "refreshToken": "...", ...}}
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REFRESH_URL = "https://copilot.tencent.com/v2/plugin/auth/token/refresh"
ORIGIN = "https://www.workbuddy.cn"


def jwt_claims(tok):
    parts = (tok or "").split(".")
    if len(parts) < 2:
        return {}
    p = parts[1].replace("-", "+").replace("_", "/")
    p += "=" * (-len(p) % 4)
    try:
        return json.loads(base64.b64decode(p))
    except Exception:
        return {}


def refresh(access, refresh_token):
    req = urllib.request.Request(
        REFRESH_URL,
        data=b"",
        headers={
            "Authorization": "Bearer " + (access or ""),
            "X-Refresh-Token": refresh_token,
            "X-Auth-Refresh-Source": "plugin",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CodeBuddy-Request": "1",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="号池 auths/ 下的 workbuddy-*.json")
    ap.add_argument("--out", help="输出文件；不给就打印到终端")
    args = ap.parse_args()

    with open(args.src, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 兼容嵌套形 {"account":..,"auth":..} 与扁平形
    auth = raw.get("auth") or raw
    account = raw.get("account") or {}
    at = auth.get("accessToken") or ""
    rt = auth.get("refreshToken") or ""

    if not rt:
        print("源文件里没有 refreshToken", file=sys.stderr)
        return 1

    print(f"源账号: {account.get('nickname') or '?'}  ({account.get('uid', '')[:8]})", file=sys.stderr)
    old_claims = jwt_claims(rt)
    print(f"原 refreshToken 剩余: {(old_claims.get('exp', 0) - old_claims.get('iat', 0)) / 86400:.1f} 天周期", file=sys.stderr)

    try:
        resp = refresh(at, rt)
    except urllib.error.HTTPError as e:
        print(f"刷新失败 HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"刷新失败: {e}", file=sys.stderr)
        return 2

    data = resp.get("data") or {}
    new_at, new_rt = data.get("accessToken"), data.get("refreshToken")
    if not new_at:
        print(f"刷新无结果: code={resp.get('code')} msg={resp.get('msg')}", file=sys.stderr)
        return 2

    out = {
        "account": account,
        "auth": {
            "accessToken": new_at,
            "refreshToken": new_rt or rt,
            "realm": auth.get("realm") or "cn",
            "domain": auth.get("domain") or "www.workbuddy.cn",
        },
    }

    nc = jwt_claims(out["auth"]["refreshToken"])
    ac = jwt_claims(new_at)
    print(
        f"刷新成功。新 accessToken 有效至 "
        f"{ac.get('exp', 0)}，新 refreshToken 有效 60 天。",
        file=sys.stderr,
    )

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入: {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
