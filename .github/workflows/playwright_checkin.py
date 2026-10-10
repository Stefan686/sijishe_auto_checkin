

import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE_URL = "https://xsijishe.com"
SIGN_URL = BASE_URL + "/k_misign-sign.html"

SUCCESS_WORDS = [
    "今日已签到",
    "今天已经签到",
    "您今天已经签到过了",
    "今日已签",
    "签到成功",
    "打卡成功",
]

BLOCK_WORDS = [
    "just a moment",
    "checking your browser",
    "verify you are human",
    "attention required",
    "access denied",
]


def first_visible(page, selectors, timeout=3000):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            locator.first.wait_for(
                state="visible", timeout=timeout
            )
            return locator.first
        except Exception:
            continue
    return None


def blocked(page):
    title = page.title().lower()
    body = page.locator("body").inner_text(
        timeout=10000
    ).lower()

    return any(
        word in title or word in body
        for word in BLOCK_WORDS
    )


def wait_for_site(page):
    page.goto(
        SIGN_URL,
        wait_until="domcontentloaded",
        timeout=45000
    )
    page.wait_for_timeout(2500)

    print("当前页面标题:", page.title())

    if blocked(page):
        raise RuntimeError(
            "网站返回了安全验证页面，"
            "GitHub 云端浏览器暂时无法正常访问"
        )


def logged_in(page):
    # Discuz 登录后一般显示退出链接
    return page.locator(
        'a[href*="action=logout"]'
    ).count() > 0


def login(page, username, password):
    print("开始检查登录状态")

    wait_for_site(page)

    if logged_in(page):
        print("检测到已登录")
        return

    print("当前未登录，尝试打开登录窗口")

    login_link = first_visible(page, [
        'a[href*="mod=logging"][href*="action=login"]',
        'a:has-text("登陆账号")',
        'a:has-text("登录")',
    ], timeout=2000)

    if login_link:
        login_link.click()
        page.wait_for_timeout(1500)

    username_input = first_visible(page, [
        'input[name="username"]',
        'input[id^="username_L"]',
        'input[autocomplete="username"]',
        'input[placeholder*="用户名"]',
        'input[placeholder*="邮箱"]',
    ])

    password_input = first_visible(page, [
        'input[name="password"]',
        'input[id^="password3_L"]',
        'input[type="password"]',
    ])

    if not username_input or not password_input:
        raise RuntimeError(
            "没有找到登录表单，"
            "可能是页面结构变化或安全检查"
        )

    username_input.fill(username)
    password_input.fill(password)

    print("账号密码已填写，准备登录")

    login_button = first_visible(page, [
        'button[name="loginsubmit"]',
        'input[name="loginsubmit"]',
        'button:has-text("登录")',
        'input[type="submit"][value*="登录"]',
        'button:has-text("登陆")',
        'input[type="submit"][value*="登陆"]',
    ])

    if not login_button:
        raise RuntimeError("没有找到登录提交按钮")

    login_button.click()
    page.wait_for_timeout(4000)

    if blocked(page):
        raise RuntimeError(
            "登录后触发网站安全验证，"
            "未尝试绕过验证"
        )

    # 重新打开签到页确认登录状态
    wait_for_site(page)

    if not logged_in(page):
        raise RuntimeError(
            "登录后没有检测到有效会话；"
            "可能登录失败、出现验证码，"
            "或网站登录状态元素发生变化"
        )

    print("登录成功")


def is_checked_in(page):
    # 先检查当前账号对应的签到区域
    button = page.locator("#JD_sign")

    if button.count() > 0:
        label = button.first.inner_text(
            timeout=5000
        ).strip()

        if any(
            word in label
            for word in ["已签到", "已签", "已打卡"]
        ):
            return True

    # 检查网站明确的签到状态提示
    indicators = [
        "#JD_sign:has-text('今日已签')",
        ".alert:has-text('签到成功')",
        ".alert:has-text('今日已签到')",
    ]

    return any(
        page.locator(selector).count() > 0
        for selector in indicators
    )


def checkin(page):
    print("进入司机社签到页面")

    wait_for_site(page)

    if not logged_in(page):
        raise RuntimeError("签到前检测到登录状态失效")

    if is_checked_in(page):
        print("SUCCESS: 今日已经签到")
        return True

    button = first_visible(page, [
        "#JD_sign",
        'a:has-text("立即签到")',
        'button:has-text("立即签到")',
    ], timeout=5000)

    if not button:
        raise RuntimeError(
            "未找到签到按钮，"
            "需要检查网站页面结构"
        )

    print("找到签到按钮，准备点击")

    # 处理普通 JavaScript 确认框
    page.once(
        "dialog",
        lambda dialog: dialog.accept()
    )

    button.click(timeout=15000)
    page.wait_for_timeout(3000)

    # 可能出现网页内的普通确认按钮
    confirm = first_visible(page, [
        'button:has-text("确定签到")',
        'button:has-text("确认签到")',
    ], timeout=1000)

    if confirm:
        confirm.click()
        page.wait_for_timeout(2000)

    # 刷新，读取服务器保存后的签到状态
    wait_for_site(page)

    if is_checked_in(page):
        print("SUCCESS: 签到成功，状态已确认")
        return True

    # 部分版本使用签到提示文本
    body = page.locator("body").inner_text()

    if any(
        word in body for word in SUCCESS_WORDS
    ):
        print(
            "检测到签到提示，但需注意可能"
            "不是当前账号的专属状态"
        )

    raise RuntimeError(
        "点击签到后未确认成功，"
        "请检查签到接口、提示或按钮结构"
    )


def run_account(browser, username, password):
    context = browser.new_context(
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={
            "width": 1366,
            "height": 900
        }
    )

    page = context.new_page()

    try:
        login(page, username, password)
        return checkin(page)
    finally:
        context.close()


def main():
    accounts = json.loads(
        os.environ["ACCOUNTS_JSON"]
    )

    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True
        )

        try:
            for index, account in enumerate(
                accounts, start=1
            ):
                print(
                    f"\n===== 开始处理账号 {index} =====",
                    flush=True
                )

                try:
                    success = run_account(
                        browser,
                        account["username"],
                        account["password"]
                    )

                    if success:
                        print(
                            f"账号 {index}: 签到完成"
                        )
                    else:
                        failed += 1

                except Exception as e:
                    failed += 1
                    print(
                        f"账号 {index} 签到失败："
                        f"{type(e).__name__}: {e}",
                        flush=True
                    )
        finally:
            browser.close()

    if failed:
        print(
            f"\n签到任务失败：{failed} 个账号未完成"
        )
        sys.exit(1)

    print("\n全部账号签到成功或已签到")


if __name__ == "__main__":
    main()
