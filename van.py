# ================================================================
# duolingo_bot_ultimate_hybrid_fixed.py
# FULL CODE - FIX STREAK (curl_cffi) + GEMS (selenium) + PROXY + REALTIME PROGRESS + STOP + CONNECTION POOL
# ================================================================

from dotenv import load_dotenv
load_dotenv()
import asyncio
import base64
import json
import logging
import os
import time
import random
import re
import sys
import subprocess
import gc
import threading
import atexit
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytz

import discord
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests
from cryptography.fernet import Fernet
import aiohttp
from aiohttp_socks import ProxyConnector

# ---------- Selenium imports ----------
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ==================== LOGGING ====================
# Tắt warning của urllib3 connection pool
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("HybridBot")

# ==================== PROXY MANAGER ====================
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.working_proxies = []
        self.failed_proxies = set()
        self.last_update = 0
        self.update_interval = 30
        self.rotate_interval = 10
        self.last_rotate = 0
        self._lock = asyncio.Lock()
        self._crawling = False
        self.current_index = 0
        self.proxy_speeds = {}
        
    def _get_proxies(self) -> List[str]:
        proxies = []
        local = [
            "socks5://127.0.0.1:1080", "socks5://localhost:1080",
            "socks5://127.0.0.1:9050", "socks5://localhost:9050",
            "socks5://127.0.0.1:9150", "socks5://localhost:9150",
            "http://127.0.0.1:8080", "http://localhost:8080",
            "http://127.0.0.1:3128", "http://localhost:3128",
            "http://127.0.0.1:8888", "http://localhost:8888",
            "http://127.0.0.1:8118", "http://localhost:8118",
        ]
        proxies.extend(local)
        
        try:
            if os.path.exists("proxy.txt"):
                with open("proxy.txt", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if line.startswith("http://") or line.startswith("socks5://"):
                                proxies.append(line)
                            elif ":" in line:
                                ip, port = line.split(":")
                                proxies.append(f"http://{ip}:{port}")
                                proxies.append(f"socks5://{ip}:{port}")
                            else:
                                proxies.append(line)
        except:
            pass
        
        proxy_env = os.getenv("PROXY_LIST", "")
        if proxy_env:
            for p in proxy_env.split(","):
                p = p.strip()
                if p:
                    if not p.startswith("http://") and not p.startswith("socks5://"):
                        if ":" in p:
                            ip, port = p.split(":")
                            proxies.append(f"http://{ip}:{port}")
                            proxies.append(f"socks5://{ip}:{port}")
                    else:
                        proxies.append(p)
        
        for i in range(1, 100):
            proxies.append(f"http://103.28.122.{i}:80")
            proxies.append(f"http://45.32.88.{i}:80")
            proxies.append(f"socks5://45.32.88.{i}:1080")
            proxies.append(f"http://45.33.88.{i}:80")
            proxies.append(f"socks5://45.33.88.{i}:1080")
        
        valid_proxies = []
        seen = set()
        for p in proxies:
            if p not in seen and p and "0.0.0.0" not in p:
                seen.add(p)
                valid_proxies.append(p)
        
        return valid_proxies
    
    async def test_proxy(self, proxy: str) -> Tuple[str, bool, float]:
        start_time = time.time()
        try:
            connector = aiohttp.TCPConnector(limit=1, limit_per_host=1, ssl=False)
            timeout = aiohttp.ClientTimeout(total=2.0, connect=0.5, sock_read=0.5)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                try:
                    async with session.get('https://httpbin.org/ip', timeout=timeout) as resp:
                        if resp.status == 200:
                            elapsed = time.time() - start_time
                            return (proxy, True, elapsed)
                except:
                    pass
                try:
                    async with session.get('http://httpbin.org/ip', timeout=timeout) as resp:
                        if resp.status == 200:
                            elapsed = time.time() - start_time
                            return (proxy, True, elapsed)
                except:
                    pass
            return (proxy, False, 999)
        except:
            return (proxy, False, 999)
    
    async def update_proxies(self, force: bool = False):
        async with self._lock:
            now = time.time()
            if not force and now - self.last_update < self.update_interval:
                return
            if self._crawling:
                return
            self._crawling = True
            try:
                logger.info("🔄 Đang cào và test proxy...")
                all_proxies = self._get_proxies()
                logger.info(f"📦 Cào được {len(all_proxies)} proxy")
                working = []
                proxy_speeds = {}
                test_limit = min(300, len(all_proxies))
                tasks = []
                for proxy in all_proxies[:test_limit]:
                    if proxy not in self.failed_proxies:
                        tasks.append(self.test_proxy(proxy))
                if tasks:
                    batch_size = 50
                    for i in range(0, len(tasks), batch_size):
                        batch = tasks[i:i+batch_size]
                        results = await asyncio.gather(*batch)
                        for proxy, ok, speed in results:
                            if ok and speed < 1.5:
                                working.append(proxy)
                                proxy_speeds[proxy] = speed
                        await asyncio.sleep(0.1)
                if not working:
                    working = [p for p in all_proxies if '127.0.0.1' in p or 'localhost' in p]
                    if not working:
                        working = ["socks5://127.0.0.1:1080", "http://127.0.0.1:8080"]
                if working and proxy_speeds:
                    working.sort(key=lambda p: proxy_speeds.get(p, 999))
                self.working_proxies = working
                self.proxies = working
                self.proxy_speeds = proxy_speeds
                self.last_update = now
                logger.info(f"✅ Tìm thấy {len(self.working_proxies)} proxy hoạt động (dưới 1.5s)")
                if working:
                    fast = working[:3]
                    speeds = [proxy_speeds.get(p, 0) for p in fast]
                    logger.info(f"🌐 Proxy nhanh nhất: {list(zip(fast, speeds))}")
            except Exception as e:
                logger.error(f"❌ Lỗi update proxy: {e}")
            self._crawling = False
    
    async def get_proxy(self) -> Optional[str]:
        await self.update_proxies()
        now = time.time()
        if now - self.last_rotate > self.rotate_interval:
            if self.working_proxies:
                self.current_index = (self.current_index + 1) % len(self.working_proxies)
                self.last_rotate = now
        if not self.working_proxies:
            return None
        return self.working_proxies[self.current_index % len(self.working_proxies)]
    
    def mark_failed(self, proxy: str):
        if proxy and proxy in self.working_proxies:
            self.working_proxies.remove(proxy)
            self.failed_proxies.add(proxy)
            if proxy in self.proxy_speeds:
                del self.proxy_speeds[proxy]
    
    async def add_proxy(self, proxy: str) -> Dict[str, Any]:
        proxy_http = None
        proxy_socks = None
        
        if not proxy.startswith("http://") and not proxy.startswith("socks5://"):
            if ":" in proxy:
                ip, port = proxy.split(":")
                if not ip or not port.isdigit():
                    return {"success": False, "message": "Proxy không hợp lệ (sai định dạng IP:PORT)"}
                proxy_http = f"http://{ip}:{port}"
                proxy_socks = f"socks5://{ip}:{port}"
            else:
                return {"success": False, "message": "Proxy không hợp lệ, cần có IP:PORT hoặc http(s)://IP:PORT"}
        else:
            if proxy.startswith("http://"):
                proxy_http = proxy
                proxy_socks = proxy.replace("http://", "socks5://")
            elif proxy.startswith("socks5://"):
                proxy_socks = proxy
                proxy_http = proxy.replace("socks5://", "http://")
            if ":" not in proxy.split("/")[-1]:
                return {"success": False, "message": "Proxy thiếu cổng (port)"}
        
        results = []
        for p in [proxy_http, proxy_socks]:
            if p and p not in self.failed_proxies:
                ok, speed = await self.test_proxy(p)
                results.append({"proxy": p, "ok": ok, "speed": speed})
        
        added = []
        for r in results:
            if r["ok"] and r["speed"] < 1.5:
                if r["proxy"] not in self.working_proxies:
                    self.working_proxies.append(r["proxy"])
                    self.proxy_speeds[r["proxy"]] = r["speed"]
                    added.append(r["proxy"])
        
        if added:
            self.working_proxies.sort(key=lambda p: self.proxy_speeds.get(p, 999))
            return {
                "success": True,
                "message": f"Đã thêm {len(added)} proxy (tốc độ <1.5s)",
                "added": added,
                "speeds": {p: self.proxy_speeds.get(p, 0) for p in added}
            }
        else:
            return {
                "success": False,
                "message": "Proxy không hoạt động hoặc quá chậm (>1.5s)",
                "results": results
            }

proxy_manager = ProxyManager()

# ==================== CẤU HÌNH ====================
BASE_URL = "https://www.duolingo.com"
API_VERSION = "2017-06-30"
LEADERBOARD_API = "https://duolingo-leaderboards-prod.duolingo.com"
MAX_WORKERS = 3000
DATA_FILE = "duolingo_bot_data.json"
USAGE_FILE = "duolingo_usage.json"

# ================== PHÂN CẤP QUYỀN ==================
CRE_IDS = set()
cre_ids_str = os.getenv("CRE_IDS", "")
if cre_ids_str:
    for uid in cre_ids_str.split(","):
        uid = uid.strip()
        if uid.isdigit():
            CRE_IDS.add(int(uid))

VIP_IDS = set()
vip_ids_str = os.getenv("VIP_IDS", "")
if vip_ids_str:
    for uid in vip_ids_str.split(","):
        uid = uid.strip()
        if uid.isdigit():
            VIP_IDS.add(int(uid))

# ================== GIỚI HẠN ==================
USER_LIMIT_STREAK_PER_HOUR = 200
USER_LIMIT_XP_PER_DAY = 2_000_000
USER_LIMIT_GEMS_PER_5H = 20_000
USER_CONCURRENCY = 8
USER_SLEEP = 0.15
USER_MAX_TASKS = 1

VIP_LIMIT_STREAK_PER_HOUR = 9999
VIP_LIMIT_XP_PER_DAY = 50_000_000
VIP_LIMIT_GEMS_PER_5H = 500_000
VIP_CONCURRENCY = 30
VIP_SLEEP = 0.01
VIP_MAX_TASKS = 5

CRE_LIMIT_STREAK_PER_HOUR = 999999999
CRE_LIMIT_XP_PER_DAY = 999999999
CRE_LIMIT_GEMS_PER_5H = 999999999
CRE_CONCURRENCY = 60
CRE_SLEEP = 0.003
CRE_MAX_TASKS = 99

# ================== MÃ HÓA ==================
KEY_FILE = "encryption_key.key"
def get_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        return key

ENCRYPTION_KEY = get_or_create_key()
cipher = Fernet(ENCRYPTION_KEY)

# ================== LƯU TRỮ ==================
user_sessions: Dict[str, Dict[str, Any]] = {}
user_tasks: Dict[str, List[asyncio.Task]] = {}
shared_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Stop flags cho các task chạy trong thread pool
_stop_flags = {}  # user_id -> Event

def encrypt_token(token: str) -> str:
    return cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted: str) -> str:
    try:
        return cipher.decrypt(encrypted.encode()).decode()
    except Exception:
        raise ValueError("Invalid encrypted token. Please re-login.")

def verify_token_signature(token: str) -> bool:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        payload = json.loads(base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode())
        if "sub" not in payload:
            return False
        if "exp" in payload and payload["exp"] < time.time():
            return False
        return True
    except:
        return False

def get_user_id_from_token(token: str) -> str:
    try:
        parts = token.split(".")
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        return str(payload.get("sub"))
    except:
        raise ValueError("Token không hợp lệ")

def save_data():
    try:
        data_to_save = {}
        for user_id, user_data in user_sessions.items():
            data_to_save[user_id] = {
                "active": user_data.get("active"),
                "accounts": {}
            }
            for uid, acc in user_data.get("accounts", {}).items():
                data_to_save[user_id]["accounts"][uid] = {
                    "token_encrypted": acc.get("token_encrypted"),
                    "uid": acc.get("uid"),
                    "username": acc.get("username"),
                    "info": acc.get("info")
                }
        with open(DATA_FILE, "w") as f:
            json.dump(data_to_save, f, indent=2)
        logger.info("💾 Đã lưu dữ liệu")
    except Exception as e:
        logger.error(f"❌ Lỗi lưu: {e}")

def load_data():
    global user_sessions
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r") as f:
            user_sessions = json.load(f)
        logger.info(f"✅ Đã tải dữ liệu: {len(user_sessions)} user(s)")
    except:
        user_sessions = {}

load_data()
atexit.register(save_data)

# ================== USAGE TRACKER ==================
def load_usage():
    if not os.path.exists(USAGE_FILE):
        return {}
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_usage(usage):
    with open(USAGE_FILE, "w") as f:
        json.dump(usage, f, indent=2)

usage_data = load_usage()
atexit.register(lambda: save_usage(usage_data))

def get_role(user_id: int) -> str:
    if user_id in CRE_IDS:
        return "CRE"
    elif user_id in VIP_IDS:
        return "VIP"
    else:
        return "User"

def is_cre(user_id: int) -> bool:
    return user_id in CRE_IDS

def is_vip(user_id: int) -> bool:
    return user_id in VIP_IDS

def get_user_limits(user_id: int):
    if user_id in CRE_IDS:
        return {
            "streak_limit": CRE_LIMIT_STREAK_PER_HOUR,
            "xp_limit": CRE_LIMIT_XP_PER_DAY,
            "gems_limit": CRE_LIMIT_GEMS_PER_5H,
            "concurrency": CRE_CONCURRENCY,
            "max_tasks": CRE_MAX_TASKS,
            "no_limit": True,
            "sleep": CRE_SLEEP
        }
    elif user_id in VIP_IDS:
        return {
            "streak_limit": VIP_LIMIT_STREAK_PER_HOUR,
            "xp_limit": VIP_LIMIT_XP_PER_DAY,
            "gems_limit": VIP_LIMIT_GEMS_PER_5H,
            "concurrency": VIP_CONCURRENCY,
            "max_tasks": VIP_MAX_TASKS,
            "no_limit": False,
            "sleep": VIP_SLEEP
        }
    else:
        return {
            "streak_limit": USER_LIMIT_STREAK_PER_HOUR,
            "xp_limit": USER_LIMIT_XP_PER_DAY,
            "gems_limit": USER_LIMIT_GEMS_PER_5H,
            "concurrency": USER_CONCURRENCY,
            "max_tasks": USER_MAX_TASKS,
            "no_limit": False,
            "sleep": USER_SLEEP
        }

def check_and_update_limits(discord_user_id: str, streak_delta: int = 0, xp_delta: int = 0, gems_delta: int = 0) -> bool:
    user_id_int = int(discord_user_id)
    limits = get_user_limits(user_id_int)
    if limits["no_limit"]:
        return True

    now = time.time()
    usage = usage_data.get(discord_user_id, {"streak": [], "xp": [], "gems": []})

    if streak_delta > 0:
        usage["streak"] = [t for t in usage["streak"] if now - t < 3600]
        if len(usage["streak"]) + streak_delta > limits["streak_limit"]:
            return False
        for _ in range(streak_delta):
            usage["streak"].append(now)

    if xp_delta > 0:
        usage["xp"] = [(amt, t) for amt, t in usage["xp"] if now - t < 86400]
        total_xp = sum(amt for amt, _ in usage["xp"])
        if total_xp + xp_delta > limits["xp_limit"]:
            return False
        usage["xp"].append((xp_delta, now))

    if gems_delta > 0:
        usage["gems"] = [(amt, t) for amt, t in usage["gems"] if now - t < 18000]
        total_gems = sum(amt for amt, _ in usage["gems"])
        if total_gems + gems_delta > limits["gems_limit"]:
            return False
        usage["gems"].append((gems_delta, now))

    usage_data[discord_user_id] = usage
    save_usage(usage_data)
    return True

# ================== QUẢN LÝ TÀI KHOẢN ==================
def get_active_account(discord_user_id: str) -> Optional[Dict[str, Any]]:
    data = user_sessions.get(discord_user_id)
    if not data:
        return None
    active_uid = data.get("active")
    if not active_uid:
        return None
    acc = data.get("accounts", {}).get(active_uid)
    if acc:
        try:
            decrypt_token(acc["token_encrypted"])
        except:
            remove_account(discord_user_id, active_uid)
            return get_active_account(discord_user_id)
    return acc

def get_all_accounts(discord_user_id: str) -> List[Dict[str, Any]]:
    return list(user_sessions.get(discord_user_id, {}).get("accounts", {}).values())

def set_active_account(discord_user_id: str, uid: str):
    if discord_user_id not in user_sessions:
        user_sessions[discord_user_id] = {"active": None, "accounts": {}}
    user_sessions[discord_user_id]["active"] = uid
    save_data()

def add_account(discord_user_id: str, token: str, uid: str, info: Dict):
    if discord_user_id not in user_sessions:
        user_sessions[discord_user_id] = {"active": None, "accounts": {}}
    encrypted = encrypt_token(token)
    user_sessions[discord_user_id]["accounts"][uid] = {
        "token_encrypted": encrypted,
        "uid": uid,
        "username": info.get("username", "Unknown"),
        "info": info
    }
    if not user_sessions[discord_user_id]["active"]:
        user_sessions[discord_user_id]["active"] = uid
    save_data()

def remove_account(discord_user_id: str, uid: str):
    data = user_sessions.get(discord_user_id)
    if not data:
        return
    if uid in data.get("accounts", {}):
        del data["accounts"][uid]
    if data.get("active") == uid and data["accounts"]:
        data["active"] = list(data["accounts"].keys())[0]
    elif data.get("active") == uid:
        data["active"] = None
    save_data()

def remove_task_from_user(user_id: str, task: asyncio.Task):
    if user_id in user_tasks and task in user_tasks[user_id]:
        user_tasks[user_id].remove(task)
        if not user_tasks[user_id]:
            del user_tasks[user_id]

async def cleanup_completed_tasks():
    for user_id in list(user_tasks.keys()):
        user_tasks[user_id] = [t for t in user_tasks[user_id] if not t.done()]
        if not user_tasks[user_id]:
            del user_tasks[user_id]

def can_add_task(user_id: int) -> bool:
    limits = get_user_limits(user_id)
    str_user_id = str(user_id)
    current_tasks = len(user_tasks.get(str_user_id, []))
    return current_tasks < limits["max_tasks"]

# ================== PROGRESS TRACKER (Realtime Update) ==================
_progress_lock = threading.Lock()
_progress = {
    'type': None,
    'done': 0,
    'total': 0,
    'speed': 0.0,
    'elapsed': 0.0,
    'status': 'idle',
    'message': ''
}

def update_progress(type_: str, done: int, total: int, speed: float = 0.0, elapsed: float = 0.0, status: str = 'running', message: str = ''):
    with _progress_lock:
        _progress['type'] = type_
        _progress['done'] = done
        _progress['total'] = total
        _progress['speed'] = speed
        _progress['elapsed'] = elapsed
        _progress['status'] = status
        _progress['message'] = message

async def progress_updater(interaction: discord.Interaction, stop_event: asyncio.Event):
    while not stop_event.is_set():
        with _progress_lock:
            p = _progress.copy()
        if p['status'] == 'idle':
            await asyncio.sleep(1)
            continue

        embed = discord.Embed(
            title=f"⏳ ĐANG {p['type'].upper()}",
            color=discord.Color.blue()
        )
        if p['type'] == 'xp':
            embed.title = "⚡ ĐANG CÀY XP"
            desc = f"🎯 **{p['done']:,} / {p['total']:,} XP**"
        elif p['type'] == 'gems':
            embed.title = "💎 ĐANG FARM GEMS"
            desc = f"💎 **{p['done']:,} / {p['total']:,} gems**"
        elif p['type'] == 'streak':
            embed.title = "🔥 ĐANG BUFF STREAK"
            desc = f"📆 **{p['done']:,} / {p['total']:,} ngày**"
        else:
            desc = "Đang xử lý..."

        if p['elapsed'] > 0:
            desc += f"\n⏱️ **{p['elapsed']:.1f}s** | 🚀 **{p['speed']:.1f} /s**"
        if p['message']:
            desc += f"\n{p['message']}"
        embed.description = desc
        embed.set_footer(text="Hybrid Bot")

        try:
            await interaction.edit_original_response(embed=embed)
        except Exception:
            pass

        await asyncio.sleep(1)

# ================== LỚP QUEST HELPER ==================
class QuestHelper:
    GOALS_API = "https://goals-api.duolingo.com"
    
    def __init__(self, token: str):
        self.token = token
        self.uid = get_user_id_from_token(token)
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest"
        }
    
    def _request(self, method, url, data=None):
        with requests.Session() as session:
            session.headers.update(self.headers)
            if method == 'GET':
                resp = session.get(url, timeout=5)
            else:
                resp = session.post(url, json=data, timeout=5)
            if resp.status_code == 200:
                return resp.json()
            return None
    
    def _get_goals(self) -> Optional[Dict]:
        try:
            return self._request('GET', f"{self.GOALS_API}/schema?ui_language=en&_={int(time.time()*1000)}")
        except:
            return None
    
    def _get_progress(self) -> Optional[Dict]:
        try:
            tz = 'UTC'
            return self._request('GET', f"{self.GOALS_API}/users/{self.uid}/progress?timezone={tz}&ui_language=en")
        except:
            return None
    
    def _get_quest_timestamp(self, goal_id: str) -> str:
        match = re.match(r'^(\d{4})_(\d{2})_monthly', goal_id)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            dt = datetime(year, month, 15, 12, 0, 0)
            return dt.isoformat() + 'Z'
        return datetime.now().isoformat() + 'Z'
    
    def _brute_force_goals(self, metrics: List[str], timestamp: str = None) -> bool:
        try:
            updates = [{"metric": m, "quantity": 2000} for m in metrics]
            updates.append({"metric": "QUESTS", "quantity": 1})
            if not timestamp:
                timestamp = datetime.now().isoformat() + 'Z'
            payload = {
                "metric_updates": updates,
                "timestamp": timestamp,
                "timezone": "UTC"
            }
            with requests.Session() as session:
                session.headers.update(self.headers)
                resp = session.post(
                    f"{self.GOALS_API}/users/{self.uid}/progress/batch",
                    json=payload,
                    timeout=5
                )
                return resp.status_code == 200
        except:
            return False
    
    def get_daily_quests(self) -> List[Dict]:
        try:
            schema = self._get_goals()
            progress = self._get_progress()
            if not schema or not progress:
                return []
            earned = set(progress.get('badges', {}).get('earned', []))
            daily_goals = [g for g in schema.get('goals', []) 
                          if g.get('category') and 'DAILY' in g.get('category', '')]
            quests = []
            for goal in daily_goals:
                goal_id = goal.get('goalId', '')
                metric = goal.get('metric', '')
                badge_id = goal.get('badgeId', '')
                prog_data = progress.get('goals', {}).get('progress', {})
                current = 0
                for key, val in prog_data.items():
                    if goal_id in key or badge_id in key:
                        if isinstance(val, dict):
                            current = val.get('progress', 0)
                        else:
                            current = val
                        break
                is_completed = (badge_id in earned) or (goal_id in earned) or (current >= goal.get('threshold', 0))
                quests.append({
                    "id": goal_id,
                    "name": goal.get('title', {}).get('uiString', 'Nhiệm vụ'),
                    "description": goal.get('subtitle', {}).get('uiString', ''),
                    "metric": metric,
                    "progress": current,
                    "target": goal.get('threshold', 0),
                    "completed": is_completed,
                    "badge_id": badge_id
                })
            return quests
        except Exception as e:
            logger.error(f"Lỗi get_daily_quests: {e}")
            return []
    
    def get_monthly_quests(self) -> List[Dict]:
        try:
            schema = self._get_goals()
            progress = self._get_progress()
            if not schema or not progress:
                return []
            earned = set(progress.get('badges', {}).get('earned', []))
            prog_data = progress.get('goals', {}).get('progress', {})
            month_keys = set()
            for key in prog_data.keys():
                if '_monthly' in key:
                    match = re.match(r'^(\d{4}_\d{2})_monthly', key)
                    if match:
                        month_keys.add(match.group(1))
            for goal in schema.get('goals', []):
                gid = goal.get('goalId', '')
                if '_monthly' in gid:
                    match = re.match(r'^(\d{4}_\d{2})_monthly', gid)
                    if match:
                        month_keys.add(match.group(1))
            quests = []
            for ym in sorted(month_keys, reverse=True):
                goal = None
                for g in schema.get('goals', []):
                    gid = g.get('goalId', '')
                    if ym in gid:
                        goal = g
                        break
                if not goal:
                    continue
                current = 0
                for key, val in prog_data.items():
                    if ym in key:
                        if isinstance(val, dict):
                            current = val.get('progress', 0)
                        else:
                            current = val
                        break
                is_completed = (goal.get('badgeId', '') in earned) or (goal.get('goalId', '') in earned)
                threshold = goal.get('threshold', 0)
                quests.append({
                    "id": goal.get('goalId', ''),
                    "name": goal.get('title', {}).get('uiString', f'Nhiệm vụ tháng {ym}'),
                    "month": ym,
                    "progress": current if not is_completed else threshold,
                    "target": threshold,
                    "completed": is_completed,
                    "badge_id": goal.get('badgeId', ''),
                    "metric": goal.get('metric', 'XP')
                })
            return quests
        except Exception as e:
            logger.error(f"Lỗi get_monthly_quests: {e}")
            return []
    
    def complete_daily_quests(self) -> Dict:
        result = {"completed": [], "failed": []}
        try:
            quests = self.get_daily_quests()
            if not quests:
                return result
            metrics = list(set([q['metric'] for q in quests if not q['completed'] and q['metric']]))
            if not metrics:
                return result
            timestamp = datetime.now().isoformat() + 'Z'
            if self._brute_force_goals(metrics, timestamp):
                updated = self.get_daily_quests()
                for q in updated:
                    if q['completed']:
                        result["completed"].append(q['id'])
                    else:
                        result["failed"].append(q['id'])
            else:
                for q in quests:
                    if not q['completed']:
                        result["failed"].append(q['id'])
            return result
        except Exception as e:
            logger.error(f"Lỗi complete_daily_quests: {e}")
            return result
    
    def claim_monthly_quests(self) -> Dict:
        result = {"completed": [], "failed": []}
        try:
            quests = self.get_monthly_quests()
            if not quests:
                return result
            for q in quests:
                if q['completed']:
                    result["completed"].append(q['id'])
                    continue
                if self._claim_monthly(q):
                    result["completed"].append(q['id'])
                else:
                    result["failed"].append(q['id'])
                time.sleep(0.3)
            return result
        except Exception as e:
            logger.error(f"Lỗi claim_monthly_quests: {e}")
            return result
    
    def _claim_monthly(self, quest: Dict) -> bool:
        try:
            timestamp = self._get_quest_timestamp(quest['id'])
            updates = [{"metric": quest['metric'], "quantity": quest['target']}]
            payload = {
                "metric_updates": updates,
                "timestamp": timestamp,
                "timezone": "UTC"
            }
            with requests.Session() as session:
                session.headers.update(self.headers)
                resp1 = session.post(
                    f"{self.GOALS_API}/users/{self.uid}/progress/batch",
                    json=payload,
                    timeout=5
                )
                if resp1.status_code != 200:
                    return False
                time.sleep(0.8)
                resp2 = session.post(
                    f"{self.GOALS_API}/users/{self.uid}/progress/batch",
                    json=payload,
                    timeout=5
                )
                return resp2.status_code == 200
        except:
            return False

# ================== LỚP DUOLINGO TỐC ĐỘ CAO (XP) ==================
class AsyncDuolingo:
    STORY_SLUGS = [
        "fr-en-le-passeport", "vi-en-le-passeport", "es-en-le-passeport",
        "de-en-le-passeport", "pt-en-le-passeport", "it-en-le-passeport",
        "en-es-the-passport", "en-fr-the-passport", "en-de-the-passport"
    ]
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ]

    def __init__(self, token: str, concurrency: int = 30, sleep: float = 0.01, use_proxy: bool = True):
        self.token = token
        self.uid = get_user_id_from_token(token)
        self.concurrency = concurrency
        self.sleep = sleep
        self.use_proxy = use_proxy
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.from_lang = "vi"
        self.learn_lang = "en"
        self.xp_before = 0
        self.total_earned = 0
        self.success_rate = 0
        self.total_attempts = 0
        self.successful_attempts = 0

    def _get_headers(self):
        headers = self.headers.copy()
        headers["User-Agent"] = random.choice(self.USER_AGENTS)
        return headers

    def _generate_payload(self, target_xp: int, custom_time: int = None):
        now = custom_time if custom_time else int(time.time())
        dur = random.randint(180, 300)
        return {
            "awardXp": True,
            "completedBonusChallenge": True,
            "fromLanguage": self.from_lang,
            "learningLanguage": self.learn_lang,
            "hasXpBoost": False,
            "isFeaturedStoryInPracticeHub": True,
            "isLegendaryMode": True,
            "isV2Redo": False,
            "isV2Story": False,
            "masterVersion": True,
            "score": 0,
            "maxScore": 0,
            "happyHourBonusXp": max(0, target_xp - 30),
            "startTime": now - dur,
            "endTime": now
        }

    async def _send_story_request(self, session: aiohttp.ClientSession, target_xp: int, custom_time: int = None, retries: int = 5) -> int:
        slug = random.choice(self.STORY_SLUGS)
        url = f"https://stories.duolingo.com/api2/stories/{slug}/complete"
        payload = self._generate_payload(target_xp, custom_time)
        
        for attempt in range(retries):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        earned = data.get("awardedXp", 0)
                        if earned > 0:
                            self.successful_attempts += 1
                            return earned
                    elif resp.status == 429:
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue
                    else:
                        await asyncio.sleep(0.05)
                        continue
            except:
                await asyncio.sleep(0.05)
                continue
        return 0

    async def _get_current_xp(self) -> int:
        try:
            headers = self._get_headers()
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(f"{BASE_URL}/{API_VERSION}/users/{self.uid}?fields=totalXp") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("totalXp", 0)
        except:
            pass
        return 0

    async def farm_xp(self, target_xp: int, progress_callback=None) -> Tuple[int, float, float]:
        total_earned = 0
        start_time = time.time()
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(self.concurrency)
        failed_attempts = 0
        max_fails = 200
        self.total_attempts = 0
        self.successful_attempts = 0
        
        self.xp_before = await self._get_current_xp()
        logger.info(f"📊 XP ban đầu: {self.xp_before:,}")

        # Tạo danh sách session (có thể dùng proxy nếu có)
        sessions = []
        timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=5)
        
        if self.use_proxy:
            proxies = proxy_manager.working_proxies
            if proxies:
                for proxy_url in proxies[:10]:  # Lấy tối đa 10 proxy để tạo session
                    try:
                        if proxy_url.startswith('socks5://'):
                            connector = ProxyConnector.from_url(proxy_url)
                        else:
                            connector = aiohttp.ProxyConnector.from_url(proxy_url)
                        sess = aiohttp.ClientSession(headers=self._get_headers(), connector=connector, timeout=timeout)
                        sessions.append(sess)
                    except Exception as e:
                        logger.debug(f"Không thể tạo session với proxy {proxy_url}: {e}")
        if not sessions:
            # Fallback: tạo session thường
            connector = aiohttp.TCPConnector(
                limit=self.concurrency * 2,
                limit_per_host=self.concurrency * 2,
                enable_cleanup_closed=True,
                force_close=False,
                ttl_dns_cache=600
            )
            sessions.append(aiohttp.ClientSession(headers=self._get_headers(), connector=connector, timeout=timeout))
        
        logger.info(f"🌐 Sử dụng {len(sessions)} session (proxy: {self.use_proxy and bool(proxy_manager.working_proxies)})")

        async def worker(sessions_list: List[aiohttp.ClientSession]):
            nonlocal total_earned, failed_attempts
            while True:
                async with lock:
                    if total_earned >= target_xp:
                        break
                    remaining = target_xp - total_earned
                    to_add = min(499, remaining)
                    if to_add < 30:
                        to_add = 30

                async with sem:
                    self.total_attempts += 1
                    session = random.choice(sessions_list)
                    earned = await self._send_story_request(session, to_add)
                
                if earned > 0:
                    async with lock:
                        total_earned += earned
                        failed_attempts = 0
                        if progress_callback:
                            progress_callback(total_earned, target_xp, time.time() - start_time)
                else:
                    failed_attempts += 1
                    if failed_attempts >= max_fails:
                        break
                    await asyncio.sleep(0.05)
                
                await asyncio.sleep(self.sleep)

        async def logger_task():
            last_log = 0
            while True:
                await asyncio.sleep(0.3)
                async with lock:
                    curr_earned = total_earned
                elapsed = time.time() - start_time
                speed = curr_earned / elapsed if elapsed > 0 else 0
                success_rate = (self.successful_attempts / self.total_attempts * 100) if self.total_attempts > 0 else 0
                
                if time.time() - last_log > 1:
                    pct = (curr_earned / target_xp) * 100
                    logger.info(f"⚡ XP: {curr_earned:,}/{target_xp:,} ({pct:.1f}%) | Speed: {speed:.1f} XP/s | Success: {success_rate:.1f}% | Workers: {self.concurrency}")
                    last_log = time.time()
                
                if curr_earned >= target_xp or failed_attempts >= max_fails:
                    break

        log_bg = asyncio.create_task(logger_task())
        workers = [asyncio.create_task(worker(sessions)) for _ in range(self.concurrency)]
        
        await asyncio.gather(*workers)
        log_bg.cancel()
        
        # Đóng các session
        for sess in sessions:
            await sess.close()

        xp_after = await self._get_current_xp()
        actual_gained = xp_after - self.xp_before
        
        success_rate = (self.successful_attempts / self.total_attempts * 100) if self.total_attempts > 0 else 0
        logger.info(f"📊 Tỷ lệ thành công: {success_rate:.1f}% ({self.successful_attempts}/{self.total_attempts})")
        
        if actual_gained > 0:
            logger.info(f"🎯 XP thực tế nhận: +{actual_gained:,} (đã farm: {total_earned:,})")
            total_earned = max(total_earned, actual_gained)

        total_time = time.time() - start_time
        avg_speed = total_earned / total_time if total_time > 0 else 0
        return total_earned, total_time, avg_speed

# ================== Selenium Driver Manager ==================
_selenium_driver = None
_driver_lock = threading.Lock()

def get_selenium_driver():
    global _selenium_driver
    with _driver_lock:
        if _selenium_driver is None:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-images')
            options.add_argument('--blink-settings=imagesEnabled=false')
            options.add_experimental_option("prefs", {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values.notifications": 2
            })
            service = Service(ChromeDriverManager().install())
            _selenium_driver = webdriver.Chrome(service=service, options=options)
            _selenium_driver.get('https://www.duolingo.com/')
            atexit.register(lambda: _selenium_driver.quit())
        return _selenium_driver

def send_request_via_selenium(token: str, method: str, url: str, data: dict = None, retries: int = 3) -> dict:
    driver = get_selenium_driver()
    driver.delete_cookie('jwt_token')
    driver.add_cookie({'name': 'jwt_token', 'value': token, 'domain': '.duolingo.com', 'path': '/'})
    
    script = """
    var method = arguments[0];
    var url = arguments[1];
    var data = arguments[2];
    var token = arguments[3];
    var callback = arguments[4];
    var options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        credentials: 'include'
    };
    if (data) {
        options.body = JSON.stringify(data);
    }
    fetch(url, options)
        .then(r => r.json())
        .then(result => callback(result))
        .catch(err => callback({error: err.message}));
    """
    for attempt in range(retries):
        try:
            result = driver.execute_async_script(script, method, url, data, token)
            if isinstance(result, dict) and 'error' in result:
                raise Exception(result['error'])
            return result
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(0.1)
    return None

# ================== LỚP CURL_DUOLINGO (dùng Selenium cho gems, curl_cffi cho streak) ==================
class CurlDuolingo:
    def __init__(self, token: str):
        self.token = token
        self.uid = get_user_id_from_token(token)
        self._stop_event = None
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        # ==== TỐI ƯU: Tạo session dùng chung để tái sử dụng connection ====
        self._session = requests.Session()
        self._session.headers.update(self.headers)
    
    def set_stop_event(self, event):
        self._stop_event = event
    
    def _should_stop(self):
        if self._stop_event and self._stop_event.is_set():
            return True
        return False
    
    # ---------- Selenium request (chỉ dùng cho gems) ----------
    def _send_request_selenium(self, method, url, data=None, retries=3):
        return send_request_via_selenium(self.token, method, url, data, retries)
    
    # ---------- curl_cffi request (dùng cho streak để tăng tốc) ----------
    def _send_request_curl(self, method, url, data=None, retries=5):
        try:
            if method.upper() == 'GET':
                resp = self._session.get(url, timeout=5)
            elif method.upper() == 'POST':
                resp = self._session.post(url, json=data, timeout=5)
            elif method.upper() == 'PUT':
                resp = self._session.put(url, json=data, timeout=5)
            else:
                return None
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            if retries > 1:
                time.sleep(0.05)
                return self._send_request_curl(method, url, data, retries-1)
            return None

    # Phiên bản trả về status code để xử lý 429
    def _send_request_curl_status(self, method, url, data=None, retries=3):
        try:
            if method.upper() == 'GET':
                resp = self._session.get(url, timeout=5)
            elif method.upper() == 'POST':
                resp = self._session.post(url, json=data, timeout=5)
            elif method.upper() == 'PUT':
                resp = self._session.put(url, json=data, timeout=5)
            else:
                return (0, None)
            if resp.status_code == 200:
                try:
                    return (resp.status_code, resp.json())
                except:
                    return (resp.status_code, None)
            else:
                return (resp.status_code, None)
        except Exception as e:
            if retries > 1:
                time.sleep(0.05)
                return self._send_request_curl_status(method, url, data, retries-1)
            return (0, None)
    
    # ================== FARM GEMS (dùng Selenium) ==================
    def farm_gems(self, target_gems: int, progress_callback=None) -> int:
        max_retries = 20
        total_gained = 0
        consecutive_empty = 0
        
        try:
            info = self._send_request_selenium('GET', f"{BASE_URL}/{API_VERSION}/users/{self.uid}?fields=gems")
            if info and 'gems' in info:
                gems_before = info.get("gems", 0)
                logger.info(f"💎 Gems ban đầu: {gems_before:,}")
            else:
                gems_before = 0
        except:
            gems_before = 0
        
        for attempt in range(max_retries):
            if self._should_stop():
                logger.info("⏹️ Dừng farm gems do người dùng yêu cầu")
                break
                
            try:
                data = self._send_request_selenium('GET', f"https://www.duolingo.com/2023-05-23/users/{self.uid}?fields=rewardBundles{{rewards}}")
                if not data:
                    time.sleep(0.3)
                    consecutive_empty += 1
                    if consecutive_empty > 3:
                        try:
                            now = int(time.time())
                            dur = random.randint(300, 600)
                            slug = random.choice(["fr-en-le-passeport", "vi-en-le-passeport", "es-en-le-passeport"])
                            story_payload = {
                                "awardXp": True,
                                "completedBonusChallenge": True,
                                "fromLanguage": "vi",
                                "learningLanguage": "en",
                                "hasXpBoost": False,
                                "illustrationFormat": "svg",
                                "isFeaturedStoryInPracticeHub": True,
                                "isLegendaryMode": True,
                                "isV2Redo": False,
                                "isV2Story": False,
                                "masterVersion": True,
                                "maxScore": 0,
                                "score": 0,
                                "happyHourBonusXp": random.randint(400, 500),
                                "startTime": now - dur,
                                "endTime": now
                            }
                            self._send_request_selenium('POST', f"https://stories.duolingo.com/api2/stories/{slug}/complete", story_payload)
                            logger.info("💎 Đã farm story để tạo reward bundles...")
                            time.sleep(1.5)
                            consecutive_empty = 0
                            continue
                        except:
                            time.sleep(0.5)
                            continue
                    time.sleep(0.3)
                    continue
                
                bundles = data.get("rewardBundles", [])
                rewards = []
                for bundle in bundles:
                    for reward in bundle.get("rewards", []):
                        if not reward.get("consumed", True):
                            amount = reward.get("amount", 0)
                            reward_type = reward.get("type", "")
                            if amount > 0 and reward_type in ["GEM", "GEM_BUNDLE", "gem", "gem_bundle"]:
                                rewards.append(reward)
                
                if not rewards:
                    consecutive_empty += 1
                    if consecutive_empty > 5:
                        logger.info("💎 Không có reward, thử farm story...")
                        try:
                            now = int(time.time())
                            dur = random.randint(300, 600)
                            slug = random.choice(["fr-en-le-passeport", "vi-en-le-passeport", "es-en-le-passeport"])
                            story_payload = {
                                "awardXp": True,
                                "completedBonusChallenge": True,
                                "fromLanguage": "vi",
                                "learningLanguage": "en",
                                "hasXpBoost": False,
                                "illustrationFormat": "svg",
                                "isFeaturedStoryInPracticeHub": True,
                                "isLegendaryMode": True,
                                "isV2Redo": False,
                                "isV2Story": False,
                                "masterVersion": True,
                                "maxScore": 0,
                                "score": 0,
                                "happyHourBonusXp": random.randint(400, 500),
                                "startTime": now - dur,
                                "endTime": now
                            }
                            self._send_request_selenium('POST', f"https://stories.duolingo.com/api2/stories/{slug}/complete", story_payload)
                            time.sleep(1.5)
                            consecutive_empty = 0
                            continue
                        except:
                            pass
                    time.sleep(0.3)
                    continue
                
                consecutive_empty = 0
                claimed_any = False
                
                for reward in rewards:
                    if self._should_stop():
                        break
                    try:
                        claim_url = f"https://www.duolingo.com/2023-05-23/users/{self.uid}/rewards/{reward['id']}"
                        payload = {
                            "consumed": True, 
                            "fromLanguage": "vi", 
                            "learningLanguage": "en"
                        }
                        claim = self._send_request_selenium('PATCH', claim_url, payload)
                        if claim and claim.get('status') != 'error':
                            amount = reward.get("amount", 0)
                            total_gained += amount
                            claimed_any = True
                            if progress_callback:
                                progress_callback(total_gained, target_gems)
                            logger.debug(f"💎 Claimed {amount} gems (total: {total_gained})")
                        time.sleep(0.02)
                    except:
                        pass
                
                if claimed_any:
                    try:
                        time.sleep(0.5)
                        info_after = self._send_request_selenium('GET', f"{BASE_URL}/{API_VERSION}/users/{self.uid}?fields=gems")
                        if info_after and 'gems' in info_after:
                            gems_after = info_after.get("gems", 0)
                            actual_gained = gems_after - gems_before
                            if actual_gained > 0:
                                logger.info(f"💎 Gems thực tế nhận: +{actual_gained:,}")
                                return max(actual_gained, total_gained)
                    except:
                        pass
                    
                    if total_gained >= target_gems:
                        break
                
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"❌ Lỗi farm gems: {e}")
                time.sleep(1)
                continue
        
        if total_gained > 0:
            logger.info(f"💎 Đã claim {total_gained} gems (ước tính)")
            return total_gained
        
        return 0

    # ================== BUFF STREAK (dùng curl_cffi để tăng tốc) ==================
    def buff_streak(self, target_days: int, progress_callback=None) -> int:
        if target_days <= 0:
            return 0
        
        target_days = min(target_days, 5000)
        
        # Lấy thông tin hiện tại
        try:
            info = self._send_request_curl('GET', f"{BASE_URL}/{API_VERSION}/users/{self.uid}?fields=streak,streakData,fromLanguage,learningLanguage")
            if info:
                current_streak = info.get("streak", 0)
                streak_data = info.get("streakData", {})
                current_data = streak_data.get("currentStreak", {})
                base_date = current_data.get("startDate")
                from_lang = info.get("fromLanguage", "vi")
                learn_lang = info.get("learningLanguage", "en")
            else:
                current_streak = 0
                base_date = None
                from_lang = "vi"
                learn_lang = "en"
        except:
            current_streak = 0
            base_date = None
            from_lang = "vi"
            learn_lang = "en"
        
        logger.info(f"📊 Streak hiện tại: {current_streak} ngày")
        
        if not base_date or not re.match(r"\d{4}-\d{2}-\d{2}", base_date):
            base_date = datetime.now().strftime("%Y-%m-%d")
        
        base_parts = base_date.split("-")
        base_year = int(base_parts[0])
        base_month = int(base_parts[1])
        base_day = int(base_parts[2])
        
        challenge_types = [
            "assist", "definition", "gapFill", "judge", "listen", 
            "match", "select", "translate", "typeCloze", "tapComplete",
            "listenTap", "listenSelect", "speak", "completeReverseTranslation",
            "listening", "reading", "writing", "speaking", "comprehension",
            "characterMatch", "characterSelect", "syllableTap"
        ]
        
        logger.info(f"🔥 Bắt đầu buff {target_days} ngày streak...")
        
        saved = 0
        consecutive_fail = 0
        consecutive_create_fail = 0
        
        while saved < target_days and not self._should_stop():
            try:
                target_dt = datetime(base_year, base_month, base_day, 12, 0, 0) - timedelta(days=1 + saved)
                end_time = int(target_dt.timestamp())
                start_time = end_time - random.randint(120, 300)
                
                # Tạo session
                session_payload = {
                    "challengeTypes": random.sample(challenge_types, min(7, len(challenge_types))),
                    "fromLanguage": from_lang,
                    "learningLanguage": learn_lang,
                    "isFinalLevel": False,
                    "isV2": True,
                    "juicy": True,
                    "smartTipsVersion": 2,
                    "type": "GLOBAL_PRACTICE"
                }
                
                # Thử tạo session với retry
                res = None
                status_code = 0
                for attempt in range(3):
                    status_code, res = self._send_request_curl_status('POST', f"{BASE_URL}/{API_VERSION}/sessions", session_payload)
                    if status_code == 200 and res and res.get("id"):
                        break
                    else:
                        # Thử payload đơn giản
                        simple_payload = {
                            "challengeTypes": ["translate", "select", "gapFill"],
                            "fromLanguage": from_lang,
                            "learningLanguage": learn_lang,
                            "type": "PRACTICE"
                        }
                        status_code, res = self._send_request_curl_status('POST', f"{BASE_URL}/{API_VERSION}/sessions", simple_payload)
                        if status_code == 200 and res and res.get("id"):
                            break
                        time.sleep(0.1)
                if status_code != 200 or not res or not res.get("id"):
                    consecutive_create_fail += 1
                    if consecutive_create_fail > 10:
                        logger.warning("⚠️ Quá nhiều lỗi tạo session, tạm dừng 5s...")
                        time.sleep(5)
                        consecutive_create_fail = 0
                        try:
                            driver = get_selenium_driver()
                            driver.refresh()
                            time.sleep(1)
                        except:
                            pass
                    else:
                        time.sleep(0.05)
                    continue
                consecutive_create_fail = 0
                sess_data = res
                sess_id = sess_data.get("id")
                
                # Thử hoàn thành session
                complete_success = False
                complete_payload = {
                    **sess_data,
                    "heartsLeft": 5,
                    "startTime": start_time,
                    "endTime": end_time,
                    "enableBonusPoints": False,
                    "failed": False,
                    "maxInLessonStreak": 9,
                    "shouldLearnThings": True,
                    "awardXp": True,
                    "hasXpBoost": False,
                    "streakExtended": True,
                    "isPractice": True
                }
                for attempt in range(2):
                    status_code, complete = self._send_request_curl_status('PUT', f"{BASE_URL}/{API_VERSION}/sessions/{sess_id}", complete_payload)
                    if status_code == 200 and complete and complete.get('status') != 'error':
                        complete_success = True
                        break
                    else:
                        # Thử payload tối giản
                        alt_payload = {
                            "heartsLeft": 5,
                            "startTime": start_time,
                            "endTime": end_time,
                            "failed": False,
                            "awardXp": True,
                            "streakExtended": True
                        }
                        status_code, complete_alt = self._send_request_curl_status('PUT', f"{BASE_URL}/{API_VERSION}/sessions/{sess_id}", alt_payload)
                        if status_code == 200 and complete_alt and complete_alt.get('status') != 'error':
                            complete_success = True
                            break
                        time.sleep(0.05)
                
                if complete_success:
                    saved += 1
                    consecutive_fail = 0
                    if progress_callback:
                        progress_callback(saved, target_days)
                    if saved % 5 == 0:
                        logger.info(f"✅ Đã buff {saved}/{target_days} ngày")
                    # Sleep ngắn nhưng không quá thấp để tránh rate limit
                    time.sleep(random.uniform(0.005, 0.01))
                else:
                    consecutive_fail += 1
                    if consecutive_fail > 10:
                        logger.warning("⚠️ Quá nhiều lỗi hoàn thành session, tạm dừng 5s...")
                        time.sleep(5)
                        consecutive_fail = 0
                        try:
                            driver = get_selenium_driver()
                            driver.refresh()
                            time.sleep(1)
                        except:
                            pass
                    else:
                        # Nếu lỗi hoàn thành, thử tạo session mới ngay
                        time.sleep(0.05)
            except Exception as e:
                logger.debug(f"Lỗi buff ngày: {e}")
                consecutive_fail += 1
                if consecutive_fail > 10:
                    logger.warning("⚠️ Quá nhiều lỗi, tạm dừng 10s...")
                    time.sleep(10)
                    consecutive_fail = 0
                    try:
                        driver = get_selenium_driver()
                        driver.refresh()
                        time.sleep(1)
                    except:
                        pass
                else:
                    time.sleep(0.05)
                continue
            
            # Reset driver sau mỗi 100 ngày để tránh memory leak
            if saved > 0 and saved % 100 == 0:
                try:
                    driver = get_selenium_driver()
                    driver.refresh()
                    time.sleep(1.5)
                except:
                    pass
        
        if self._should_stop():
            logger.info("⏹️ Dừng buff streak do người dùng yêu cầu")
        
        # Kiểm tra streak sau khi buff
        try:
            time.sleep(2)
            info_after = self._send_request_curl('GET', f"{BASE_URL}/{API_VERSION}/users/{self.uid}?fields=streak")
            if info_after and 'streak' in info_after:
                streak_after = info_after.get("streak", 0)
                actual_saved = streak_after - current_streak
                if actual_saved > 0:
                    logger.info(f"✅ Streak thực tế tăng: +{actual_saved} ngày")
                    return max(actual_saved, saved)
        except Exception as e:
            logger.debug(f"Lỗi kiểm tra streak: {e}")
        
        logger.info(f"✅ Đã buff {saved} ngày streak (ước tính)")
        return saved

# ================== DISCORD BOT ==================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================== VIEWS ==================
class ShopSelect(discord.ui.Select):
    def __init__(self, items, token, uid, user_id, parent_view):
        options = []
        for i, item in enumerate(items[:20]):
            name = item.get("name") or item.get("id") or f"Item {i+1}"
            label = name[:100]
            if not label:
                label = "Item"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(i),
                    description=("Free" if item.get("currencyType") == "XGM" else "Paid")[:100]
                )
            )
        super().__init__(placeholder="Chọn vật phẩm để mua...", options=options, min_values=1, max_values=1)
        self.token = token
        self.uid = uid
        self.items = items
        self.user_id = user_id
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
            return
        idx = int(self.values[0])
        item = self.items[idx]
        self.parent_view.selected_item = item
        embed = discord.Embed(
            title="✅ Đã chọn",
            description=f"Đã chọn **{item.get('name', item.get('id', 'Item'))}**\nDùng nút bên dưới để mua.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class ShopView(discord.ui.View):
    def __init__(self, items, token, uid, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.items = items
        self.token = token
        self.uid = uid
        self.selected_item = None
        self.add_item(ShopSelect(items, token, uid, user_id, self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Mua x5", style=discord.ButtonStyle.green, custom_id="buy5")
    async def buy5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._buy_multiple(interaction, 5)

    @discord.ui.button(label="Mua x10", style=discord.ButtonStyle.green, custom_id="buy10")
    async def buy10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._buy_multiple(interaction, 10)

    @discord.ui.button(label="Mua tất cả free", style=discord.ButtonStyle.blurple, custom_id="buyall")
    async def buyall(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.items:
            await interaction.response.send_message("Không có item free.", ephemeral=True)
            return
        await interaction.response.defer()
        total = 0
        for item in self.items:
            if self._buy_item(item):
                total += 1
            await asyncio.sleep(0.2)
        embed = discord.Embed(
            title="🛒 Mua tất cả",
            description=f"Đã mua {total}/{len(self.items)} item.",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Đóng", style=discord.ButtonStyle.red, custom_id="close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🛒 Đã đóng shop.", embed=None, view=None)

    async def _buy_multiple(self, interaction: discord.Interaction, times: int):
        if not self.selected_item:
            await interaction.response.send_message("⚠️ Hãy chọn item trước!", ephemeral=True)
            return
        await interaction.response.defer()
        success = 0
        for _ in range(times):
            if self._buy_item(self.selected_item):
                success += 1
            await asyncio.sleep(0.3)
        embed = discord.Embed(
            title=f"🛒 Mua x{times}",
            description=f"Đã mua thành công {success}/{times} lần.",
            color=discord.Color.green() if success > 0 else discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed, view=self)

    def _buy_item(self, item):
        try:
            import requests as req
            with req.Session() as session:
                session.headers.update({
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                })
                payload = {
                    "itemName": item.get("id"),
                    "isFree": True,
                    "consumed": True,
                    "fromLanguage": "vi",
                    "learningLanguage": "en"
                }
                res = session.post(
                    f"{BASE_URL}/{API_VERSION}/users/{self.uid}/shop-items",
                    json=payload,
                    timeout=5
                )
                return res.status_code in [200, 201]
        except:
            return False

class AccountView(discord.ui.View):
    def __init__(self, accs, user_id):
        super().__init__(timeout=120)
        self.accs = accs
        self.user_id = user_id
        self.add_item(AccountSelect(accs, user_id))

class AccountSelect(discord.ui.Select):
    def __init__(self, accs, user_id):
        options = []
        for i, acc in enumerate(accs[:20]):
            name = acc.get("username") or f"Account {i+1}"
            label = name[:100]
            if not label:
                label = "Account"
            desc = f"ID: {acc.get('uid', 'Unknown')[:20]}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(i),
                    description=desc[:100]
                )
            )
        super().__init__(placeholder="Chọn tài khoản để chuyển...", options=options, min_values=1, max_values=1)
        self.accs = accs
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
            return
        idx = int(self.values[0])
        acc = self.accs[idx]
        uid = acc["uid"]
        username = acc.get("username", "Unknown")
        set_active_account(str(interaction.user.id), uid)
        embed = discord.Embed(
            title="✅ Đã chuyển tài khoản!",
            description=f"Đã chuyển sang **{username}** (ID: {uid})",
            color=discord.Color.green()
        )
        embed.set_footer(text="Hybrid Bot")
        await interaction.response.edit_message(embed=embed, view=None)

# ================== LỆNH SLASH ==================
@bot.tree.command(name="farmxp", description="⚡ Cày XP (CRE không giới hạn)")
@app_commands.describe(xp="Số XP muốn farm (CRE: không giới hạn, User/VIP tối đa 5.000.000)")
async def farmxp(interaction: discord.Interaction, xp: int):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return
    
    user_id = str(interaction.user.id)
    user_id_int = interaction.user.id
    role = get_role(user_id_int)
    
    if xp <= 0:
        await interaction.followup.send("⚠️ XP phải lớn hơn 0.")
        return
    if role != "CRE" and xp > 5000000:
        await interaction.followup.send("⚠️ User/VIP chỉ được farm tối đa 5.000.000 XP.")
        return
    
    if not can_add_task(user_id_int):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⏳ Đã đạt giới hạn {limits['max_tasks']} task!")
        return
    
    if not check_and_update_limits(user_id, xp_delta=xp):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⚠️ Đã đạt giới hạn XP ({limits['xp_limit']:,} XP).")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng. Đăng nhập lại.")
        return

    limits = get_user_limits(user_id_int)
    embed = discord.Embed(title="⚡ KHỞI ĐỘNG CÀY XP", color=discord.Color.gold())
    embed.description = f"🎯 {xp:,} XP\n🏅 **{role}**\n🚀 {limits['concurrency']} luồng"
    await interaction.edit_original_response(embed=embed)

    task = asyncio.create_task(farm_xp_hybrid(interaction, token, xp, user_id_int))
    if user_id not in user_tasks:
        user_tasks[user_id] = []
    user_tasks[user_id].append(task)

@bot.tree.command(name="farmgems", description="💎 Farm Gems")
@app_commands.describe(gems="Số gems muốn farm (tối đa 50.000)")
async def farmgems(interaction: discord.Interaction, gems: int = 10000):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập.")
        return
    if not (1 <= gems <= 50000):
        await interaction.followup.send("⚠️ Gems từ 1 đến 50.000.")
        return
    
    user_id = str(interaction.user.id)
    user_id_int = interaction.user.id
    
    if not can_add_task(user_id_int):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⏳ Đã đạt giới hạn {limits['max_tasks']} task!")
        return
    
    if not check_and_update_limits(user_id, gems_delta=gems):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⚠️ Đã đạt giới hạn gems ({limits['gems_limit']:,} gems).")
        return
        
    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return
        
    role = get_role(user_id_int)
    embed = discord.Embed(title="💎 KHỞI ĐỘNG FARM GEMS", color=discord.Color.purple())
    embed.description = f"🎯 {gems:,} gems\n🏅 **{role}**"
    await interaction.edit_original_response(embed=embed)
    task = asyncio.create_task(farm_gems_hybrid(interaction, token, gems))
    if user_id not in user_tasks:
        user_tasks[user_id] = []
    user_tasks[user_id].append(task)

@bot.tree.command(name="buffstreak", description="🔥 Buff Streak (CRE không giới hạn)")
@app_commands.describe(count="Số ngày muốn buff (CRE: không giới hạn, User/VIP tối đa 10.000)")
async def buffstreak(interaction: discord.Interaction, count: int):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    user_id_int = interaction.user.id
    role = get_role(user_id_int)
    
    if count <= 0:
        await interaction.followup.send("⚠️ Số ngày phải lớn hơn 0.")
        return
    if role != "CRE" and count > 10000:
        await interaction.followup.send(f"⚠️ {role} chỉ được buff tối đa 10.000 ngày.")
        return
    
    if not can_add_task(user_id_int):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⏳ Đã đạt giới hạn {limits['max_tasks']} task!")
        return

    if not check_and_update_limits(user_id, streak_delta=count):
        limits = get_user_limits(user_id_int)
        await interaction.followup.send(f"⚠️ Đã đạt giới hạn streak ({limits['streak_limit']} ngày).")
        return

    acc = get_active_account(user_id)
    if not acc:
        await interaction.followup.send("⚠️ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    embed = discord.Embed(title="🔥 KHỞI ĐỘNG BUFF STREAK", color=discord.Color.orange())
    embed.description = f"🎯 +{count} ngày\n🏅 **{role}**"
    await interaction.edit_original_response(embed=embed)

    task = asyncio.create_task(buff_streak_hybrid(interaction, token, count, user_id_int))
    if user_id not in user_tasks:
        user_tasks[user_id] = []
    user_tasks[user_id].append(task)

@bot.tree.command(name="dailyquest", description="📋 Hoàn thành nhiệm vụ hàng ngày")
async def daily_quest(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    embed = discord.Embed(
        title="📋 ĐANG HOÀN THÀNH NHIỆM VỤ NGÀY...",
        description="Đang xử lý...",
        color=discord.Color.blue()
    )
    await interaction.edit_original_response(embed=embed)

    helper = QuestHelper(token)
    result = await asyncio.get_event_loop().run_in_executor(shared_executor, helper.complete_daily_quests)

    embed = discord.Embed(
        title="📋 KẾT QUẢ NHIỆM VỤ NGÀY",
        color=discord.Color.green() if result["completed"] else discord.Color.red()
    )
    embed.add_field(
        name="✅ Hoàn thành",
        value=f"{len(result['completed'])} nhiệm vụ" if result["completed"] else "Không có",
        inline=True
    )
    embed.add_field(
        name="❌ Thất bại",
        value=f"{len(result['failed'])} nhiệm vụ" if result["failed"] else "Không có",
        inline=True
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)

@bot.tree.command(name="monthlyclaim", description="🎁 Claim nhiệm vụ hàng tháng")
async def monthly_claim(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    embed = discord.Embed(
        title="🎁 ĐANG CLAIM NHIỆM VỤ THÁNG...",
        description="Đang xử lý...",
        color=discord.Color.blue()
    )
    await interaction.edit_original_response(embed=embed)

    helper = QuestHelper(token)
    try:
        result = await asyncio.get_event_loop().run_in_executor(shared_executor, helper.claim_monthly_quests)
    except Exception as e:
        embed = discord.Embed(
            title="❌ LỖI CLAIM",
            description=f"Lỗi: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed)
        return

    embed = discord.Embed(
        title="🎁 KẾT QUẢ CLAIM NHIỆM VỤ THÁNG",
        color=discord.Color.green() if result["completed"] else discord.Color.red()
    )
    embed.add_field(
        name="✅ Đã claim",
        value=f"{len(result['completed'])} nhiệm vụ" if result["completed"] else "Không có",
        inline=True
    )
    embed.add_field(
        name="❌ Thất bại",
        value=f"{len(result['failed'])} nhiệm vụ" if result["failed"] else "Không có",
        inline=True
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)

@bot.tree.command(name="shop", description="🛒 Shop - Chọn vật phẩm miễn phí")
async def shop(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    import requests as req
    with req.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        uid = get_user_id_from_token(token)

        try:
            test_resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=id", timeout=3)
            if test_resp.status_code != 200:
                await interaction.followup.send("❌ Token không hợp lệ.")
                return
        except:
            await interaction.followup.send("❌ Lỗi kết nối.")
            return

        try:
            res = session.get(f"{BASE_URL}/2023-05-23/shop-items", timeout=3)
            if res.status_code != 200:
                await interaction.followup.send(f"❌ Lỗi shop: {res.status_code}")
                return
            items = res.json().get("shopItems", [])
        except:
            await interaction.followup.send("❌ Lỗi dữ liệu shop.")
            return

    free_items = [item for item in items if item.get("currencyType") == "XGM" and "gift" not in item.get("id", "")]
    if not free_items:
        await interaction.followup.send("⚠️ Không có vật phẩm miễn phí.")
        return

    embed = discord.Embed(
        title="🛒 SHOP - Vật phẩm miễn phí",
        description=f"Có **{len(free_items)}** vật phẩm.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Hybrid Bot")
    
    view = ShopView(free_items, token, uid, str(interaction.user.id))
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="login", description="🔑 Đăng nhập Duolingo")
@app_commands.describe(token="JWT Token")
async def login(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)
    if not verify_token_signature(token):
        await interaction.followup.send("❌ Token không hợp lệ!")
        return
    try:
        import requests as req
        with req.Session() as session:
            session.headers.update({
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            })
            uid = get_user_id_from_token(token)
            resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=id,username,name,streak,totalXp,gems,picture", timeout=3)
            if resp.status_code != 200:
                await interaction.followup.send("❌ Token không hợp lệ.")
                return
            info = resp.json()

        if str(interaction.user.id) not in user_sessions:
            user_sessions[str(interaction.user.id)] = {"active": None, "accounts": {}}
        if uid in user_sessions[str(interaction.user.id)]["accounts"]:
            user_sessions[str(interaction.user.id)]["accounts"][uid]["token_encrypted"] = encrypt_token(token)
            user_sessions[str(interaction.user.id)]["accounts"][uid]["info"] = info
            user_sessions[str(interaction.user.id)]["accounts"][uid]["username"] = info.get("username", "Unknown")
        else:
            add_account(str(interaction.user.id), token, uid, info)
        set_active_account(str(interaction.user.id), uid)
        embed = discord.Embed(title="✅ Đăng nhập thành công!", color=discord.Color.green())
        embed.add_field(name="Tài khoản", value=f"{info.get('name')} (@{info.get('username')})", inline=False)
        embed.add_field(name="🔥 Streak", value=f"{info.get('streak', 0):,} ngày", inline=True)
        embed.add_field(name="⚡ XP", value=f"{info.get('totalXp', 0):,}", inline=True)
        embed.add_field(name="💎 Gems", value=f"{info.get('gems', 0):,}", inline=True)
        embed.set_footer(text="Hybrid Bot")
        avatar_url = info.get("picture")
        if avatar_url:
            if avatar_url.startswith("//"):
                avatar_url = "https:" + avatar_url
            embed.set_thumbnail(url=avatar_url)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Lỗi: {e}")

@bot.tree.command(name="listacc", description="📋 Danh sách tài khoản")
async def listacc(interaction: discord.Interaction):
    await interaction.response.defer()
    accs = get_all_accounts(str(interaction.user.id))
    if not accs:
        await interaction.followup.send("❌ Chưa có tài khoản.")
        return
    data = user_sessions.get(str(interaction.user.id), {})
    active_uid = data.get("active")
    embed = discord.Embed(title="📋 DANH SÁCH TÀI KHOẢN", color=discord.Color.blue())
    for i, acc in enumerate(accs[:20]):
        uid = acc["uid"]
        username = acc.get("username", "Unknown")
        info = acc.get("info", {})
        streak = info.get("streak", 0)
        xp = info.get("totalXp", 0)
        gems = info.get("gems", 0)
        active_mark = "✅ **ĐANG DÙNG**" if uid == active_uid else ""
        embed.add_field(
            name=f"{i+1}. {username} {active_mark}",
            value=f"🔥 {streak} ngày | ⚡ {xp:,} | 💎 {gems:,}",
            inline=False
        )
    embed.set_footer(text="Chọn tài khoản bên dưới")
    view = AccountView(accs, str(interaction.user.id))
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="switchacc", description="🔄 Chuyển đổi tài khoản")
@app_commands.describe(number="Số thứ tự (xem /listacc)")
async def switchacc(interaction: discord.Interaction, number: int):
    await interaction.response.defer()
    accs = get_all_accounts(str(interaction.user.id))
    if not accs:
        await interaction.followup.send("❌ Chưa có tài khoản.")
        return
    if number < 1 or number > len(accs):
        await interaction.followup.send(f"❌ Số thứ tự từ 1 đến {len(accs)}.")
        return
    acc = accs[number - 1]
    uid = acc["uid"]
    set_active_account(str(interaction.user.id), uid)
    username = acc.get("username", "Unknown")
    await interaction.followup.send(f"✅ Đã chuyển sang **{username}** (ID: {uid})")

@bot.tree.command(name="delacc", description="🗑️ Xóa tài khoản")
@app_commands.describe(number="Số thứ tự (xem /listacc)")
async def delacc(interaction: discord.Interaction, number: int):
    await interaction.response.defer()
    accs = get_all_accounts(str(interaction.user.id))
    if not accs:
        await interaction.followup.send("❌ Chưa có tài khoản.")
        return
    if number < 1 or number > len(accs):
        await interaction.followup.send(f"❌ Số thứ tự từ 1 đến {len(accs)}.")
        return
    acc = accs[number - 1]
    uid = acc["uid"]
    username = acc.get("username", "Unknown")
    remove_account(str(interaction.user.id), uid)
    await interaction.followup.send(f"🗑️ Đã xóa **{username}** (ID: {uid})")

@bot.tree.command(name="addacc", description="➕ Thêm tài khoản")
@app_commands.describe(token="JWT Token")
async def addacc(interaction: discord.Interaction, token: str):
    await interaction.response.defer()
    if not verify_token_signature(token):
        await interaction.followup.send("❌ Token không hợp lệ!")
        return
    try:
        import requests as req
        with req.Session() as session:
            session.headers.update({
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            })
            uid = get_user_id_from_token(token)
            resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=id,username,name,streak,totalXp,gems", timeout=3)
            if resp.status_code != 200:
                await interaction.followup.send("❌ Token không hợp lệ.")
                return
            info = resp.json()

        if uid in user_sessions.get(str(interaction.user.id), {}).get("accounts", {}):
            await interaction.followup.send(f"ℹ️ **{info.get('username')}** đã có.")
            return
        add_account(str(interaction.user.id), token, uid, info)
        embed = discord.Embed(title="✅ Đã thêm tài khoản", color=discord.Color.green())
        embed.add_field(name="Tài khoản", value=f"{info.get('name')} (@{info.get('username')})", inline=False)
        embed.add_field(name="🔥 Streak", value=f"{info.get('streak', 0):,} ngày", inline=True)
        embed.add_field(name="⚡ XP", value=f"{info.get('totalXp', 0):,}", inline=True)
        embed.add_field(name="💎 Gems", value=f"{info.get('gems', 0):,}", inline=True)
        embed.set_footer(text="Hybrid Bot")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Lỗi: {e}")

@bot.tree.command(name="acc", description="📊 Xem thông tin tài khoản")
async def acc(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return
    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return
    import requests as req
    with req.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        uid = get_user_id_from_token(token)
        try:
            resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=username,totalXp,gems,streak,level,league", timeout=3)
            if resp.status_code != 200:
                await interaction.followup.send("❌ Không lấy được thông tin.")
                return
            info = resp.json()
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}")
            return

    role = get_role(interaction.user.id)
    embed = discord.Embed(title=f"📊 {info.get('username')}", color=discord.Color.blue())
    embed.add_field(name="XP", value=f"{info.get('totalXp', 0):,}", inline=True)
    embed.add_field(name="Gems", value=f"{info.get('gems', 0):,}", inline=True)
    embed.add_field(name="Streak", value=f"{info.get('streak', 0):,} ngày", inline=True)
    embed.add_field(name="Level", value=info.get('level', 0), inline=True)
    embed.add_field(name="League", value=info.get('league', 'N/A'), inline=True)
    embed.add_field(name="🏅 Cấp bậc", value=role, inline=True)
    embed.set_footer(text="Hybrid Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="scan", description="🔍 Quét thông tin chi tiết")
async def scan(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    import requests as req
    with req.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        uid = get_user_id_from_token(token)
        try:
            resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=id,username,name,joinedDate,streak,totalXp,gems,league,level,learningLanguage,fromLanguage", timeout=3)
            if resp.status_code != 200:
                await interaction.followup.send("❌ Không lấy được thông tin.")
                return
            info = resp.json()
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}")
            return

    embed = discord.Embed(title=f"🔍 SCAN: {info.get('username')}", color=discord.Color.teal())
    embed.add_field(name="🆔 ID", value=uid, inline=False)
    embed.add_field(name="👤 Tên", value=info.get('name', 'N/A'), inline=True)
    embed.add_field(name="📅 Ngày tham gia", value=info.get('joinedDate', 'N/A'), inline=True)
    embed.add_field(name="🔥 Streak", value=f"{info.get('streak', 0):,} ngày", inline=True)
    embed.add_field(name="⚡ XP", value=f"{info.get('totalXp', 0):,}", inline=True)
    embed.add_field(name="💎 Gems", value=f"{info.get('gems', 0):,}", inline=True)
    embed.add_field(name="🏆 League", value=info.get('league', 'N/A'), inline=True)
    embed.add_field(name="📊 Level", value=info.get('level', 0), inline=True)
    embed.add_field(name="🌍 Học ngôn ngữ", value=info.get('learningLanguage', 'N/A'), inline=True)
    embed.add_field(name="🌐 Ngôn ngữ gốc", value=info.get('fromLanguage', 'N/A'), inline=True)
    embed.set_footer(text="Hybrid Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="bxh", description="🏆 Xem bảng xếp hạng")
async def bxh(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập.")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    import requests as req
    with req.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        uid = get_user_id_from_token(token)
        lb_url = f"{LEADERBOARD_API}/leaderboards/7d9f5dd1-8423-491a-91f2-2532052038ce/users/{uid}?client_unlocked=true&get_reactions=true"
        try:
            res = session.get(lb_url, timeout=3)
            if res.status_code != 200:
                await interaction.followup.send("❌ Không lấy được bảng xếp hạng.")
                return
            raw_data = res.json()
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}")
            return

    data = raw_data[0] if isinstance(raw_data, list) else raw_data
    if data.get("active"):
        data = data["active"]
    if not data or not data.get("cohort") or not data.get("contest"):
        await interaction.followup.send("❌ Không có dữ liệu.")
        return

    cohort = data.get("cohort", {})
    rankings = cohort.get("rankings", [])
    tier = cohort.get("tier", 0)
    contest = data.get("contest", {})
    ruleset = contest.get("ruleset", {})
    num_promoted = ruleset.get("num_promoted", [])
    num_demoted = ruleset.get("num_demoted", [])
    n_prom = num_promoted[tier] if tier < len(num_promoted) else 0
    n_dem = num_demoted[tier] if tier < len(num_demoted) else 0
    my_rank = None
    my_score = 0
    for idx, user in enumerate(rankings):
        if str(user.get("user_id")) == uid:
            my_rank = idx + 1
            my_score = user.get("score", 0)
            break
    league_names = ["Bronze", "Silver", "Gold", "Sapphire", "Ruby", "Emerald", "Amethyst", "Pearl", "Obsidian", "Diamond"]
    league_name = league_names[tier] if tier < len(league_names) else f"League {tier+1}"
    embed = discord.Embed(title=f"🏆 Bảng xếp hạng - {league_name}", color=discord.Color.gold())
    if my_rank:
        embed.add_field(name="🔹 Vị trí của bạn", value=f"#{my_rank} với {my_score:,} XP", inline=False)
    else:
        embed.add_field(name="🔹 Bạn chưa có trong bảng xếp hạng", value="", inline=False)
    top_10 = rankings[:10]
    desc = ""
    for idx, user in enumerate(top_10, 1):
        name = user.get("display_name", "Unknown")
        score = user.get("score", 0)
        is_me = str(user.get("user_id")) == uid
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        desc += f"{medal} **{name}** {'' if not is_me else '👈'} – {score:,} XP\n"
    if desc:
        embed.add_field(name="📊 Top 10", value=desc, inline=False)
    if n_prom > 0:
        embed.add_field(name="⬆ Thăng hạng", value=f"{n_prom} người đầu tiên", inline=True)
    if n_dem > 0:
        embed.add_field(name="⬇ Xuống hạng", value=f"{n_dem} người cuối cùng", inline=True)
    embed.set_footer(text="Hybrid Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="freemax", description="🌟 Kích hoạt Duolingo Max miễn phí")
async def freemax(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except:
        await interaction.response.send_message("⚠️ Interaction đã hết hạn.", ephemeral=True)
        return

    acc = get_active_account(str(interaction.user.id))
    if not acc:
        await interaction.followup.send("❌ Chưa đăng nhập!")
        return

    try:
        token = decrypt_token(acc["token_encrypted"])
    except ValueError:
        await interaction.followup.send("❌ Token bị hỏng.")
        return

    embed = discord.Embed(title="🌟 ĐANG KIỂM TRA...", color=discord.Color.blue())
    await interaction.edit_original_response(embed=embed)

    import requests as req
    with req.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        uid = get_user_id_from_token(token)
        
        try:
            resp = session.get(f"{BASE_URL}/{API_VERSION}/users/{uid}?fields=fromLanguage,learningLanguage", timeout=3)
            if resp.status_code != 200:
                await interaction.followup.send("❌ Không lấy được thông tin user.")
                return
            info = resp.json()
            
            payload = {
                "itemName": "immersive_subscription",
                "isFree": True,
                "consumed": True,
                "fromLanguage": info.get("fromLanguage", "vi"),
                "learningLanguage": info.get("learningLanguage", "en"),
                "productId": "com.duolingo.immersive_free_trial_subscription"
            }
            resp = session.post(
                f"{BASE_URL}/{API_VERSION}/users/{uid}/shop-items",
                json=payload,
                timeout=5
            )
            
            if resp.status_code in [200, 201]:
                embed = discord.Embed(
                    title="🌟 Duolingo Max đã được kích hoạt!",
                    description="Hãy làm mới trang để cập nhật.",
                    color=discord.Color.green()
                )
            elif resp.status_code == 400:
                embed = discord.Embed(
                    title="❌ Không thể kích hoạt",
                    description="Bạn đã có Duolingo Max hoặc không thể kích hoạt thêm.",
                    color=discord.Color.red()
                )
            else:
                embed = discord.Embed(
                    title="❌ Lỗi",
                    description=f"Status code: {resp.status_code}",
                    color=discord.Color.red()
                )
        except Exception as e:
            embed = discord.Embed(
                title="❌ Lỗi",
                description=str(e),
                color=discord.Color.red()
            )
    
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)

@bot.tree.command(name="proxy", description="🌐 Xem trạng thái proxy")
async def proxy_status(interaction: discord.Interaction):
    await interaction.response.defer()
    
    embed = discord.Embed(
        title="🌐 PROXY STATUS",
        color=discord.Color.blue()
    )
    
    proxies = proxy_manager.working_proxies
    failed = len(proxy_manager.failed_proxies)
    total = len(proxies) + failed
    
    embed.add_field(
        name="📊 Tổng proxy",
        value=f"✅ Hoạt động: {len(proxies)}\n❌ Đã fail: {failed}\n📦 Tổng: {total}",
        inline=False
    )
    
    if proxies:
        proxy_list = ""
        for i, p in enumerate(proxies[:10]):
            speed = proxy_manager.proxy_speeds.get(p, 0)
            proxy_list += f"• {p} - {speed:.2f}s\n"
        if len(proxies) > 10:
            proxy_list += f"\n... và {len(proxies)-10} proxy khác"
        embed.add_field(
            name="🌐 Proxy đang dùng (rotate 10s)",
            value=proxy_list,
            inline=False
        )
    else:
        embed.add_field(
            name="⚠️ Không có proxy",
            value="Đang cào proxy...",
            inline=False
        )
    
    embed.set_footer(text="Hybrid Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="proxyreset", description="🔄 Reset và cào proxy mới")
async def proxy_reset(interaction: discord.Interaction):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được reset proxy!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    proxy_manager.working_proxies = []
    proxy_manager.failed_proxies = set()
    proxy_manager.proxy_speeds = {}
    proxy_manager.last_update = 0
    
    await proxy_manager.update_proxies(force=True)
    
    embed = discord.Embed(
        title="🔄 PROXY RESET",
        description=f"Đã tìm thấy {len(proxy_manager.working_proxies)} proxy hoạt động (dưới 1.5s)",
        color=discord.Color.green()
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="addproxy", description="🌐 Thêm proxy mới và tự động test (chỉ nhận <1.5s)")
@app_commands.describe(proxy="Proxy cần thêm (ví dụ: 1.2.3.4:8080 hoặc http://1.2.3.4:8080)")
async def add_proxy(interaction: discord.Interaction, proxy: str):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được thêm proxy!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    result = await proxy_manager.add_proxy(proxy)
    
    if result["success"]:
        embed = discord.Embed(
            title="✅ Đã thêm proxy thành công!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📊 Kết quả",
            value=result["message"],
            inline=False
        )
        if result.get("speeds"):
            speeds_text = "\n".join([f"• {p} - {s:.2f}s" for p, s in result["speeds"].items()])
            embed.add_field(name="🚀 Tốc độ", value=speeds_text, inline=False)
        embed.set_footer(text="Hybrid Bot")
    else:
        embed = discord.Embed(
            title="❌ Thêm proxy thất bại",
            description=result["message"],
            color=discord.Color.red()
        )
        if result.get("results"):
            results_text = "\n".join([f"• {r['proxy']} - {'✅' if r['ok'] else '❌'} ({r['speed']:.2f}s)" for r in result["results"]])
            embed.add_field(name="📊 Kết quả test", value=results_text, inline=False)
        embed.set_footer(text="Hybrid Bot")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="stop", description="🛑 Dừng tất cả task")
async def stop_task(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in user_tasks and user_tasks[user_id]:
        count = len(user_tasks[user_id])
        if user_id in _stop_flags:
            _stop_flags[user_id].set()
        for task in user_tasks[user_id]:
            if not task.done():
                task.cancel()
        await asyncio.sleep(0.5)
        user_tasks[user_id] = []
        await interaction.response.send_message(f"⏹️ Đã dừng **{count}** task!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Không có task nào đang chạy.", ephemeral=True)

@bot.tree.command(name="help", description="📚 Hướng dẫn sử dụng")
async def help_cmd(interaction: discord.Interaction):
    role = get_role(interaction.user.id)
    embed = discord.Embed(
        title="📚 HYBRID BOT",
        color=discord.Color.green()
    )
    embed.add_field(name="🔑 Đăng nhập", value="`/login token:<token>` hoặc `/addacc token:<token>`", inline=False)
    embed.add_field(name="📋 Danh sách tài khoản", value="`/listacc` - Có nút bấm chọn", inline=False)
    embed.add_field(name="🔄 Chọn tài khoản", value="`/switchacc <số thứ tự>`", inline=False)
    embed.add_field(name="🗑️ Xóa tài khoản", value="`/delacc <số thứ tự>`", inline=False)
    embed.add_field(name="⚡ Cày XP", value="`/farmxp xp:<số>` (CRE không giới hạn, User/VIP tối đa 5.000.000)", inline=False)
    embed.add_field(name="💎 Farm Gems", value="`/farmgems gems:<số>` (max 50.000)", inline=False)
    embed.add_field(name="🔥 Buff Streak", value="`/buffstreak count:<số>` (CRE không giới hạn, User/VIP tối đa 10.000)", inline=False)
    embed.add_field(name="📋 Daily Quest", value="`/dailyquest` - Hoàn thành nhiệm vụ ngày", inline=False)
    embed.add_field(name="🎁 Monthly Claim", value="`/monthlyclaim` - Claim nhiệm vụ tháng", inline=False)
    embed.add_field(name="🛒 Shop", value="`/shop`", inline=False)
    embed.add_field(name="🔍 Scan", value="`/scan`", inline=False)
    embed.add_field(name="🏆 Bảng xếp hạng", value="`/bxh`", inline=False)
    embed.add_field(name="🌟 Kích hoạt Max", value="`/freemax`", inline=False)
    embed.add_field(name="🛑 Dừng task", value="`/stop`", inline=False)
    embed.add_field(name="🌐 Proxy", value="`/proxy` - Xem trạng thái proxy", inline=False)
    embed.add_field(name="🌐 Thêm proxy", value="`/addproxy proxy:<proxy>` - Thêm proxy mới (tự test <1.5s)", inline=False)
    
    limits = get_user_limits(interaction.user.id)
    embed.add_field(
        name="⚙️ GIỚI HẠN",
        value=f"**Task:** {limits['max_tasks']} cùng lúc\n**Concurrency:** {limits['concurrency']} luồng\n**XP:** {limits['xp_limit']:,}/ngày\n**Gems:** {limits['gems_limit']:,}/5h\n**Streak:** {limits['streak_limit']}/giờ",
        inline=False
    )
    
    if role == "CRE":
        embed.add_field(
            name="👑 QUẢN LÝ (CHỈ CRE)",
            value="`/creadd` - Thêm CRE\n`/crelist` - DS CRE\n`/credel` - Xóa CRE\n`/vipadd` - Thêm VIP\n`/viplist` - DS VIP\n`/vipdel` - Xóa VIP\n`/sync` - Đồng bộ lệnh\n`/proxyreset` - Reset proxy\n`/addproxy` - Thêm proxy",
            inline=False
        )
    
    embed.set_footer(text="Hybrid Bot")
    await interaction.response.send_message(embed=embed)

# ================== LỆNH QUẢN LÝ CRE/VIP ==================
@bot.tree.command(name="creadd", description="👑 Thêm CRE (CHỈ CRE)")
@app_commands.describe(user_id="ID Discord của user muốn thêm làm CRE")
async def creadd(interaction: discord.Interaction, user_id: str):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được thêm CRE!", ephemeral=True)
        return
    try:
        uid = int(user_id)
        if uid in CRE_IDS:
            await interaction.response.send_message(f"ℹ️ User <@{uid}> đã là CRE!", ephemeral=True)
            return
        CRE_IDS.add(uid)
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_cre = f"CRE_IDS={','.join(str(id) for id in CRE_IDS)}\n"
            found = False
            for i, line in enumerate(lines):
                if line.startswith("CRE_IDS="):
                    lines[i] = new_cre
                    found = True
                    break
            if not found:
                lines.append(new_cre)
            with open(env_path, "w") as f:
                f.writelines(lines)
        await interaction.response.send_message(f"✅ Đã thêm <@{uid}> vào danh sách CRE!", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ ID user không hợp lệ!", ephemeral=True)

@bot.tree.command(name="crelist", description="👑 Danh sách CRE (CHỈ CRE)")
async def crelist(interaction: discord.Interaction):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới xem được!", ephemeral=True)
        return
    if not CRE_IDS:
        await interaction.response.send_message("📋 Chưa có CRE nào.", ephemeral=True)
        return
    embed = discord.Embed(title="👑 DANH SÁCH CRE", color=discord.Color.gold())
    for uid in CRE_IDS:
        embed.add_field(name=f"<@{uid}>", value=f"ID: `{uid}`", inline=False)
    embed.set_footer(text="Hybrid Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="credel", description="🗑️ Xóa CRE (CHỈ CRE)")
@app_commands.describe(user_id="ID Discord của CRE muốn xóa")
async def credel(interaction: discord.Interaction, user_id: str):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được xóa CRE!", ephemeral=True)
        return
    try:
        uid = int(user_id)
        if uid not in CRE_IDS:
            await interaction.response.send_message(f"ℹ️ User <@{uid}> không phải là CRE!", ephemeral=True)
            return
        CRE_IDS.remove(uid)
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_cre = f"CRE_IDS={','.join(str(id) for id in CRE_IDS)}\n"
            for i, line in enumerate(lines):
                if line.startswith("CRE_IDS="):
                    lines[i] = new_cre
                    break
            with open(env_path, "w") as f:
                f.writelines(lines)
        await interaction.response.send_message(f"✅ Đã xóa <@{uid}> khỏi danh sách CRE!", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ ID user không hợp lệ!", ephemeral=True)

@bot.tree.command(name="vipadd", description="👑 Thêm VIP (CHỈ CRE)")
@app_commands.describe(user_id="ID Discord của user muốn thêm làm VIP")
async def vipadd(interaction: discord.Interaction, user_id: str):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được thêm VIP!", ephemeral=True)
        return
    try:
        uid = int(user_id)
        if uid in VIP_IDS:
            await interaction.response.send_message(f"ℹ️ User <@{uid}> đã là VIP!", ephemeral=True)
            return
        VIP_IDS.add(uid)
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_vip = f"VIP_IDS={','.join(str(id) for id in VIP_IDS)}\n"
            found = False
            for i, line in enumerate(lines):
                if line.startswith("VIP_IDS="):
                    lines[i] = new_vip
                    found = True
                    break
            if not found:
                lines.append(new_vip)
            with open(env_path, "w") as f:
                f.writelines(lines)
        await interaction.response.send_message(f"✅ Đã thêm <@{uid}> vào danh sách VIP!", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ ID user không hợp lệ!", ephemeral=True)

@bot.tree.command(name="viplist", description="👑 Danh sách VIP (CHỈ CRE)")
async def viplist(interaction: discord.Interaction):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới xem được!", ephemeral=True)
        return
    if not VIP_IDS:
        await interaction.response.send_message("📋 Chưa có VIP nào.", ephemeral=True)
        return
    embed = discord.Embed(title="👑 DANH SÁCH VIP", color=discord.Color.gold())
    for uid in VIP_IDS:
        embed.add_field(name=f"<@{uid}>", value=f"ID: `{uid}`", inline=False)
    embed.set_footer(text="Hybrid Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vipdel", description="🗑️ Xóa VIP (CHỈ CRE)")
@app_commands.describe(user_id="ID Discord của VIP muốn xóa")
async def vipdel(interaction: discord.Interaction, user_id: str):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Chỉ CRE mới được xóa VIP!", ephemeral=True)
        return
    try:
        uid = int(user_id)
        if uid not in VIP_IDS:
            await interaction.response.send_message(f"ℹ️ User <@{uid}> không phải là VIP!", ephemeral=True)
            return
        VIP_IDS.remove(uid)
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            new_vip = f"VIP_IDS={','.join(str(id) for id in VIP_IDS)}\n"
            for i, line in enumerate(lines):
                if line.startswith("VIP_IDS="):
                    lines[i] = new_vip
                    break
            with open(env_path, "w") as f:
                f.writelines(lines)
        await interaction.response.send_message(f"✅ Đã xóa <@{uid}> khỏi danh sách VIP!", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ ID user không hợp lệ!", ephemeral=True)

@bot.tree.command(name="sync", description="🔄 Đồng bộ lệnh slash (CHỈ CRE)")
@app_commands.describe(guild_id="ID server để sync (để trống sync toàn cầu)")
async def sync_commands(interaction: discord.Interaction, guild_id: str = None):
    if not is_cre(interaction.user.id):
        await interaction.response.send_message("❌ Bạn không có quyền! Chỉ CRE mới được dùng lệnh này.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        if guild_id:
            try:
                guild = discord.Object(int(guild_id))
                synced = await bot.tree.sync(guild=guild)
                await interaction.followup.send(
                    f"✅ [CRE] Đã đồng bộ {len(synced)} lệnh vào server `{guild_id}`!",
                    ephemeral=True
                )
            except ValueError:
                await interaction.followup.send(
                    "❌ ID server không hợp lệ! Vui lòng nhập đúng ID số.",
                    ephemeral=True
                )
        else:
            synced = await bot.tree.sync()
            await interaction.followup.send(
                f"✅ [CRE] Đã đồng bộ {len(synced)} lệnh toàn cầu!",
                ephemeral=True
            )
    except discord.errors.NotFound:
        await interaction.followup.send(
            "⚠️ Interaction hết hạn nhưng lệnh sync đã được xử lý!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Lỗi sync: {str(e)}",
            ephemeral=True
        )

# ================== HÀM FARM (cập nhật realtime) ==================
async def farm_xp_hybrid(interaction: discord.Interaction, token: str, target_xp: int, user_id_int: int):
    user_id = str(interaction.user.id)
    role = get_role(user_id_int)
    
    update_progress('xp', 0, target_xp, 0, 0, 'running')
    stop_event = asyncio.Event()
    updater_task = asyncio.create_task(progress_updater(interaction, stop_event))
    
    start = time.time()
    duo = AsyncDuolingo(token, concurrency=get_user_limits(user_id_int)["concurrency"], sleep=get_user_limits(user_id_int)["sleep"])
    
    def progress_callback(done, total, elapsed):
        speed = done / elapsed if elapsed > 0 else 0
        update_progress('xp', done, total, speed, elapsed, 'running')
    
    gained, elapsed, speed = await duo.farm_xp(target_xp, progress_callback)
    
    stop_event.set()
    await updater_task
    
    embed = discord.Embed(
        title="🎉 CÀY XP HOÀN TẤT!" if gained > 0 else "⚠️ Không có XP",
        color=discord.Color.green() if gained > 0 else discord.Color.red()
    )
    embed.description = (
        f"⚡ **+{gained:,} XP**\n"
        f"⏱️ **{elapsed:.1f}s** | 🚀 **{speed:.1f} XP/s**\n"
        f"🏅 **{role}**"
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)
    
    if user_id in user_tasks:
        user_tasks[user_id] = [t for t in user_tasks[user_id] if t is not asyncio.current_task()]

def _farm_gems_sync(token: str, target_gems: int, stop_event: threading.Event, progress_callback=None) -> int:
    duo = CurlDuolingo(token)
    duo.set_stop_event(stop_event)
    try:
        gained = duo.farm_gems(target_gems, progress_callback)
        return gained
    except Exception as e:
        logger.error(f"❌ Lỗi farm gems sync: {e}")
        return 0

async def farm_gems_hybrid(interaction: discord.Interaction, token: str, target_gems: int):
    user_id = str(interaction.user.id)
    role = get_role(interaction.user.id)
    
    update_progress('gems', 0, target_gems, 0, 0, 'running')
    stop_event = asyncio.Event()
    updater_task = asyncio.create_task(progress_updater(interaction, stop_event))
    
    start = time.time()
    loop = asyncio.get_running_loop()
    
    thread_stop = threading.Event()
    _stop_flags[user_id] = thread_stop
    
    def progress_callback(done, total):
        elapsed = time.time() - start
        speed = done / elapsed if elapsed > 0 else 0
        update_progress('gems', done, total, speed, elapsed, 'running')
    
    try:
        gained = await loop.run_in_executor(
            shared_executor,
            _farm_gems_sync,
            token,
            target_gems,
            thread_stop,
            progress_callback
        )
    except Exception as e:
        logger.error(f"Lỗi farm gems: {e}")
        gained = 0
    finally:
        if user_id in _stop_flags:
            del _stop_flags[user_id]
    
    elapsed = time.time() - start
    speed = gained / elapsed if elapsed > 0 else 0
    
    stop_event.set()
    await updater_task
    
    embed = discord.Embed(
        title="🎉 FARM GEMS HOÀN TẤT!" if gained > 0 else "⚠️ Không tăng gems",
        color=discord.Color.purple() if gained > 0 else discord.Color.red()
    )
    embed.description = (
        f"💎 **+{gained:,} gems**\n"
        f"⏱️ **{elapsed:.1f}s** | 🚀 **{speed:.1f} gems/s**\n"
        f"🏅 **{role}**"
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)
    
    if user_id in user_tasks:
        user_tasks[user_id] = [t for t in user_tasks[user_id] if t is not asyncio.current_task()]

def _buff_streak_sync(token: str, target_days: int, stop_event: threading.Event, progress_callback=None) -> int:
    duo = CurlDuolingo(token)
    duo.set_stop_event(stop_event)
    try:
        gained = duo.buff_streak(target_days, progress_callback)
        return gained
    except Exception as e:
        logger.error(f"❌ Lỗi buff streak sync: {e}")
        return 0

async def buff_streak_hybrid(interaction: discord.Interaction, token: str, target_count: int, user_id_int: int):
    user_id = str(interaction.user.id)
    role = get_role(user_id_int)
    
    update_progress('streak', 0, target_count, 0, 0, 'running')
    stop_event = asyncio.Event()
    updater_task = asyncio.create_task(progress_updater(interaction, stop_event))
    
    start = time.time()
    loop = asyncio.get_running_loop()
    
    thread_stop = threading.Event()
    _stop_flags[user_id] = thread_stop
    
    def progress_callback(done, total):
        elapsed = time.time() - start
        speed = done / elapsed if elapsed > 0 else 0
        update_progress('streak', done, total, speed, elapsed, 'running')
    
    try:
        total_gained = await loop.run_in_executor(
            shared_executor,
            _buff_streak_sync,
            token,
            target_count,
            thread_stop,
            progress_callback
        )
    except Exception as e:
        logger.error(f"Lỗi buff streak: {e}")
        total_gained = 0
    finally:
        if user_id in _stop_flags:
            del _stop_flags[user_id]
    
    elapsed = time.time() - start
    speed = total_gained / elapsed if elapsed > 0 else 0
    
    stop_event.set()
    await updater_task
    
    embed = discord.Embed(
        title=f"🔥 BUFF STREAK HOÀN TẤT! +{total_gained} ngày",
        color=discord.Color.green() if total_gained > 0 else discord.Color.red()
    )
    embed.description = (
        f"✅ **Đã buff:** +{total_gained}/{target_count} ngày\n"
        f"⏱️ **{elapsed:.1f}s** | 🚀 **{speed:.2f} ngày/s**\n"
        f"🏅 **{role}**"
    )
    embed.set_footer(text="Hybrid Bot")
    await interaction.edit_original_response(embed=embed)
    
    if user_id in user_tasks:
        user_tasks[user_id] = [t for t in user_tasks[user_id] if t is not asyncio.current_task()]

# ================== ON_READY ==================
@bot.event
async def on_ready():
    print(f'✅ Bot đã đăng nhập: {bot.user}')
    print(f'👑 CRE IDs: {CRE_IDS}')
    print(f'⭐ VIP IDs: {VIP_IDS}')
    print(f'🌐 Proxy manager đã sẵn sàng')
    print(f'🖥️ Selenium driver sẽ được khởi tạo khi cần')
    
    try:
        await proxy_manager.update_proxies(force=True)
        print(f"✅ Đã cào {len(proxy_manager.working_proxies)} proxy hoạt động (dưới 1.5s)")
    except:
        pass
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Đã đồng bộ {len(synced)} lệnh")
    except Exception as e:
        print(f"⚠️ Lỗi sync: {e}")

# ================== CHẠY BOT ==================
if __name__ == "__main__":
    # Tăng pool size cho curl_cffi và aiohttp
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=3, backoff_factor=0.1))
        session.mount('http://', adapter)
        session.mount('https://', adapter)
    except:
        pass

    BOT_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️ Điền token bot Discord!")
        print("   export DISCORD_TOKEN=your_token")
        print("   Hoặc tạo file .env:")
        print('   DISCORD_TOKEN=your_token_here')
        print('   CRE_IDS=123456789')
        print('   VIP_IDS=111111111')
    else:
        try:
            asyncio.run(proxy_manager.update_proxies(force=True))
        except:
            pass
        bot.run(BOT_TOKEN)