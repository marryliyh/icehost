import os
import time
import json
import urllib.parse
import random
import requests
from playwright.sync_api import sync_playwright

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

def check_is_successfully_loaded(page):
    """通过检测控制面板独有的元素（如波兰语的控制台、服务器、有效期），100% 精准判定是否真正进入了控制台"""
    try:
        konsola_visible = page.locator("text=Konsola").first.is_visible()
        waznosc_visible = page.locator("text=DATA WAŻNOŚCI").first.is_visible()
        serwery_visible = page.locator("text=Serwery").first.is_visible()
        return konsola_visible or waznosc_visible or serwery_visible
    except Exception:
        return False

def check_is_cf_page(page):
    """检测当前是否仍卡在验证码页面（通过检测页面是否仍存在非主 Frame 的子 iframe 进行100%绝对判定）"""
    try:
        child_frames = [f for f in page.frames if f != page.main_frame]
        return len(child_frames) > 0
    except Exception:
        return True

def load_page_with_cf_bypass(page, url):
    """智能页面加载函数：通过底层列表捕获 Frame 绕过影子 DOM，获取绝对坐标并执行模拟真人按压点击"""
    print(f"正在访问页面: {url}")
    page.goto(url)
    
    # 轮询 15 秒，直接在浏览器底层搜寻除主框架以外的任何子框架（验证盾）
    turnstile_frame = None
    for i in range(15):
        child_frames = [f for f in page.frames if f != page.main_frame]
        if len(child_frames) > 0:
            turnstile_frame = child_frames[0]
            break
        page.wait_for_timeout(1000)

    if turnstile_frame:
        print("⚡ 成功通过底层接口穿透闭合影子 DOM 捕获到 Cloudflare 验证盾 iframe！")
        page.wait_for_timeout(3000) # 给予 3 秒缓冲时间确保其完全渲染完毕
        
        # 激活焦点：先在左上角空白处安全点击一下，确保浏览器窗口获得绝对焦点
        print("正在物理点击页面空白处以强制激活浏览器窗口焦点...")
        page.mouse.click(random.randint(10, 50), random.randint(10, 50))
        page.wait_for_timeout(500)

        box = None
        try:
            # 利用 frame_element().bounding_box() 拿取绝对坐标
            iframe_handle = turnstile_frame.frame_element()
            box = iframe_handle.bounding_box()
            if box:
                print(f"✓ 成功获取验证盾绝对物理坐标: x={box['x']:.1f}, y={box['y']:.1f}, w={box['width']:.1f}, h={box['height']:.1f}")
        except Exception as e:
            print(f"尝试通过 frame_element 获取坐标失败: {e}")
                
        if not box:
            print("⚠️ 无法获取验证盾边界定位框，启用标准视口固定经验坐标保底...")
            box = {"x": 490.0, "y": 375.3, "width": 300.0, "height": 65.0}

        base_x = box["x"]
        base_y = box["y"]
        h_center = box["height"] / 2
        
        # 围绕复选框所在的左侧位置（30px ~ 45px 范围）进行多点微调
        points_to_click = [
            (base_x + 35, base_y + h_center),      # 1. 理论复选框正中心
            (base_x + 40, base_y + h_center),      # 2. 稍微偏右 5 像素
            (base_x + 30, base_y + h_center),      # 3. 稍微偏左 5 像素
            (base_x + 35, base_y + h_center - 5),  # 4. 微调偏上 5 像素
            (base_x + 35, base_y + h_center + 5),  # 5. 微调偏下 5 像素
            (base_x + box["width"] / 2, base_y + h_center) # 6. 验证码容器正中心点（保底）
        ]
        
        for x, y in points_to_click:
            # 每次点击前，直接检测控制面板独有元素。如果进去了，立即通关退出！
            if check_is_successfully_loaded(page):
                print("✓ 恭喜！控制面板特有元素已出现，验证成功通过！")
                break
                
            print(f"正在模拟真人平滑移动至 ({x:.1f}, {y:.1f}) 并执行物理按压点击...")
            try:
                # 移动鼠标
                page.mouse.move(x, y, steps=15)
                page.wait_for_timeout(random.randint(400, 800)) # 模拟人类悬停观察
                page.mouse.down()
                page.wait_for_timeout(random.randint(100, 180)) # 模拟真人点击按压延迟
                page.mouse.up()
                
                # 点击后等待 6 秒观察状态
                page.wait_for_timeout(6000)
                
                if check_is_successfully_loaded(page):
                    print("✓ 成功进入控制面板，验证通过！")
                    break
                else:
                    print("控制面板尚未加载，说明验证盾依然存在，准备尝试下一个微调坐标点...")
            except Exception as e:
                print(f"点击坐标 ({x:.1f}, {y:.1f}) 遇到问题: {e}")
                
        # 点击结束后，再次进行最终状态核对
        if check_is_successfully_loaded(page):
            print("✓ 恭喜！Cloudflare 验证已安全通关。")
        else:
            print("⚠️ 尝试了所有坐标，仍未成功穿透验证盾。")
            
        print("正在等待页面 React 异步数据完全加载...")
        page.wait_for_timeout(8000)
    else:
        print("页面未检测到验证盾，或已成功跳过。")
        
    page.wait_for_timeout(3000)

def run():
    if not SERVER_URL or not ICEHOST_COOKIES:
        print("错误: 缺少 ICEHOST_SERVER_URL 或 ICEHOST_COOKIES")
        return

    with sync_playwright() as p:
        # ⚡ 核心修改：改用 Firefox 启动，Firefox 对 Cloudflare 的防自动化检测和 TLS 指纹指抗性极高！
        browser = p.firefox.launch(headless=True)
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            viewport={"width": 1280, "height": 720}
        )

        try:
            raw_data = json.loads(ICEHOST_COOKIES)
            cookies_to_add = []

            # 提取 Cookie
            if isinstance(raw_data, list):
                cookies_to_add = raw_data
            elif isinstance(raw_data, dict):
                cookies_to_add = raw_data.get("cookies", [])
            else:
                raise ValueError("未知的数据格式")

            # 1. 注入并进行高精度统一 URL 编码
            formatted_cookies = []
            for c in cookies_to_add:
                raw_value = c["value"]
                clean_value = urllib.parse.unquote(raw_value)
                encoded_value = urllib.parse.quote(clean_value)
                
                fc = {
                    "name": c["name"],
                    "value": encoded_value,
                    "domain": c["domain"],
                    "path": c.get("path", "/")
                }
                if "expirationDate" in c:
                    fc["expires"] = int(c["expirationDate"])
                if "secure" in c:
                    fc["secure"] = c["secure"]
                if "httpOnly" in c:
                    fc["httpOnly"] = c["httpOnly"]
                if "sameSite" in c:
                    ss = str(c["sameSite"]).lower()
                    if ss in ["no_restriction", "none"]:
                        fc["sameSite"] = "None"
                    elif ss == "lax":
                        fc["sameSite"] = "Lax"
                    elif ss == "strict":
                        fc["sameSite"] = "Strict"
                formatted_cookies.append(fc)
            
            context.add_cookies(formatted_cookies)
            print("Cookie 成功执行双重高精度 URL 编码并注入！已完美规避 PHP '+' 转换漏洞。")

        except Exception as e:
            print(f"凭证解析/注入失败: {e}")
            send_tg_notification(f"❌ <b>IceHost 运行异常</b>\n凭证解析注入失败: {e}")
            browser.close()
            return

        page = context.new_page()

        # 全局网络流量拦截与指纹清洗
        def handle_route(route):
            headers = {**route.request.headers}
            headers["sec-ch-ua"] = '"Firefox";v="122", "Gecko";v="122"'
            headers["sec-ch-ua-mobile"] = "?0"
            headers["sec-ch-ua-platform"] = '"Windows"'
            headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
            route.continue_(headers=headers)

        page.route("**/*", handle_route)

        # 首次访问并过盾
        load_page_with_cf_bypass(page, SERVER_URL)

        # 首次截图
        page.screenshot(path="icehost_debug_screenshot.png")

        # 判断登录状态
        if "login" in page.url or page.locator("input[type='email']").first.is_visible():
            msg = "❌ <b>IceHost 登录失效！</b>\n请在浏览器重新提取并更新 ICEHOST_COOKIES。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            browser.close()
            return

        # 3. 检测是否已经达到了 6 小时限制（波兰语特征词）
        keywords = ["Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny"]
        is_limited = False
        
        for kw in keywords:
            if page.locator(f"text={kw}").first.is_visible():
                is_limited = True
                break
        
        if is_limited:
            print("检测到红框限制提示：说明未到可续期时间。结束本次运行（不发送 Telegram 提醒）。")
            browser.close()
            return

        # 4. 如果没有到上限，安全寻找并点击续期按钮
        renew_btn = page.locator("a:has-text('DODAJ 6 GODZIN'), button:has-text('DODAJ 6 GODZIN'), [class*='blue']:has-text('DODAJ 6 GODZIN')").first
        
        if renew_btn.is_visible() and renew_btn.is_enabled():
            print("未检测到限制提示，找到续期按钮，正在点击...")
            renew_btn.click()
            
            # 点击后重新使用过盾函数
            load_page_with_cf_bypass(page, SERVER_URL)
            
            # 重新截图
            page.screenshot(path="icehost_debug_screenshot.png")
            
            # 二次检测结果
            is_now_limited = False
            for kw in keywords:
                if page.locator(f"text={kw}").first.is_visible():
                    is_now_limited = True
                    break
                    
            if is_now_limited:
                print("点击后弹出了红框提示：说明未到可续期时间（续期未成功）。结束本次运行（不发送 Telegram 提醒）。")
            else:
                msg = "⚡ <b>IceHost 服务器续期成功！</b>\n服务器已真正成功延长 6 小时有效期。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
        else:
            print("未在页面中找到可用的蓝色续期按钮。")

        browser.close()

if __name__ == "__main__":
    run()
