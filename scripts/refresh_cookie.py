#!/usr/bin/env python3
"""刷新抖音【登录态】cookie。

抖音已把博主作品列表锁在登录后:游客 cookie 会撞登录墙、只能拿到缓存旧数据。
本脚本用系统 Chrome 打开抖音登录页,你用手机抖音App扫码登录后,自动把登录态
cookie 抠出来保存,之后 fetch 就能抓到实时数据。

用法:
    /Users/apple/.cc-switch/skills/douyin/.venv/bin/python scripts/refresh_cookie.py

依赖:playwright(pip 装,清华镜像) + 系统 Google Chrome。cookie 每隔几周会过期,再跑一次即可。
"""
import os
import sys
import time
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from playwright.sync_api import sync_playwright

HOME = "https://www.douyin.com/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _has_session(cookies) -> bool:
    return any(c["name"] in ("sessionid", "sessionid_ss") and c["value"] for c in cookies)


def main() -> int:
    logged = False
    cookies = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA)
        page = ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        # 尝试点开登录框(点不到就靠自己点右上角"登录")
        try:
            page.get_by_text("登录", exact=True).first.click(timeout=4000)
        except Exception:
            pass
        print(">>> 已打开 Chrome。请用手机抖音App扫码登录(最多等 150 秒)...", flush=True)
        for i in range(50):
            time.sleep(3)
            if _has_session(ctx.cookies()):
                logged = True
                time.sleep(4)  # 等 msToken/其它 cookie 落地
                break
            if i and i % 5 == 0:
                print(f"  ...等待扫码中 ({i*3}s)", flush=True)
        cookies = ctx.cookies()
        browser.close()

    if not logged:
        print("❌ 未检测到登录(没扫码或超时),cookie 未更新。")
        return 1

    dy = [c for c in cookies if "douyin.com" in c["domain"]]
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in dy)
    cli = os.path.join(SCRIPT_DIR, "cli.py")
    subprocess.run([sys.executable, cli, "cookie", "set", cookie_str])
    print(f"✅ 登录态 cookie 已更新(sessionid={'sessionid=' in cookie_str}, 长度 {len(cookie_str)})。"
          f"现在跑 fetch 就能抓实时数据了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
