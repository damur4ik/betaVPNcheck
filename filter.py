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

# Страны для поиска
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

# Приоритетные страны (Hys2 из них идет на самый верх)
TIER1_COUNTRIES = ["PL", "FI", "DE", "SE", "LT", "NO", "EE"]
# Страны, которые всегда отправляются в самый низ
TIER3_COUNTRIES = ["BY", "KZ", "UZ", "IL", "AZ", "UA"]

# Словарь, который переводит название страны из подписки в код и флаг
COUNTRY_MAP = {
    "poland": ("PL", "🇵🇱"), "germany": ("DE", "🇩🇪"), "finland": ("FI", "🇫🇮"),
    "sweden": ("SE", "🇸🇪"), "lithuania": ("LT", "🇱🇹"), "norway": ("NO", "🇳🇴"),
    "estonia": ("EE", "🇪🇪"), "belarus": ("BY", "🇧🇾"), "kazakhstan": ("KZ", "🇰🇿"),
    "uzbekistan": ("UZ", "🇺🇿"), "israel": ("IL", "🇮🇱"), "azerbaijan": ("AZ", "🇦🇿"),
    "ukraine": ("UA", "🇺🇦"), "russia": ("RU", "🇷🇺"), "usa": ("US", "🇺🇸"),
}
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()

def get_protocol_and_transport(item):
    """Определяет протокол. Для VLESS вытаскивает транспорт (gRPC, WebSocket и т.д.)."""
    try:
        for ob in item.get("outbounds", []):
            proto = ob.get("protocol", "").lower()
            stream = ob.get("streamSettings", {})
            network = stream.get("network", "tcp").lower()
            
            if proto == "vless":
                if network == "ws": return "WebSocket"
                if network == "grpc": return "gRPC"
                if network == "xhttp": return "xhttp"
                if network == "tcp": return "TCP"
                return network.upper()
            if proto == "vmess": return "VMESS"
            if proto == "trojan": return "TROJAN"
            if proto == "shadowsocks": return "SS"
            if proto in ["hysteria", "hysteria2"]: return "Hys2"
    except Exception:
        pass
    return "VPN"

def real_ping(item_json, index):
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

    print(f"[2/4] Поиск серверов по названиям стран...")
    matched_items = []
    
    if raw.startswith("[") and raw.endswith("]"):
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                for word in FILTER_WORDS:
                    # Ищем слово в названии (например, Poland)
                    if word.lower() in remarks.lower():
                        item["_matched_word"] = word
                        matched_items.append(item)
                        break 
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] Ошибка парсинга JSON: {e}")

    print(f"  Найдено по названию: {len(matched_items)}")
    if not matched_items:
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

    print(f"[4/4] Определение приоритетов и сохранение...")
    
    processed_items = []
    for ping, item in alive_items:
        # Берем страну из названия подписки
        matched_word = item.pop("_matched_word", "poland")
        
        # Получаем код и флаг из нашего словаря
        code, flag = COUNTRY_MAP.get(matched_word.lower(), ("XX", "🏴‍☠️"))
        transport = get_protocol_and_transport(item)
        
        # === ЛОГИКА ПРИОРИТЕТОВ ===
        # 4 - Самый низ (Нежелательные страны)
        # 3 - Обычные протоколы (TCP, gRPC, VMESS и т.д.)
        # 2 - Hys2 из других стран
        # 1 - Самый верх (Hys2 из списка TIER1_COUNTRIES)
        
        if code in TIER3_COUNTRIES:
            priority = 4
        elif transport == "Hys2":
            if code in TIER1_COUNTRIES:
                priority = 1
            else:
                priority = 2
        else:
            priority = 3

        processed_items.append({
            "ping": ping, "item": item, "code": code, 
            "flag": flag, "transport": transport, "priority": priority
        })

    # Сортируем сначала по приоритету (1 -> 2 -> 3 -> 4), затем по пингу
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
            
        if name_counts[base_name] > 1:
            new_remarks = f"{base_name} #{name_counts[base_name]}"
        else:
            new_remarks = base_name
            
        data["item"]["remarks"] = new_remarks
        alive_json.append(data["item"])
        
        print(f"  [{data['priority']}] {i+1}. {new_remarks:<20} | {data['ping']} ms")

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
