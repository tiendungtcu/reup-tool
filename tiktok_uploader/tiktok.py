import time, requests, json
import requests, json, time, subprocess, os, sys
import uuid
from zlib import crc32
import concurrent.futures
import threading
from fake_useragent import FakeUserAgentError, UserAgent
from requests_auth_aws_sigv4 import AWSSigV4
from tiktok_uploader.basics import eprint
from tiktok_uploader.bot_utils import *

# Constants
_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36'

def upload_to_tiktok_optimized(video_file, session, region="ap-northeast-3"):
    """Original sequential upload function as fallback"""
    url = "https://www.tiktok.com/api/v1/video/upload/auth/?aid=1988"
    r = session.get(url)
    if not assert_success(url, r):
        return False

    aws_auth = AWSSigV4(
        "vod",
        region=region,
        aws_access_key_id=r.json()["video_token_v5"]["access_key_id"],
        aws_secret_access_key=r.json()["video_token_v5"]["secret_acess_key"],
        aws_session_token=r.json()["video_token_v5"]["session_token"],
    )
    with open(video_file, "rb") as f:
        video_content = f.read()
    file_size = len(video_content)
    url = f"https://www.tiktok.com/top/v1?Action=ApplyUploadInner&Version=2020-11-19&SpaceName=tiktok&FileType=video&IsInner=1&FileSize={file_size}&s=g158iqx8434"

    r = session.get(url, auth=aws_auth)
    if not assert_success(url, r):
        return False

    # upload chunks
    upload_node = r.json()["Result"]["InnerUploadAddress"]["UploadNodes"][0]
    video_id = upload_node["Vid"]
    store_uri = upload_node["StoreInfos"][0]["StoreUri"]
    video_auth = upload_node["StoreInfos"][0]["Auth"]
    upload_host = upload_node["UploadHost"]
    session_key = upload_node["SessionKey"]
    # Optimize chunk size based on file size
    if file_size < 50 * 1024 * 1024:  # < 50MB
        chunk_size = 2 * 1024 * 1024  # 2MB chunks
        max_workers = 8
    elif file_size < 200 * 1024 * 1024:  # < 200MB
        chunk_size = 5 * 1024 * 1024  # 5MB chunks
        max_workers = 6
    else:  # > 200MB
        chunk_size = 10 * 1024 * 1024  # 10MB chunks
        max_workers = 4
    chunks = []
    i = 0
    while i < file_size:
        chunks.append(video_content[i: i + chunk_size])
        i += chunk_size
    crcs = []
    upload_id = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        upload_start = time.time()
        futures = []
        
        for i, chunk in enumerate(chunks):
            crc = crc32(chunk)
            crcs.append(crc)
            
            url_chunk = f"https://{upload_host}/{store_uri}?partNumber={i + 1}&uploadID={upload_id}&phase=transfer"
            headers = {
                "Authorization": video_auth,
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="undefined"',
                "Content-Crc32": str(crc),  # Fixed: convert to string like original
            }
            
            # Create a new session for each worker to avoid conflicts
            worker_session = requests.Session()
            worker_session.headers.update(session.headers)
            worker_session.cookies.update(session.cookies)
            if hasattr(session, 'proxies'):
                worker_session.proxies.update(session.proxies)
            
            # Set the same verify setting
            worker_session.verify = session.verify
            
            future = executor.submit(upload_chunk_fixed, worker_session, url_chunk, headers, chunk, i, len(chunks))
            futures.append(future)
        
        # Wait for all uploads to complete
        success_count = 0
        failed_chunks = []
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                if future.result():
                    success_count += 1
                else:
                    failed_chunks.append(i)
            except Exception as e:
                print(f"[-] Chunk upload exception: {e}")
                failed_chunks.append(i)
        
        upload_time = time.time() - upload_start
        total_mb = file_size / (1024 * 1024)
        speed = total_mb / upload_time if upload_time > 0 else 0
        
        if failed_chunks:
            print(f"[-] Failed chunks: {failed_chunks}")
            return False
        
        print(f"[+] All {success_count} chunks uploaded successfully in {upload_time:.2f}s ({speed:.2f} MB/s)")

    return video_id, session_key, upload_id, crcs, upload_host, store_uri, video_auth, aws_auth

def upload_chunk_fixed(session, url, headers, chunk, chunk_index, total_chunks):
    """Upload a single chunk with retry logic - fixed version"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            # Use the same timeout and approach as original
            r = session.post(url, headers=headers, data=chunk, timeout=60)
            upload_time = time.time() - start_time
            
            if assert_success(url, r):
                print(f"[+] Chunk {chunk_index + 1}/{total_chunks} uploaded in {upload_time:.2f}s")
                return True
            else:
                print(f"[-] Chunk {chunk_index + 1} failed (attempt {attempt + 1}) - Status: {r.status_code}")
                
        except requests.exceptions.Timeout:
            print(f"[-] Chunk {chunk_index + 1} timeout (attempt {attempt + 1})")
        except requests.exceptions.ConnectionError as e:
            print(f"[-] Chunk {chunk_index + 1} connection error (attempt {attempt + 1}): {e}")
        except Exception as e:
            print(f"[-] Chunk {chunk_index + 1} error (attempt {attempt + 1}): {e}")
            
        if attempt < max_retries - 1:
            wait_time = min(2 ** attempt, 10)  # Cap at 10 seconds
            print(f"[!] Retrying chunk {chunk_index + 1} in {wait_time} seconds...")
            time.sleep(wait_time)
            
    return False

def subprocess_jsvmp_safe(js_path, user_agent, sig_url):
    """Safe wrapper for subprocess_jsvmp"""
    try:
        return subprocess_jsvmp(js_path, user_agent, sig_url)
    except Exception as e:
        print(f"Signature generation failed: {e}")
        return None


def upload_video_with_retry(video_file, session, region, proxy, max_retries=3):
    """Upload video with retry logic and proxy handling"""
    for attempt in range(max_retries):
        try:
            print(f"🔄 Upload attempt {attempt + 1}/{max_retries}")
            result = upload_to_tiktok_optimized(video_file, session, region)
            if result:
                return result
        except Exception as e:
            print(f"❌ Upload attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print("❌ All upload attempts failed")
                return False
    return False

def finalize_upload_with_retry(session, upload_host, store_uri, upload_id, crcs, video_auth, proxy, max_retries=3):
    """Finalize upload with retry logic"""
    url = f"https://{upload_host}/{store_uri}?uploadID={upload_id}&phase=finish&uploadmode=part"
    headers = {
        "Authorization": video_auth,
        "Content-Type": "text/plain;charset=UTF-8",
    }
    data = ",".join([f"{i + 1}:{crcs[i]}" for i in range(len(crcs))])

    for attempt in range(max_retries):
        try:
            r = session.post(url, headers=headers, data=data, timeout=30)
            if assert_success(url, r):
                print("✅ Upload finalized successfully")
                return True
            else:
                print(f"❌ Finalize attempt {attempt + 1} failed")
        except Exception as e:
            print(f"❌ Finalize attempt {attempt + 1} error: {e}")
            
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
    return False

def commit_upload_with_retry(session, session_key, aws_auth, max_retries=3):
    """Commit upload with retry logic"""
    url = f"https://www.tiktok.com/top/v1?Action=CommitUploadInner&Version=2020-11-19&SpaceName=tiktok"
    data = '{"SessionKey":"' + session_key + '","Functions":[{"name":"GetMeta"}]}'

    for attempt in range(max_retries):
        try:
            r = session.post(url, auth=aws_auth, data=data, timeout=30)
            if assert_success(url, r):
                print("✅ Upload committed successfully")
                return True
            else:
                print(f"❌ Commit attempt {attempt + 1} failed")
        except Exception as e:
            print(f"❌ Commit attempt {attempt + 1} error: {e}")
            
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
    return False

def publish_video_with_retry(session, creation_id, video_id, title, markup_text, 
                           text_extra, user_agent, pre_signatures, proxy, max_retries=3):
    """Publish video with retry logic"""
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
    print(f"will commit data: {data}")
    for attempt in range(max_retries):
        try:
            # Generate or use pre-generated signatures
            signatures = pre_signatures
            if not signatures:
                print("🔐 Generating fresh signatures...")
                mstoken = session.cookies.get("msToken")
                if not mstoken:
                    print("❌ Missing msToken")
                    continue
                    
                js_path = os.path.join(os.getcwd(), "tiktok_uploader", "tiktok-signature", "browser.js")
                sig_url = f"https://www.tiktok.com/api/v1/web/project/post/?app_name=tiktok_web&channel=tiktok_web&device_platform=web&aid=1988&msToken={mstoken}"
                signatures = subprocess_jsvmp(js_path, user_agent, sig_url)

            if not signatures:
                print("❌ Failed to generate signatures")
                continue

            try:
                tt_output = json.loads(signatures)["data"]
            except (json.JSONDecodeError, KeyError) as e:
                print(f"❌ Failed to parse signature data: {e}")
                continue

            # Prepare request
            mstoken = session.cookies.get("msToken")
            project_post_dict = {
                "app_name": "tiktok_web",
                "channel": "tiktok_web",
                "device_platform": "web",
                "aid": 1988,
                "msToken": mstoken,
                "X-Bogus": tt_output["x-bogus"],
                "_signature": tt_output["signature"],
            }

            headers = {"content-type": "application/json", "user-agent": user_agent}
            url = "https://www.tiktok.com/tiktok/web/project/post/v1/"
            
            r = session.request(
                "POST",
                url,
                params=project_post_dict,
                data=json.dumps(data),
                headers=headers,
                timeout=30
            )

            if assertSuccess(url, r):
                if r.json().get("status_code") == 0:
                    print("✅ Published successfully!")
                    return True
                else:
                    print(f"❌ Publish failed: {r.json()}")
            else:
                print(f"❌ Publish attempt {attempt + 1} failed")
                printError(url, r)

        except Exception as e:
            print(f"❌ Publish attempt {attempt + 1} error: {e}")
            
        if attempt < max_retries - 1:
            print(f"⏳ Retrying publish in {2 ** attempt} seconds...")
            time.sleep(2 ** attempt)
            pre_signatures = None  # Force regeneration on retry
    
    return False