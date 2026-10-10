
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

URL = "https://xsijishe.com/k_misign-sign.html"

BLOCK_WORDS = [
    "just a moment",
    "checking your browser",
    "verify you are human",
    "attention required",
    "access denied",
    "请稍候",
    "验证您是否为真人",
    "检查您的浏览器",
]

def check_security(page):
    title = page.title().strip()
    print("页面标题:", title)
    print("页面地址:", page.url)

    if any(w in title.lower() for w in BLOCK_WORDS):
        raise RuntimeError(
            "网站返回安全检查页面，"
            "GitHub 云端浏览器无法继续自动登录"
        )

def find_visible(scope, selectors, timeout=1200):
    for selector in selectors:
        loc = scope.locator(selector).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            pass
    return None

def get_login_fields(page):
    # 查找主页面以及登录 iframe
    for frame in page.frames:
        username = find_visible(frame, [
            'input[name="username"]',
            'input[id^="username_L"]',
            'input[autocomplete="username"]',
            'input[placeholder*="用户名"]',
            'input[placeholder*="邮箱"]',
        ], 700)

        password = find_visible(frame, [
            'input[name="password"]',
            'input[id^="password3_L"]',
            'input[type="password"]',
        ], 700)

        if username and password:
            return frame, username, password

    return None, None, None

def already_logged_in(page):
    # 先排除仍显示游客登录菜单的情况
    logout = page.locator(
        'a[href*="action=logout"]'
    )
    if logout.count() > 0:
        return True

    # 游客标识是辅助判断，不单独证明登录成功
    return False

def open_login(page):
    print("尝试打开登录窗口")

    # 方法一：点击签到按钮触发登录
    sign = find_visible(page, [
        "#JD_sign",
        'a:has-text("签到")',
        'button:has-text("签到")',
    ])

    if sign:
        sign.click(timeout=8000)
        page.wait_for_timeout(1200)

        frame, user, pwd = get_login_fields(page)
        if user and pwd:
            print("签到按钮成功唤起登录弹窗")
            return

    # 方法二：寻找右上角登录入口
    login = find_visible(page, [
        'a:has-text("登陆账号")',
        'a:has-text("登录账号")',
        'a[href*="mod=logging"][href*="action=login"]',
    ])

    if not login:
        # 尝试展开头像附近的游客菜单
        avatar = find_visible(page, [
            'a:has-text("游客您好")',
            '[class*="user"] a',
            '[class*="avatar"]',
        ], 800)

        if avatar:
            avatar.hover()
            page.wait_for_timeout(700)

        login = find_visible(page, [
            'a:has-text("登陆账号")',
            'a:has-text("登录账号")',
        ])

    if login:
        login.click(timeout=8000)
        page.wait_for_timeout(1500)

    frame, user, pwd = get_login_fields(page)

    if not user or not pwd:
        check_security(page)
        raise RuntimeError(
            "登录窗口没有出现；"
            "需检查右上角头像和登录弹窗选择器"
        )

def login(page, username, password):
    print("打开签到页面")

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=45000
    )
    page.wait_for_timeout(2500)

    check_security(page)

    if already_logged_in(page):
        print("检测到已有登录会话")
        return

    open_login(page)

    frame, user, pwd = get_login_fields(page)

    if not user or not pwd:
        raise RuntimeError("没有找到账号密码输入框")

    print("找到登录表单")

    user.fill(username)
    pwd.fill(password)

    submit = find_visible(frame, [
        '[name="loginsubmit"]',
        'button:has-text("登录")',
        'input[type="submit"][value*="登录"]',
        'button:has-text("登陆")',
        'input[type="submit"][value*="登陆"]',
    ])

    if not submit:
        raise RuntimeError("找不到登录按钮")

    print("提交登录请求")
    submit.click(timeout=10000)

    # 根据实际网站行为等待约 3 秒
    page.wait_for_timeout(4000)

    check_security(page)

    # 再访问签到页，确认会话
    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=45000
    )
    page.wait_for_timeout(1500)

    check_security(page)

    if not already_logged_in(page):
        print("未找到退出链接，检查是否仍为游客")

        visitor = page.get_by_text(
            "游客您好", exact=True
        )

        if visitor.count() > 0:
            raise RuntimeError(
                "登录后仍显示游客状态，登录可能失败"
            )

        # 不将缺少游客文字直接当成登录成功
        raise RuntimeError(
            "无法确认登录成功，"
            "需要进一步定位网站的登录状态元素"
        )

    print("登录成功，开始签到")

def checkin(page):
    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=45000
    )
    page.wait_for_timeout(1500)

    check_security(page)

    # 只检查签到区域，避免排行榜文字误判
    area = page.locator("#JD_sign")

    if area.count() > 0:
        txt = area.first.inner_text().strip()
        print("签到按钮状态:", txt)

        if "已签到" in txt or "已签" in txt:
            print("SUCCESS: 今日已签到")
            return

    button = find_visible(page, [
        "#JD_sign",
        'button:has-text("立即签到")',
        'a:has-text("立即签到")',
    ])

    if not button:
        raise RuntimeError("未找到签到按钮")

    print("点击签到按钮")

    def handle_dialog(dialog):
        print("检测到确认弹窗")
        dialog.accept()

    page.on("dialog", handle_dialog)

    button.click(timeout=12000)
    page.wait_for_timeout(2000)

    confirm = find_visible(page, [
        'button:has-text("确认签到")',
        'button:has-text("确定签到")',
    ], 700)

    if confirm:
        confirm.click()
        page.wait_for_timeout(1500)

    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    check_security(page)

    area = page.locator("#JD_sign")

    if area.count() > 0:
        txt = area.first.inner_text().strip()
        print("签到后按钮状态:", txt)

        if "已签到" in txt or "已签" in txt:
            print("SUCCESS: 签到状态已确认")
            return

    raise RuntimeError(
        "已尝试点击签到，但没有确认成功；"
        "请检查页面签到状态"
    )

def main():
    accounts = json.loads(os.environ["ACCOUNTS_JSON"])
    failures = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            for index, account in enumerate(accounts, 1):
                print(f"\n===== 账号 {index} =====")

                context = browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1366, "height": 900}
                )

                try:
                    page = context.new_page()

                    login(
                        page,
                        account["username"],
                        account["password"]
                    )

                    checkin(page)

                except Exception as e:
                    failures += 1
                    print(
                        f"账号 {index} 失败："
                        f"{type(e).__name__}: {e}"
                    )

                finally:
                    context.close()

        finally:
            browser.close()

    if failures:
        print(f"共有 {failures} 个账号未完成")
        sys.exit(1)

    print("所有账号签到完成")

if __name__ == "__main__":
    main()
