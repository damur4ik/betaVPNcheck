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

FILTER_WORDS = ["poland"] 
OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
TIMEOUT = 5
MAX_WORKERS = 5
XRAY_PATH = "./xray_bin/xray"
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()

def get_protocol(item):
    """Определяет протокол сервера."""
    try:
        for ob in item.get("outbounds", []):
            proto = ob.get("protocol", "").lower()
            if proto == "vless": return "VLESS"
            if proto == "vmess": return "VMESS"
            if proto == "trojan": return "TROJAN"
            if proto == "shadowsocks": return "SS"
            if proto in ["hysteria", "hysteria2"]: return "HYS2"
    except Exception:
        pass
    return "VPN"

def get_server_ip(item):
    """Извлекает IP или домен сервера из конфига Xray."""
    try:
        for ob in item.get("outbounds", []):
            settings = ob.get("settings", {})
            if "vnext" in settings and settings["vnext"]:
                return settings["vnext"][0].get("address")
            if "servers" in settings and settings["servers"]:
                return settings["servers"][0].get("address")
    except Exception:
        pass
    return None

def get_country_info(ip):
    """Определяет реальную страну по IP через ip-api.com."""
    if not ip:
        return "XX"
    try:
        # Запрашиваем только код страны
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,countryCode", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                return data.get("countryCode", "XX")
    except Exception:
        pass
    return "XX"

def country_code_to_flag(country_code):
    """Преобразует двухбуквенный код страны (PL) в эмодзи-флаг (🇵🇱)."""
    if not country_code or len(country_code) != 2 or country_code == "XX":
        return "🏴‍☠️"
    try:
        return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)
    except Exception:
        return "🏴‍☠️"

def real_ping(item_json, index):
    """Запускает Xray локально и проверяет реальный пинг через прокси."""
    port = 10000 + index
    temp_config = {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks"}],
        "outbounds": item_json.get("outbounds", [])
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(temp_config, f)
        temp_path = f.name

    try:
        proc = subprocess.Popen([XRAY_PATH, "run", "-c", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        start_wait = time.time()
        while time.time() - start_wait < 2:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            proc.kill()
            return None

        proxies = {
            'http': f'socks5h://127.0.0.1:{port}',
            'https': f'socks5h://127.0.0.1:{port}'
        }
        
        start_ping = time.time()
        try:
            r = requests.get("http://cp.cloudflare.com/generate_204", proxies=proxies, timeout=TIMEOUT)
            if r.status_code == 204:
                ping_ms = int((time.time() - start_ping) * 1000)
                proc.kill()
                return ping_ms
        except Exception:
            pass
            
        proc.kill()
        return None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def main():
    print("[1/4] Загрузка подписки...")
    try:
        raw = fetch_raw_sub(SOURCE_URL)
    except Exception as e:
        print(f"  Ошибка при скачивании: {e}")
        return

    print(f"[2/4] Поиск серверов по странам: {', '.join(FILTER_WORDS)}...")
    matched_items = []
    
    if raw.startswith("[") and raw.endswith("]"):
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                for word in FILTER_WORDS:
                    if word.lower() in remarks.lower():
                        matched_items.append(item)
                        break 
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] Ошибка парсинга JSON: {e}")

    print(f"  Найдено по названию: {len(matched_items)}")
    if not matched_items:
        print("  Нет серверов с такими названиями. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return

    print(f"[3/4] РЕАЛЬНАЯ проверка через Xray (таймаут {TIMEOUT} сек)...")
    alive_items = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(real_ping, item, idx): item 
            for idx, item in enumerate(matched_items)
        }
        
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            remarks = item.get("remarks", "Unknown")
            ping = future.result()
            
            if ping is not None:
                print(f"  ✅ РАБОТАЕТ (пинг: {ping} ms): {remarks}")
                alive_items.append((ping, item))
            else:
                print(f"  ❌ НЕ РАБОТАЕТ: {remarks}")

    print(f"[4/4] Сортировка, переименование и сохранение...")
    alive_items.sort(key=lambda x: x[0])
    
    name_counts = {}
    alive_json = []

    print("\n--- ИТОГОВЫЙ СПИСОК В HAPP ---")
    for i, (ping, item) in enumerate(alive_items):
        ip = get_server_ip(item)
        code = get_country_info(ip)
        
        flag = country_code_to_flag(code)
        protocol = get_protocol(item)
        
        # Формат: Флаг КодСтраны Протокол
        base_name = f"{flag} {code} {protocol}"
        
        if base_name not in name_counts:
            name_counts[base_name] = 1
        else:
            name_counts[base_name] += 1
            
        if name_counts[base_name] > 1:
            new_remarks = f"{base_name} #{name_counts[base_name]}"
        else:
            new_remarks = base_name
            
        item["remarks"] = new_remarks
        alive_json.append(item)
        
        print(f"  {i+1}. {new_remarks:<25} | {ping} ms")

    if alive_json:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(alive_json, f, ensure_ascii=False, indent=2)
        print(f"\n  Сохранено рабочих серверов: {len(alive_json)}")
    else:
        print("\n  Все серверы оказались нерабочими. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")

if __name__ == "__main__":
    main()
