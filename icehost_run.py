import os
import time
import json
import urllib.parse
import requests
from seleniumbase import SB

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")


def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("未配置 TG 机器人变量，跳过发送 TG 推送。")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
        print("TG 状态通知发送成功。")
    except Exception as e:
        print(f"发送 TG 消息异常: {e}")

    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": "IceHost 实时画面"}
                requests.post(url, data=data, files=files)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")


def run():
    if not SERVER_URL:
        msg = "❌ <b>IceHost 续期失败！</b>\n未配置 ICEHOST_SERVER_URL 环境变量，脚本无法运行。"
        print(msg)
        send_tg_notification(msg)
        return

    # 1. 启动 SeleniumBase 并开启 UC 免密/防检测模式与 Xvfb 虚拟桌面
    with SB(uc=True, xvfb=True) as sb:
        print(f"正在访问 IceHost 面板: {SERVER_URL}")
        # 使用 UC 专属重连模式访问，能极大缓解首屏 Cloudflare 阻断
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=8)
        sb.sleep(5)

        # 2. 注入 Cookies（智能兼容 JSON 或纯文本格式）
        if ICEHOST_COOKIES:
            try:
                cookies_to_add = []
                raw_cookies_str = ICEHOST_COOKIES.strip()

                # 尝试一：标准 JSON 格式
                try:
                    raw_data = json.loads(raw_cookies_str)
                    if isinstance(raw_data, list):
                        cookies_to_add = raw_data
                    elif isinstance(raw_data, dict):
                        cookies_to_add = raw_data.get("cookies", [])
                    print("检测到 JSON 格式 Cookie，正在解析...")

                # 尝试二：纯文本格式
                except json.JSONDecodeError:
                    print("检测到纯文本 Cookie 格式，正在自动提取...")

                    token_value = raw_cookies_str
                    if "icehostpl_session=" in token_value:
                        token_value = token_value.split("icehostpl_session=")[1].split(";")[0]
                    elif "XSRF-TOKEN=" in token_value:
                        token_value = token_value.split("XSRF-TOKEN=")[1].split(";")[0]

                    token_value = token_value.strip()

                    cookies_to_add = [
                        {"name": "icehostpl_session", "value": token_value, "domain": "dash.icehost.pl"},
                        {"name": "XSRF-TOKEN", "value": token_value, "domain": "dash.icehost.pl"}
                    ]

                # 统一注入
                for c in cookies_to_add:
                    raw_value = c["value"]
                    decoded_value = urllib.parse.unquote(raw_value)

                    cookie_dict = {
                        "name": c["name"],
                        "value": decoded_value,
                        "domain": c.get("domain", "dash.icehost.pl"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True)
                    }
                    if "sameSite" in c:
                        ss = str(c["sameSite"]).lower()
                        if ss in ["lax", "strict", "none"]:
                            cookie_dict["sameSite"] = ss.capitalize()

                    sb.add_cookie(cookie_dict)

                print("Cookie 成功注入！")
                sb.refresh()
                sb.sleep(5)

            except Exception as e:
                err_msg = f"⚠️ <b>IceHost Cookie 注入失败！</b>\n{e}"
                print(f"注入 Cookie 异常: {e}")
                send_tg_notification(err_msg, "icehost_debug_screenshot.png")
                return  # 🔧 Cookie 挂了没法继续，发通知后退出

        else:
            # 没有配 Cookie，也发通知
            msg = "⚠️ <b>IceHost 未配置 Cookie！</b>\nICEHOST_COOKIES 环境变量为空，无法登录面板。"
            print(msg)
            send_tg_notification(msg)
            return

        # 3. 核心过盾：物理点击 Cloudflare Turnstile 验证
        sb.save_screenshot("icehost_debug_screenshot.png")
        try:
            print("正在检测并调用系统级 PyAutoGUI 驱动，物理点击 Cloudflare 验证码...")
            sb.uc_gui_click_captcha()
            sb.sleep(10)
            sb.save_screenshot("icehost_debug_screenshot.png")
        except Exception as e:
            print(f"验证盾已被跳过或点击执行完毕: {e}")

        # 4. 判断登录状态
        current_url = sb.get_current_url()
        if "login" in current_url or sb.is_element_visible("input[type='email']"):
            msg = "❌ <b>IceHost 登录失效！</b>\nCookie 可能已过期，请在浏览器重新提取并更新 ICEHOST_COOKIES。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            return

        # 5. 判定红框限制（未到续期时间）
        page_source = sb.get_page_source()
        keywords = [
            "Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny",
            "cannot extend", "recently", "next 6 hours"
        ]
        is_limited = any(kw in page_source for kw in keywords)

        if is_limited:
            msg = "ℹ️ <b>IceHost 暂无可续期</b>\n检测到限制提示，说明今日已续期或未到 6 小时冷却时间，无需操作。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")  # 🔧 之前静默，现在发通知
            return

        # 6. 寻找并点击续期按钮
        renew_btn_selector = (
            "//*[not(*) and ("
            "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'dodaj 6') or "
            "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6')"
            ")]"
        )

        try:
            print("正在等待续期按钮加载...")
            sb.wait_for_element_visible(renew_btn_selector, timeout=15)
            print("找到续期按钮，正在点击...")
            sb.click(renew_btn_selector)

            sb.sleep(5)
            sb.save_screenshot("icehost_debug_screenshot.png")

            # 点击后检查是否弹出限制
            current_source = sb.get_page_source()
            is_failed_due_to_limit = any(kw in current_source for kw in keywords)

            if is_failed_due_to_limit:
                msg = "ℹ️ <b>IceHost 点击后被限制</b>\n续期按钮已点击，但页面弹出限制提示，说明暂不可续期。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")  # 🔧 之前静默，现在发通知
                return

            print("点击后未检测到报错，刷新确认结果...")
            sb.refresh()
            sb.sleep(5)
            sb.save_screenshot("icehost_debug_screenshot.png")

            updated_source = sb.get_page_source()
            is_now_limited = any(kw in updated_source for kw in keywords)

            if is_now_limited:
                msg = "✅ <b>IceHost 服务器续期成功！</b>\n服务器已成功延长 6 小时有效期。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
            else:
                msg = "ℹ️ <b>IceHost 续期指令已发送</b>\n按钮已点击，请检查下方截图确认是否成功。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")

        except Exception as e:
            error_msg = f"❌ <b>IceHost 续期异常！</b>\n未找到续期按钮，页面可能已改版或网络异常。\n错误: {e}"
            print(error_msg)
            send_tg_notification(error_msg, "icehost_debug_screenshot.png")


if __name__ == "__main__":
    run()
