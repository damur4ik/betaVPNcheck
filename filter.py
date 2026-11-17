import base64
import re
import os
import json
import socket
import requests
import time
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

# === НАСТРОЙКИ ===
SOURCE_URL = os.environ.get("SOURCE_URL")
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

# Токен для IPinfo (получить бесплатно на ipinfo.io)
IPINFO_TOKEN = os.environ.get("IPINFO_TOKEN", "") 

FILTER_WORDS = [
    "poland", "germany", "finland", "sweden", "lithuania", 
    "norway", "estonia", "belarus", "kazakhstan", "uzbekistan", 
    "israel", "azerbaijan", "ukraine", "russia"
]

OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
TIMEOUT = 5
MAX_WORKERS = 5
XRAY_PATH = "./xray_bin/xray"

TIER1_COUNTRIES = ["PL", "FI", "DE", "SE", "LT", "NO", "EE"]
TIER3_COUNTRIES = ["BY", "KZ", "UZ", "IL", "AZ", "UA"]

FALLBACK_COUNTRIES = {
    "poland": ("PL", "🇵🇱"), "germany": ("DE", "🇩🇪"), "finland": ("FI", "🇫🇮"),
    "sweden": ("SE", "🇸🇪"), "lithuania": ("LT", "🇱🇹"), "norway": ("NO", "🇳🇴"),
    "estonia": ("EE", "🇪🇪"), "belarus": ("BY", "🇧🇾"), "kazakhstan": ("KZ", "🇰🇿"),
    "uzbekistan": ("UZ", "🇺🇿"), "israel": ("IL", "🇮🇱"), "azerbaijan": ("AZ", "🇦🇿"),
    "ukraine": ("UA", "🇺🇦"), "russia": ("RU", "🇷🇺"), "usa": ("US", "🇺🇸"),
}
# =================

# ... (функции fetch_raw_sub, get_protocol_and_transport, get_server_address, country_code_to_flag остаются без изменений) ...

def get_country_getmyip(ip):
    """Определяет страну через getmyip.pro (без ключа, 10k запросов/день)."""
    try:
        r = requests.get(f"https://getmyip.pro/{ip}?format=json", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("country_code")
    except Exception:
        pass
    return None

def get_country_ipinfo(ip, token):
    """Определяет страну через IPinfo (требуется бесплатный токен)."""
    if not token:
        return None
    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json?token={token}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("country")
    except Exception:
        pass
    return None

def get_country_info(ip, default_word):
    """Определяет страну с помощью нескольких источников для надежности."""
    default_code, default_flag = FALLBACK_COUNTRIES.get(default_word.lower(), ("XX", "🏴‍☠️"))
    
    if not ip:
        return default_code, default_flag

    # Пытаемся использовать надежные источники
    code = get_country_getmyip(ip)
    if not code:
        code = get_country_ipinfo(ip, IPINFO_TOKEN)
    
    if code:
        return code, country_code_to_flag(code)
    
    # Если ничего не сработало, возвращаем страну по умолчанию
    return default_code, default_flag

# ... (функция real_ping остается без изменений) ...

def main():
    # ... (шаги 1-3 остаются без изменений) ...

    print(f"[4/4] Геолокация, определение приоритетов и сохранение...")
    
    # ... (сбор IP-адресов остается без изменений) ...

    processed_items = []
    for i, (ping, item) in enumerate(alive_items):
        matched_word = item.pop("_matched_word", "poland")
        ip = item_ips[i]
        
        code, flag = get_country_info(ip, matched_word)
        transport = get_protocol_and_transport(item)
        
        # === ЛОГИКА ПРИОРИТЕТОВ ===
        if code in TIER3_COUNTRIES:
            priority = 4
        elif transport == "Hys2":
            priority = 1 if code in TIER1_COUNTRIES else 2
        else:
            priority = 3

        processed_items.append({
            "ping": ping, "item": item, "code": code, 
            "flag": flag, "transport": transport, "priority": priority
        })

    processed_items.sort(key=lambda x: (x["priority"], x["ping"]))
    
    name_counts = {}
    alive_json = []

    print("\n--- ИТОГОВЫЙ СПИСОК В HAPP ---")
    for i, data in enumerate(processed_items):
        base_name = f"{data['flag']} {data['code']} {data['transport']}"
        if base_name not in name_counts:
            name_counts[base_name] = 1
        else:
            name_counts[base_name] += 1
            
        new_remarks = f"{base_name} #{name_counts[base_name]}" if name_counts[base_name] > 1 else base_name
        data["item"]["remarks"] = new_remarks
        alive_json.append(data["item"])
        
        print(f"  [{data['priority']}] {new_remarks:<20} | {data['ping']} ms")

    # ... (сохранение файла остается без изменений) ...

if __name__ == "__main__":
    main()
