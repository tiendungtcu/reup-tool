import json
import logging
import os
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread, Lock
import asyncio
from typing import Any, Callable, Dict, Optional

from fake_useragent import FakeUserAgentError, UserAgent
import ffmpeg
import requests
import schedule
import yt_dlp
import re

from patchright.sync_api import sync_playwright, TimeoutError, Error as PlaywrightError

# Replace ytnoti import with our custom PubSubHubbub server
from pubsubhubbub_server import PubSubHubbubServer, start_ngrok_tunnel
from pyngrok import ngrok

# Import TikTok uploader modules
from tiktok_uploader.bot_utils import (
    assert_success,
    assertSuccess,
    convert_tags,
    generate_random_string,
    printError,
    subprocess_jsvmp,
)
from tiktok_uploader.tiktok import upload_to_tiktok_optimized


# ====================== DEBUG HELPER ======================
def debug_page(page):
    """Lưu screenshot + DOM khi gặp sự cố (sync version)"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = "debug"
    os.makedirs(folder, exist_ok=True)

    screenshot_path = os.path.join(folder, f"upload_err_{ts}.png")
    dom_path = os.path.join(folder, f"upload_err_{ts}.html")

    try:
        page.screenshot(path=screenshot_path, full_page=True)
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"📸 Debug saved: {screenshot_path}, {dom_path}")
    except Exception as e:
        print(f"⚠️ Debug failed: {e}")


# ==========================================================


# Create a Video class to match ytnoti's Video interface
class Video:
    def __init__(self, id, title, url, channel_id, published):
        self.id = id
        self.title = title
        self.url = url
        self.channel = type("Channel", (), {"id": channel_id})()
        self.timestamp = type(
            "Timestamp",
            (),
            {
                "published": (
                    datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if published
                    else datetime.now(timezone.utc)
                )
            },
        )()


channel_events = {}
event_lock = Lock()  # Lock for thread-safe event initialization
apikey_error_channels = set()
FAIL_KEY_LIST = set()

# Initialize PubSubHubbub server instead of ytnoti
pubsub_server = None
websub_port = 8080

APP_CONFIGS = {}
ALL_CONFIGS = {}
ERROR_MSG = ""
ERR_FILE = Path("log/errors.log")
YT_COOKIE_FILE = "yt_cookies.txt"
event = Event()
is_rendered = {}

os.makedirs("downloads", exist_ok=True)
os.makedirs("processed", exist_ok=True)
os.makedirs("log", exist_ok=True)

# Configure the logging system
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",  # Include asctime for datetime
    datefmt="%Y-%m-%d %H:%M:%S",  # Define the datetime format
    handlers=[logging.FileHandler(ERR_FILE, mode="a"), logging.StreamHandler()],
)


def _default_pipeline_steps() -> Dict[str, bool]:
    return {
        "scan": True,
        "download": True,
        "render": True,
        "upload": True,
    }


def _sanitize_pipeline_steps(pipeline_steps: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    defaults = _default_pipeline_steps()
    if isinstance(pipeline_steps, dict):
        for key in defaults:
            if key in pipeline_steps:
                defaults[key] = bool(pipeline_steps[key])

    if defaults["upload"]:
        defaults["render"] = True
        defaults["download"] = True

    if defaults["render"] and not defaults["download"]:
        defaults["download"] = True

    if not defaults["render"]:
        defaults["upload"] = False

    if not defaults["download"]:
        defaults["render"] = False
        defaults["upload"] = False

    return defaults


def get_channel_pipeline_steps(channel: str) -> Dict[str, bool]:
    config = ALL_CONFIGS.get(channel, {}).get("config", {})
    return _sanitize_pipeline_steps(config.get("pipeline_steps"))


def send_telegram_message(channel, message, is_app=False):
    if is_app:
        tg_bots_str = APP_CONFIGS.get("telegram", "")
    else:
        channel_configs = ALL_CONFIGS[channel]["config"]
        tg_bots_str = channel_configs.get("telegram", APP_CONFIGS.get("telegram", ""))
    if not tg_bots_str:
        return
    tg_bots = tg_bots_str.split(";")
    for tg_bot_str in tg_bots:
        tg_data = tg_bot_str.split("|")
        try:
            url = f"https://api.telegram.org/bot{tg_data[1]}/sendMessage"
            payload = {
                "chat_id": tg_data[0],
                "text": f"Kênh Yt: {channel}\n{message}",
            }
            requests.post(url, data=payload)
        except Exception as e:
            print("⚠️ Không gửi được Telegram:", e)


# Load configs for all YT channels
def load_all_configs(base_folder="configs"):
    data = {}

    # Iterate through all subfolders in configs
    for subfolder in os.listdir(base_folder):
        subfolder_path = os.path.join(base_folder, subfolder)

        if os.path.isdir(subfolder_path):
            config_path = os.path.join(subfolder_path, "config.json")
            cookies_path = os.path.join(subfolder_path, "cookies.json")

            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except FileNotFoundError:
                er_msg = f"❌ Lỗi đọc config: Folder configs/{subfolder} thiếu file config.json"
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue
            except Exception as er:
                er_msg = f"❌ Lỗi đọc config: Folder configs/{subfolder} lỗi đọc file config.json, cần sửa file config.json"
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue

            try:
                with open(cookies_path, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
            except FileNotFoundError:
                er_msg = f"❌ Lỗi đọc cookies config: Folder configs/{subfolder} thiếu file cookies.json."
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue
            except Exception as er:
                er_msg = f"❌ Lỗi đọc cookies config: Folder configs/{subfolder}lỗi đọc file cookies.json, {er}"
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue
            if not config:
                er_msg = f"❌ Lỗi đọc cookies config: Folder configs/{subfolder} file config.json rỗng."
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue
            if not cookies:
                er_msg = f"❌ Lỗi đọc cookies config: Folder configs/{subfolder} file cookies.json rỗng."
                send_telegram_message(subfolder, er_msg, True)
                logging.error(er_msg)
                continue
            if config and cookies:
                data[subfolder] = {"config": config, "cookies": cookies}

    return data


# Initialize PubSubHubbub server
async def initialize_pubsub_server():
    global pubsub_server, websub_port

    try:
        # Get settings from APP_CONFIGS
        websub_url = APP_CONFIGS.get("websub_url")
        ngrok_auth_token = APP_CONFIGS.get("ngrok_auth_token")
        domain_type = APP_CONFIGS.get("domain_type", "ngrok")
        websub_port = APP_CONFIGS.get("websub_port", 8080)

        # Setup ngrok if needed
        ngrok_url = None
        if domain_type == "ngrok":
            if not ngrok_auth_token:
                raise Exception("Chưa nhập ngrok_auth_token trong file settings.json")
            ngrok.set_auth_token(ngrok_auth_token)
            ngrok_url = start_ngrok_tunnel(websub_port)
        else:
            ngrok_url = websub_url

        # Create PubSubHubbub server
        pubsub_server = PubSubHubbubServer(port=websub_port, ngrok_url=ngrok_url)

        # Add video callback
        pubsub_server.add_video_callback(handle_new_video)

        # Start server
        await pubsub_server.start_server()

        print(f"🟢 PubSubHubbub server started on port {websub_port}")
        if ngrok_url:
            print(f"🌐 Webhook URL: {ngrok_url}/webhook")

        return True

    except Exception as e:
        logging.error(f"Failed to initialize PubSubHubbub server: {e}")
        return False


# Video callback function (replaces the @notifier.upload() decorator)
def handle_new_video(video_data: dict):
    """Handle new video notifications from PubSubHubbub server."""
    try:
        # Convert video_data dict to Video object
        video = Video(
            id=video_data["id"],
            title=video_data["title"],
            url=video_data["url"],
            channel_id=video_data["channel_id"],
            published=video_data.get("published", ""),
        )

        # check if video uploaded
        current_time = datetime.now().strftime("%H:%M:%S")
        last_videoid_file = Path(f"log/{video.channel.id}")
        if (
            last_videoid_file.exists()
            and last_videoid_file.read_text().strip() == video.id
        ):
            print(f"⏳ websub lúc {current_time} Video mới đã đăng trước đó.")
            return None

        published_time_str = video.timestamp.published.astimezone().strftime("%H:%M:%S")
        tele_msg = f"📢 Lúc: {current_time} Phát hiện video mới từ websub:\n{video.title}\n{video.url}\nPhát hành: {published_time_str}"
        print(tele_msg)
        Thread(
            target=send_telegram_message,
            args=(
                video.channel.id,
                tele_msg,
            ),
            daemon=True,
        ).start()

        # Process video in a separate thread
        Thread(
            target=process_video_pipeline, args=(video.channel.id, video), daemon=True
        ).start()

    except Exception as e:
        logging.error(f"Error handling new video: {e}")


# Function to subscribe to channels
async def subscribe_to_channels():
    """Subscribe to all channels that use websub."""
    if not pubsub_server:
        logging.error("PubSubHubbub server not initialized")
        return

    websub_channels = [
        item
        for item in ALL_CONFIGS
        if ALL_CONFIGS[item]["config"]["detect_video"] in ["websub", "both"]
    ]

    if not websub_channels:
        print("No channels configured for WebSub")
        return

    print(f"Subscribing to {len(websub_channels)} channels...")

    for channel_id in websub_channels:
        try:
            channel_name = ALL_CONFIGS[channel_id]["config"].get(
                "channel_name", channel_id
            )
            success = await pubsub_server.subscribe_to_channel(channel_id, channel_name)
            if success:
                print(f"✅ Subscribed to {channel_name} ({channel_id})")
            else:
                print(f"❌ Failed to subscribe to {channel_name} ({channel_id})")
        except Exception as e:
            logging.error(f"Error subscribing to channel {channel_id}: {e}")


def get_video_duration(input_file):
    """Get the duration of a video in seconds."""
    try:
        probe = ffmpeg.probe(input_file)
        duration = float(probe["format"]["duration"])
        return duration
    except ffmpeg.Error as e:
        print(f"Error getting duration: {e}")
        sys.exit(1)


def get_youtube_filesize(url: str):
    try:
        ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            size = None
            for f in info.get("formats") or []:
                if (
                    f.get("format_id") in ["18", "22"]
                    and f.get("ext") == "mp4"
                    and f.get("acodec") != "none"
                    and f.get("vcodec") != "none"
                ):
                    size = f.get("filesize") or f.get("filesize_approx")
                    if size:
                        break
        return size or info.get("filesize") or info.get("filesize_approx")
    except Exception:
        return None


def download_video(channel, url, download_path):
    global ERROR_MSG
    channel_configs = ALL_CONFIGS[channel]["config"]
    video_format = channel_configs.get("video_format", "18")
    try:
        print("📥 Đang tải video...")
        ydl_opts = {
            "outtmpl": str(download_path),
            "format": (video_format if shutil.which("ffmpeg") is not None else "18"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "verbose": False,
            # Force overwrite to avoid partial file issues
            "overwrites": True,
            # Maximize concurrent downloads
            "concurrent_fragment_downloads": 32,
            "retries": 10,
            "fragment_retries": 3,
            "continuedl": True,
            "check_formats": False,
            "nocheckcertificate": True,
            "no_check_certificate": True,
            # Network optimizations
            "source_address": "0.0.0.0",
            "http_chunk_size": 2 * 1024 * 1024,
            "socket_timeout": 30,
            "noprogress": True,
            # Use different downloaders for different protocols
            "external_downloader": (
                ("aria2c" if shutil.which("aria2c") is not None else None)
                if video_format == "18"
                else {
                    "https": "aria2c" if shutil.which("aria2c") is not None else None,
                    "http": "aria2c" if shutil.which("aria2c") is not None else None,
                    "default": None,
                }
            ),
            "external_downloader_args": (
                {
                    "aria2c": [
                        "--min-split-size=1M",
                        "--max-connection-per-server=16",
                        "--split=64",
                        "--max-concurrent-downloads=16",
                        "--file-allocation=none",
                        "--disk-cache=256M",
                        "--optimize-concurrent-downloads=true",
                        "--retry-wait=2",
                        "--max-tries=10",
                        "--summary-interval=0",
                        "--console-log-level=warn",
                        "--download-result=hide",
                        "--disable-ipv6=true",
                        "--piece-length=1M",
                        "--enable-http-pipelining=true",
                        "--http-accept-gzip=true",
                        "--reuse-uri=true",
                        "--always-resume=true",
                        "--auto-save-interval=0",
                    ]
                }
                if shutil.which("aria2c") is not None
                else {}
            ),
            # Enhanced extractor args for speed
            "extractor_args": {
                "youtube": {
                    "skip": ["translated_subs"],
                    "player_client": ["default"],
                    "player_skip": ["webpage", "initial_data"],
                    "webpage_skip": ["player_response", "initial_data"],
                }
            },
            # Additional speed optimizations
            "prefer_free_formats": False,
            "no_check_certificate": True,
            "geo_bypass": True,
            "age_limit": None,
        }

        # Add cookies if available
        if Path(f"{channel}{YT_COOKIE_FILE}").exists():
            ydl_opts["cookiefile"] = f"{channel}{YT_COOKIE_FILE}"
        else:
            if Path(YT_COOKIE_FILE).exists():
                ydl_opts["cookiefile"] = YT_COOKIE_FILE

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        print("✅ Tải xong.")
        return True

    except Exception as e:
        ERROR_MSG = f"Lỗi khi tải video từ Youtube: {e}"
        logging.error(f"Kênh {channel}: {ERROR_MSG}")
        return None


# done
def render_video_ffmpeg(input_path, output_path, method="repeat"):
    global ERROR_MSG
    duration = get_video_duration(input_path)
    print(f"Độ dài video gốc: {duration:.2f} giây")
    try:
        stream = ffmpeg.input(input_path)

        if 60 <= duration <= 300:
            print("✅ Không cần render.")
            return None
        else:
            if duration <= 30:
                loops = int(60 // duration) + 1
                stream = ffmpeg.input(input_path, stream_loop=loops)
                stream = ffmpeg.output(
                    stream,
                    str(output_path),
                    c="copy",
                    t=60,
                    movflags="+faststart",
                    loglevel="quiet",
                )

            elif 30 < duration < 60:
                if method == "repeat":
                    loops = int(60 // duration) + 1
                    stream = ffmpeg.input(input_path, stream_loop=loops)
                    stream = ffmpeg.output(
                        stream,
                        str(output_path),
                        c="copy",
                        t=60,
                        movflags="+faststart",
                        loglevel="quiet",
                    )
                else:
                    # Slow down videos between 31s and 59s to reach 60s
                    slowdown_factor = duration / 61
                    print(f"Làm chậm video đến tốc độ: {slowdown_factor:.2f}.")
                    video = stream.video.filter(
                        "setpts", f"{1/slowdown_factor}*PTS"
                    )  # Slow down video
                    audio = stream.audio.filter(
                        "atempo", slowdown_factor
                    )  # Slow down audio
                    # stream = ffmpeg.output(stream, audio, str(output_path), c:v='libx264', c:a='aac', t=60)
                    stream = ffmpeg.output(
                        video,
                        audio,
                        str(output_path),
                        format="mp4",
                        movflags="+faststart",
                        t=61,
                        loglevel="quiet",
                    )

            else:
                # Clip videos > 5min to 5min
                stream = ffmpeg.output(
                    stream,
                    str(output_path),
                    c="copy",
                    t=300,
                    movflags="+faststart",
                    loglevel="quiet",
                )
            # Run the ffmpeg command
            ffmpeg.run(stream, overwrite_output=True, capture_stderr=True)
            return True

    except ffmpeg.Error as e:
        print(f"Lỗi render video: {e.stderr}")
        return False


def human_click(
    page, element_or_selector, delay_range=(0.1, 0.5), offset_range=(-10, 10)
):
    try:
        # Handle both element objects and selector strings
        if isinstance(element_or_selector, str):
            element = page.locator(element_or_selector)
        else:
            element = element_or_selector

        # Wait for element to be visible
        element.wait_for(state="visible", timeout=5000)

        # Get element bounding box
        box = element.bounding_box()
        if not box:
            return False

        # Calculate center position with random offset
        center_x = box["x"] + box["width"] / 2
        center_y = box["y"] + box["height"] / 2

        # Add random offset within element bounds
        max_offset_x = min(abs(offset_range[1]), box["width"] / 3)
        max_offset_y = min(abs(offset_range[1]), box["height"] / 3)

        random_x = center_x + random.uniform(-max_offset_x, max_offset_x)
        random_y = center_y + random.uniform(-max_offset_y, max_offset_y)

        # Move mouse to position with slight delay
        page.mouse.move(random_x, random_y)

        # Random delay before click
        time.sleep(random.uniform(*delay_range))

        # Perform the click
        page.mouse.click(random_x, random_y)

        return True

    except Exception as e:
        print(f"Human click failed: {e}")
        return False


def human_move_mouse(page, delay_range=(0.1, 1)):
    try:
        # Random movement within viewport
        x = random.randint(100, 1200)
        y = random.randint(100, 800)
        page.mouse.move(x, y)
        time.sleep(random.uniform(*delay_range))
    except Exception:
        pass


def wait_and_click_post(page, timeout=30, is_human=False):
    global ERROR_MSG
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            # 1. Xử lý popup cookie nếu có
            try:
                cookie_btn = page.query_selector("button:has-text('Allow all')")
                if cookie_btn and cookie_btn.is_visible():
                    if is_human:
                        # Convert ElementHandle to Locator
                        cookie_locator = page.locator("button:has-text('Allow all')")
                        human_click(page, cookie_locator, delay_range=(0.2, 0.5))
                    else:
                        cookie_btn.click()
                    print("✅ Đã bấm Allow all cookies")
            except Exception as er:
                pass  # không có banner cookies

            # 2. Xử lý popup kiểm tra nội dung (nếu có)
            try:
                cancel_popup = page.query_selector(
                    "div.Button__content.Button__content--shape-default.Button__content--size-medium.Button__content--type-neutral.Button__content--loading-false:not(:has-text('Add'))"
                )
                if cancel_popup and cancel_popup.is_visible():
                    if is_human:
                        # Convert ElementHandle to Locator
                        cancel_locator = page.locator(
                            "div.Button__content.Button__content--shape-default.Button__content--size-medium.Button__content--type-neutral.Button__content--loading-false:not(:has-text('Add'))"
                        )
                        human_click(page, cancel_locator, delay_range=(0.2, 0.5))
                    else:
                        cancel_popup.click()
                    print("✅ Đã đóng content check popup")
            except PlaywrightError as er:
                err_msg = f"Kiểm tra và click content check button: {er}"
                print(err_msg)
                pass

            # 3. Chờ nút Post khả dụng
            if is_human:
                human_move_mouse(page, delay_range=(0.1, 0.5))
            page.locator(
                "button[data-e2e='post_video_button'][data-disabled='false'][data-loading='false']",
            ).click(timeout=500)
            print("✅ Đã Click nút Post!")
            return True
        except TimeoutError:
            continue  # Keep trying until timeout
        except Exception as e:
            continue
    ERROR_MSG = "Lỗi khi upload TikTok: Chờ post quá lâu"
    logging.error(ERROR_MSG)
    debug_page(page)
    return False


def intercept_route(route):
    url = route.request.url
    lower = url.lower()
    if any(
        ext in lower
        for ext in [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".woff",
            ".woff2",
            ".ttf",
        ]
    ) or any(
        bad in lower
        for bad in [
            "googletagmanager",
            "google-analytics",
            "doubleclick",
            "hotjar",
            "mixpanel",
            "sentry",
        ]
    ):
        try:
            route.abort()
        except Exception:
            pass
    else:
        route.continue_()


# API-based TikTok upload function using tiktok_uploader
def upload_to_tiktok_api(
    channel, video_path, download_path, video_id=None, description=""
):
    """Upload video to TikTok using API-based method"""
    global ERROR_MSG

    try:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"🚀 {current_time} Starting API-based TikTok upload...")

        # Get channel configs
        channel_configs = ALL_CONFIGS[channel]["config"]
        proxy_config = channel_configs.get("proxy")
        proxy = None
        if proxy_config:
            try:
                proxy_parts = proxy_config.split(":")
                if len(proxy_parts) == 4:
                    # Format: host:port:username:password
                    host, port, username, password = proxy_parts
                    proxy = f"http://{username}:{password}@{host}:{port}"
                elif len(proxy_parts) == 2:
                    # Format: host:port (no auth)
                    host, port = proxy_parts
                    proxy = f"http://{host}:{port}"
                print(f"🌐 Using proxy: {host}:{port}")
            except Exception as e:
                print(f"⚠️ Invalid proxy format: {proxy_config}, continuing without proxy")
                proxy = None
        region = channel_configs.get("region", "ap-northeast-3")
        # Load cookies from channel config and save them in the expected format
        cookies_data = ALL_CONFIGS[channel]["cookies"]

        cookies = [
            {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": ".tiktok.com",
                "path": "/",
            }
            for cookie in (
                cookies_data
                if isinstance(cookies_data, (list, tuple))
                else cookies_data.get("cookies", [])
            )
        ]
        # Upload the video using the tiktok_uploader function
        title = description or f"Auto-uploaded video {video_id or 'untitled'}"
        session_id = next(
            (cookie["value"] for cookie in cookies if cookie["name"] == "sessionid"),
            None,
        )
        dc_id = next(
            (
                cookie["value"]
                for cookie in cookies
                if cookie["name"] == "tt-target-idc"
            ),
            None,
        )
        mstoken = next(
            (cookie["value"] for cookie in cookies if cookie["name"] == "msToken"),
            None,
        ) 
        try:
            user_agent = UserAgent().random
        except FakeUserAgentError as e:
            user_agent = channel_configs.get(
                    "user_agent",
                    "'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36'",
                )
            print("[-] Could not get random user agent, using default")
        if not dc_id:
            print(
                "[WARNING]: Please login, tiktok datacenter id must be allocated, or may fail"
            )
            dc_id = "useast2a"

        # Creating Session with optimized settings
        session = requests.Session()
        session.cookies.set("sessionid", session_id, domain=".tiktok.com")
        session.cookies.set("tt-target-idc", dc_id, domain=".tiktok.com")
        session.cookies.set("msToken", mstoken, domain=".tiktok.com")
        session.verify = True

        # Optimize session with connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20, pool_maxsize=20, max_retries=3
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Connection": "keep-alive",
        }
        session.headers.update(headers)

        if proxy:
            session.proxies = {
                "http": proxy,
                "https": proxy
            }

        creation_id = generate_random_string(21, True)
        markup_text, text_extra = convert_tags(title, session)
        current_time = datetime.now().strftime("%H:%M:%S")
        # Create pre-signatures
        mstoken = session.cookies.get("msToken")
        js_path = os.path.join(
                os.getcwd(), "tiktok_uploader", "tiktok-signature", "browser.js"
            )
        sig_url = f"https://www.tiktok.com/api/v1/web/project/post/?app_name=tiktok_web&channel=tiktok_web&device_platform=web&aid=1988&msToken={mstoken}"
        signatures = subprocess_jsvmp(js_path, user_agent, sig_url)
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"📤 {current_time} Sinh xong signature")
        # Wait for render finished event
        if channel_events[channel]:
            wait_for_render = channel_events[channel].wait(timeout=80)
            # if timeout then exit
            if wait_for_render is False:
                return False
        real_video_path = video_path if is_rendered[channel] is True else download_path
        video_file = os.path.join(os.getcwd(), real_video_path)
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"📤 {current_time} Uploading video via API: {video_file}")
        (
            video_id,
            session_key,
            upload_id,
            crcs,
            upload_host,
            store_uri,
            video_auth,
            aws_auth,
        ) = upload_to_tiktok_optimized(video_file, session, region)
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"✅ {current_time} Upload successfully!")
        url = f"https://{upload_host}/{store_uri}?uploadID={upload_id}&phase=finish&uploadmode=part"
        headers = {
            "Authorization": video_auth,
            "Content-Type": "text/plain;charset=UTF-8",
        }
        data = ",".join([f"{i + 1}:{crcs[i]}" for i in range(len(crcs))])

        if proxy:
            r = requests.post(url, headers=headers, data=data, proxies=session.proxies)
            if not assert_success(url, r):
                return False
        else:
            r = requests.post(url, headers=headers, data=data)
            if not assert_success(url, r):
                return False
        
        url = f"https://www.tiktok.com/top/v1?Action=CommitUploadInner&Version=2020-11-19&SpaceName=tiktok"
        data = '{"SessionKey":"' + session_key + '","Functions":[{"name":"GetMeta"}]}'
        r = session.post(url, auth=aws_auth, data=data)
        if not assert_success(url, r):
            return False
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"✅ {current_time} Commit upload successfully!")
        # publish video
        url = "https://www.tiktok.com"
        headers = {"user-agent": user_agent}

        r = session.head(url, headers=headers)
        if not assert_success(url, r):
            return False
        headers = {"content-type": "application/json", "user-agent": user_agent}
        brand = ""
        if brand and brand[-1] == ",":
            brand = brand[:-1]

        data = {
            "post_common_info": {
                "creation_id": creation_id,
                "enter_post_page_from": 1,
                "post_type": 3,
            },
            "feature_common_info_list": [
                {
                    "geofencing_regions": [],
                    "playlist_name": "",
                    "playlist_id": "",
                    "tcm_params": '{"commerce_toggle_info":{}}',
                    "sound_exemption": 0,
                    "anchors": [],
                    "vedit_common_info": {"draft": "", "video_id": video_id},
                    "privacy_setting_info": {
                        "visibility_type": 0,
                        "allow_duet": 1,
                        "allow_stitch": 1,
                        "allow_comment": 1,
                    },
                }
            ],
            "single_post_req_list": [
                {
                    "batch_index": 0,
                    "video_id": video_id,
                    "is_long_video": 0,
                    "single_post_feature_info": {
                        "text": title,
                        "text_extra": text_extra,
                        "markup_text": title,
                        "music_info": {},
                        "poster_delay": 0,
                    },
                }
            ],
        }

        uploaded = False
        count = 1
        while True:
            print(f"Lam lan thu: {count}")
            if not signatures:
                print("chua co signature, lam lai")
                mstoken = session.cookies.get("msToken")
                js_path = os.path.join(
                    os.getcwd(), "tiktok_uploader", "tiktok-signature", "browser.js"
                )
                sig_url = f"https://www.tiktok.com/api/v1/web/project/post/?app_name=tiktok_web&channel=tiktok_web&device_platform=web&aid=1988&msToken={mstoken}"
                signatures = subprocess_jsvmp(js_path, user_agent, sig_url)
            if signatures is None:
                print("[-] Failed to generate signatures")
                return False
            
            try:
                tt_output = json.loads(signatures)["data"]
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[-] Failed to parse signature data: {str(e)}")
                return False
            project_post_dict = {
                "app_name": "tiktok_web",
                "channel": "tiktok_web",
                "device_platform": "web",
                "aid": 1988,
                "msToken": mstoken,
                "X-Bogus": tt_output["x-bogus"],
                "_signature": tt_output["signature"],
                # "X-TT-Params": tt_output["x-tt-params"],  # not needed rn.
            }
            # url = f"https://www.tiktok.com/api/v1/web/project/post/"
            url = f"https://www.tiktok.com/tiktok/web/project/post/v1/"
            r = session.request(
                "POST",
                url,
                params=project_post_dict,
                data=json.dumps(data),
                headers=headers,
            )
            count = count + 1
            if not assertSuccess(url, r):
                print("[-] Published failed, try later again")
                printError(url, r)
                return False
            if r.json()["status_code"] == 0:
                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"✅ {current_time} Published successfully!")
                uploaded = True
                break
            else:
                print("[-] Publish failed to Tiktok, trying again...")
                printError(url, r)
                return False
        if not uploaded:
            print("[-] Could not upload video")
            return False

        # Mark video as uploaded
        if video_id:
            # Path(f"log/{channel}").write_text(video_id)
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"✅ {current_time} API upload successful!")
            return True
        else:
            ERROR_MSG = "API upload failed - upload_video returned False"
            return False

    except Exception as e:
        ERROR_MSG = f"❌ Lỗi khi upload TikTok API: {e}"
        logging.error(f"Kênh {channel}: {ERROR_MSG}")
        print(f"API upload error: {e}")
        return False
    finally:
        # Clean up session
        if 'session' in locals():
            session.close()
        with event_lock:
            if channel in channel_events:
                channel_events[channel].clear()

# Browser-based TikTok upload function (existing)
def upload_to_tiktok_browser(channel, video_path, download_path, video_id=None):
    """Upload video to TikTok using browser automation"""
    global ERROR_MSG
    channel_configs = ALL_CONFIGS[channel]["config"]
    is_human = channel_configs.get("is_human", APP_CONFIGS.get("is_human", False))
    print(f"human human : {is_human}")
    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"🚀 {current_time} Đang mở browser ...")
    with sync_playwright() as p:
        try:
            with event_lock:
                if channel not in channel_events:
                    channel_events[channel] = Event()
            proxy_config = channel_configs.get("proxy")
            proxy_data = proxy_config.split(":") if proxy_config else None
            proxy = (
                {
                    "server": f"{proxy_data[0]}:{proxy_data[1]}",
                    "username": proxy_data[2],
                    "password": proxy_data[3],
                }
                if proxy_data is not None
                else None
            )
            view_ports = channel_configs.get("view_port", "1280x720").split("x")
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",
                proxy=proxy,
                args=[
                    "--headless=new",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                    "--disable-infobars",
                    "--enable-automation",
                    "--no-first-run",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--no-zygote",
                    # "--single-process",
                    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                ],
            )
            context = browser.new_context(
                user_agent=channel_configs.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
                ),
                viewport={"width": int(view_ports[0]), "height": int(view_ports[1])},
            )
            # Load cookies from configs
            cookies_data = ALL_CONFIGS[channel]["cookies"]
            cookies = [
                {
                    "name": cookie.get("name"),
                    "value": cookie.get("value"),
                    "domain": ".tiktok.com",
                    "path": "/",
                }
                for cookie in (
                    cookies_data
                    if isinstance(cookies_data, (list, tuple))
                    else cookies_data.get("cookies", [])
                )
            ]
            context.add_cookies(cookies)

            page = context.new_page()
            page.add_init_script(
                """
            (() => {
            if (window.chrome) {
            delete Object.getPrototypeOf(navigator).webdriver;
            delete window.chrome.runtime;
            delete window.chrome.devtools;
            const outerWidth = window.outerWidth;
            const outerHeight = window.outerHeight;
            Object.defineProperty(window, 'outerWidth', { get: () => outerWidth });
            Object.defineProperty(window, 'outerHeight', { get: () => outerHeight });
            }
            })();
            """
            )
            page.route("**/*", intercept_route)
            page.goto(
                "https://www.tiktok.com/tiktokstudio/upload?from=creator_center",
                wait_until="domcontentloaded",
            )
            # Simulate natural mouse movement after page load
            if is_human:
                human_move_mouse(page, delay_range=(0.1, 0.5))

            ## Upload video
            file_input = page.wait_for_selector(
                "input[type='file']", state="attached", timeout=30000
            )
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"🚀 {current_time} Browser sẵn sàng")
            wait_for_render = channel_events[channel].wait(timeout=80)
            # if timeout then exit
            if wait_for_render is False:
                return False
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f" {current_time} Browser chọn file")

            absolute_file_path = os.path.join(
                os.getcwd(),
                video_path if is_rendered[channel] is True else download_path,
            )
            file_input.set_input_files(str(absolute_file_path))
            print("📤 Đã tải video lên.")
            print("⏳ Đợi TikTok xử lý video...")
            if is_human:
                human_move_mouse(page, delay_range=(0.5, 1.5))
                print("simulate human click ")
                list_selectors = [
                    "div.notranslate.public-DraftEditor-content[contenteditable='true']>div>div>div>span",
                    "div[data-e2e='advanced_settings_container']",
                    "div.notranslate.public-DraftEditor-content[contenteditable='true']",
                    "div.poi-search>div.Select__root>button.Select__trigger",
                ]
                selected_elements = random.sample(list_selectors, 3)
                for i, el in enumerate(selected_elements):
                    if i > 0:
                        time.sleep(random.uniform(0.1, 1))
                    try:
                        human_click(page, el, delay_range=(0.1, 0.6))
                    except Exception as e:
                        continue
            post_clicked = wait_and_click_post(page, 35, is_human)
            if post_clicked is False:
                return False

            # mark video uploaded
            Path(f"log/{channel}").write_text(video_id)
            ## Chờ nếu có confirm post popup thì click
            try:
                confirm_button_selector = "button.TUXButton.TUXButton--default.TUXButton--medium.TUXButton--primary"
                confirm_button = page.wait_for_selector(
                    confirm_button_selector, timeout=800
                )
                if confirm_button:
                    if is_human:
                        human_click(
                            page, confirm_button_selector, delay_range=(0.3, 0.7)
                        )
                    else:
                        confirm_button.click()
            except PlaywrightError:
                pass  # Keep trying until timeout
            return True
        except Exception as e:
            ERROR_MSG = f"❌ Lỗi khi upload TikTok: {e}"
            if page:
                debug_page(page)
            logging.error(f"Kênh {channel}: {ERROR_MSG}")
            raise
        finally:
            with event_lock:
                if channel in channel_events:
                    channel_events[channel].clear()
            # Ensure browser resources are cleaned up
            if page:
                try:
                    page.close()
                except Exception as e:
                    logging.error(f"Error closing page: {e}")
            if context:
                try:
                    context.close()
                except Exception as e:
                    logging.error(f"Error closing context: {e}")
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    logging.error(f"Error closing browser: {e}")


# Main upload function that chooses between API and browser methods
def upload_to_tiktok(
    channel, video_path, download_path, video_id=None, video_title=None
):
    """Main upload function - chooses method based on config"""
    channel_configs = ALL_CONFIGS[channel]["config"]
    upload_method = channel_configs.get(
        "upload_method", "browser"
    )  # Default to browser

    if upload_method == "api":
        print("🚀 Using API-based upload method")
        return upload_to_tiktok_api(
            channel, video_path, download_path, video_id, video_title
        )
    else:
        print("🚀 Using browser-based upload method")
        return upload_to_tiktok_browser(channel, video_path, download_path, video_id)


def process_video_pipeline(
    channel,
    video,
    pipeline_steps: Optional[Dict[str, bool]] = None,
    stop_event: Optional[Event] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
):
    channel_data = ALL_CONFIGS.get(channel)
    if not channel_data:
        raise ValueError(f"Channel {channel} not configured")

    channel_configs = channel_data["config"]
    steps = _sanitize_pipeline_steps(pipeline_steps or channel_configs.get("pipeline_steps"))

    def emit(message: str):
        if progress_callback:
            try:
                progress_callback(message)
            except Exception:
                pass
        print(message)

    def cancelled() -> bool:
        return bool(stop_event and stop_event.is_set())

    if not any(steps[step] for step in ("download", "render", "upload")):
        emit("Pipeline steps disabled for download/render/upload; skipping processing")
        return True

    video_title = video.title
    video_url = f"https://www.youtube.com/watch?v={video.id}"
    file_name = re.sub(r"[^A-Za-z0-9\s]+", "", video_title).strip()[:80]

    start_time = time.perf_counter()
    download_path = Path(f"downloads/{file_name}.mp4")
    processed_path = Path(f"processed/{file_name}.mp4")

    last_videoid_file = Path(f"log/{channel}")
    last_videoid_file.write_text(video.id)

    download_time = 0.0
    render_time = 0.0
    upload_time = 0.0

    try:
        if steps["download"]:
            emit("📥 Đang tải video từ YouTube...")
            download_start = time.perf_counter()
            download_result = download_video(channel, video_url, download_path)
            if not download_result:
                err_msg = f"✅ Lỗi download\n{video_title}\n{video_url}: {ERROR_MSG}"
                print(err_msg)
                send_telegram_message(channel, err_msg)
                if last_videoid_file.exists():
                    last_videoid_file.unlink()
                return False
            download_time = time.perf_counter() - download_start
            emit(f"✅ Download hoàn tất sau {download_time:.2f}s")
        else:
            emit("⏭️ Bỏ qua bước download")

        if cancelled():
            emit("⚠ Pipeline bị hủy sau bước download")
            return False

        render_needed = steps["render"]
        render_result = None
        if render_needed:
            emit("🎬 Đang render video...")
            render_start = time.perf_counter()
            render_method = channel_configs.get("render_video_method", "repeat")
            render_result = render_video_ffmpeg(download_path, processed_path, render_method)
            if render_result is False:
                err_msg = f"✅ Lỗi trong khi render video\n{video_title}\n{video_url}: {ERROR_MSG}"
                print(err_msg)
                send_telegram_message(channel, err_msg)
                return False
            render_time = time.perf_counter() - render_start
            emit(f"✅ Render hoàn tất sau {render_time:.2f}s")
        else:
            emit("⏭️ Bỏ qua bước render")

        # Determine which file to upload (rendered or original download)
        if render_needed and render_result:
            is_rendered[channel] = True
        else:
            is_rendered[channel] = False

        if cancelled():
            emit("⚠ Pipeline bị hủy trước bước upload")
            return False

        if steps["upload"]:
            emit("🚀 Đang upload video lên TikTok...")
            with event_lock:
                channel_events.setdefault(channel, Event())
                channel_events[channel].set()

            upload_start = time.perf_counter()
            upload_result = upload_to_tiktok(
                channel,
                processed_path,
                download_path,
                video.id,
                video_title,
            )
            if not upload_result:
                err_msg = f"❌ Lỗi upload TikTok\n{video_title}\n{video_url}: {ERROR_MSG}"
                print(err_msg)
                send_telegram_message(channel, err_msg)
                return False
            upload_time = time.perf_counter() - upload_start
            emit(f"✅ Upload hoàn tất sau {upload_time:.2f}s")
        else:
            emit("⏭️ Bỏ qua bước upload")

        total_duration = time.perf_counter() - start_time
        summary_parts = []
        if steps["download"]:
            summary_parts.append(f"Download: {download_time:.2f}s")
        if steps["render"]:
            summary_parts.append(f"Render: {render_time:.2f}s")
        if steps["upload"]:
            summary_parts.append(f"Upload: {upload_time:.2f}s")
        process_time_str = " | ".join(summary_parts) if summary_parts else "No processing steps executed"

        current_time_str = datetime.now().strftime("%H:%M:%S")
        emit(f"✅ {current_time_str}: Hoàn tất pipeline\n{process_time_str}")

        if steps["upload"]:
            username = channel_configs.get("username", "default_username")
            upload_method = channel_configs.get("upload_method", "browser")
            tele_msg = (
                f"✅ Đã đăng TikTok thành công ({upload_method}):\n"
                f"{video_title}\n{video_url}\n{process_time_str}\n"
                f"Tài khoản TikTok: {username}\nĐăng lúc: {datetime.now().strftime('%H:%M:%S')}\n"
            )
            send_telegram_message(channel, tele_msg)
        elif steps["render"] or steps["download"]:
            tele_msg = (
                f"ℹ️ Hoàn tất pipeline thủ công:\n{video_title}\n{video_url}\n"
                f"{process_time_str}"
            )
            send_telegram_message(channel, tele_msg)

        return True

    finally:
        try:
            # if download_path.exists():
            #     download_path.unlink()
            if processed_path.exists():
                processed_path.unlink()
        except Exception as cleanup_error:
            print(f"Lỗi khi xóa file tạm: {cleanup_error}")


def fetch_youtube_activities(
    api_keys, channel_id, api="playlistItems", max_retries=3, method="sequence"
):
    global FAIL_KEY_LIST
    base_url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        if api == "playlistItems"
        else "https://www.googleapis.com/youtube/v3/activities"
    )

    def make_request(api_key, retry_count=0):
        params = (
            {
                "part": "contentDetails,snippet",
                "fields": "items(snippet(title,publishedAt),contentDetails(videoId))",
                "playlistId": "UU" + channel_id[2:],
                "maxResults": 1,
                "key": api_key,
            }
            if api == "playlistItems"
            else {
                "part": "snippet,contentDetails",
                "fields": "items(snippet(type,title,publishedAt),contentDetails(upload(videoId)))",
                "channelId": channel_id,
                "maxResults": 1,
                "key": api_key,
            }
        )

        try:
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if retry_count < max_retries - 1:
                # Exponential backoff with jitter
                time.sleep(2**retry_count + random.uniform(0, 0.1))
                return make_request(api_key, retry_count + 1)
            return {"error": str(e), "api_key": api_key}

    if "parallel" == method:
        # Use ThreadPoolExecutor for concurrent requests
        with ThreadPoolExecutor(max_workers=len(api_keys)) as executor:
            # Create future tasks for each API key
            future_to_key = {
                executor.submit(make_request, key.strip()): key for key in api_keys
            }

            # Process completed futures and return first success
            for future in as_completed(future_to_key):
                result = future.result()
                if "error" not in result:
                    # Immediately cancel all other tasks and return
                    executor._threads.clear()  # Clear threads to stop further execution
                    for f in future_to_key:
                        f.cancel()
                    return result

            # If all requests fail, collect errors
            errors = [f.result().get("error", "Unknown error") for f in future_to_key]
        raise Exception(f"Kênh {channel_id}: Tất cả Youtube API Keys đều lỗi: {errors}")
    else:
        for api_key in api_keys:
            if api_key.strip() not in FAIL_KEY_LIST:
                result = make_request(api_key.strip())
                if "error" not in result:
                    return result
                else:
                    FAIL_KEY_LIST.add(api_key.strip())
                    Thread(
                        target=send_telegram_message,
                        args=(
                            channel_id,
                            f"API key bị lỗi cần thay thế: {api_key}",
                        ),
                        daemon=True,
                    ).start()

        raise Exception(
            f"Kênh {channel_id}: Tất cả Youtube API Keys đều lỗi: {FAIL_KEY_LIST}"
        )


def check_new_video(channel: str):
    # print(f"🔍 Kiểm tra video mới youtube channel {channel}..")
    if channel in apikey_error_channels:
        return None
    channel_configs = ALL_CONFIGS[channel]["config"]
    api_type = channel_configs.get("youtube_api_type", "playlistItems")
    api_keys = channel_configs.get(
        "youtube_api_key", "AIzaSyB_LiqDEWOzgdIRQTPe9j_5jKzMKME2sH0"
    )
    is_new_seconds = channel_configs.get("is_new_second", 150)
    fetch_method = channel_configs.get("api_scan_method", "sequence")
    try:
        data = fetch_youtube_activities(
            api_keys.split(";"), channel, api_type, 3, fetch_method
        )
        if not data.get("items"):
            print("⚠️ Không tìm thấy hoạt động nào.")
            return None

        latest = data["items"][0]
        if api_type != "playlistItems" and latest["snippet"]["type"] != "upload":
            # print("⏳ Không có video upload mới.")
            return None

        video_id = (
            latest["contentDetails"]["videoId"]
            if api_type == "playlistItems"
            else latest["contentDetails"]["upload"]["videoId"]
        )
        video_title = latest["snippet"]["title"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        published_at = latest["snippet"]["publishedAt"]
        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        time_diff = (now_utc - published_dt).total_seconds()

        if time_diff > is_new_seconds:
            # print(f"🕒 Video đã đăng {int(time_diff)}s trước, bỏ qua.")
            return None

        # Use pathlib for faster file I/O
        last_videoid_file = Path(f"log/{channel}")
        if (
            last_videoid_file.exists()
            and last_videoid_file.read_text().strip() == video_id
        ):
            # print("⏳ Video mới đã đăng trước đó.")
            return None
        # Lấy thời gian hiện tại khi đăng
        current_time = datetime.now().strftime("%H:%M:%S")  # Format: "HH:MM:SS"
        published_time_str = published_dt.strftime("%H:%M:%S")

        tele_msg = f"📢 Lúc: {current_time} Phát hiện video mới từ api:\n{video_title}\n{video_url}\nPhát hành: {published_time_str}"
        print(tele_msg)
        Thread(
            target=send_telegram_message,
            args=(
                channel,
                tele_msg,
            ),
            daemon=True,
        ).start()
        video = Video(
            id=video_id,
            title=video_title,
            url=video_url,
            channel_id=channel,
            published=published_at,
        )
        return video
    except Exception as e:
        apikey_error_channels.add(channel)
        err_msg = f"❌ Lỗi khi kiểm tra video mới: {e}"
        logging.error(f"Kênh {channel}:{err_msg}")
        send_telegram_message(channel, err_msg)


def run_sync_scheduler():
    """Run the scheduler in a separate thread for API polling."""
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logging.error(f"Error in scheduler: {e}")
            time.sleep(5)


# Modified main execution
async def main():
    """Main async function to run the application."""
    global ALL_CONFIGS

    try:
        # Load configurations
        ALL_CONFIGS = load_all_configs()
        if not ALL_CONFIGS:
            er_msg = (
                f"❌ Không có cấu hình kênh YT nào, vui lòng cập nhật folder configs"
            )
            logging.error(er_msg)
            send_telegram_message("Tất cả channel", er_msg, True)
            raise Exception(er_msg)
    except Exception as e:
        logging.error(f"❌ Lỗi đọc config: {str(e)}")
        return

    # Initialize PubSubHubbub server
    server_initialized = await initialize_pubsub_server()
    if not server_initialized:
        logging.error("Failed to start PubSubHubbub server")
        return

    # Subscribe to channels
    await subscribe_to_channels()

    # Setup API polling for channels that use "api" or "both"
    for channel in (
        item
        for item in list(ALL_CONFIGS)
        if ALL_CONFIGS[item]["config"]["detect_video"] == "api"
        or ALL_CONFIGS[item]["config"]["detect_video"] == "both"
    ):
        channel_configs = ALL_CONFIGS[channel]["config"]
        interval = channel_configs.get("scan_interval", 2)

        def check_channel_video(ch=channel):  # Use default argument to capture channel
            video = check_new_video(ch)
            if video:
                Thread(
                    target=process_video_pipeline, args=(ch, video), daemon=True
                ).start()

        schedule.every(interval).seconds.do(check_channel_video)
        print(f"Scheduled channel {channel} to check every {interval} seconds")

    print(f"🟢 Application started at {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")

    # Start scheduler in background thread for API polling
    if any(
        ALL_CONFIGS[item]["config"]["detect_video"] in ["api", "both"]
        for item in ALL_CONFIGS
    ):
        scheduler_thread = Thread(target=run_sync_scheduler, daemon=True)
        scheduler_thread.start()
        print("🔄 API polling scheduler started")

    # Run the main loop
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Dừng tool.")
    finally:
        # Cleanup
        if pubsub_server:
            print("Cleaning up PubSubHubbub server...")


# Entry point
if __name__ == "__main__":
    # Load app settings first
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            APP_CONFIGS = json.load(f)
    except Exception as e:
        logging.error(f"Error loading settings.json: {e}")
        sys.exit(1)

    # Run the main async function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Application stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)
