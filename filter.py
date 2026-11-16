import base64
import re
import os
import json
import socket
import requests
import time
import subprocess
import tempfile
from urllib.parse import unquote_plus, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# === НАСТРОЙКИ ===
SOURCE_URL = os.environ.get("SOURCE_URL")
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

# Сюда можно добавлять страны в будущем: ["poland", "germany", "netherlands"]
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
    """Определяет протокол сервера и возвращает красивое короткое имя."""
    try:
        for ob in item.get("outbounds", []):
            proto = ob.get("protocol", "").lower()
            if proto in ["vless", "vmess", "trojan", "shadowsocks"]:
                return proto.upper()
            elif proto in ["hysteria", "hysteria2"]:
                return "Hys2"
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
            proc.terminate()
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
                proc.terminate()
                return ping_ms
        except Exception:
            pass
            
        proc.terminate()
        return None
    finally:
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
        print("  [DEBUG] Формат подписки: JSON массив (Xray)")
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                # Проверяем, есть ли в названии хотя бы одна из стран
                for word in FILTER_WORDS:
                    if word.lower() in remarks.lower():
                        # Запоминаем, какая именно страна совпала (для красивого имени)
                        item["_matched_country"] = word.capitalize()
                        matched_items.append(item)
                        break # Если нашли совпадение, переходим к следующему серверу
        except json.JSONDecodeError:
            pass

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
    # 1. Сортируем по пингу (от лучшего к худшему)
    alive_items.sort(key=lambda x: x[0])
    
    # 2. Переименовываем и считаем дубликаты
    name_counts = {}
    alive_json = []

    print("\n--- ИТОГОВЫЙ СПИСОК ---")
    for i, (ping, item) in enumerate(alive_items):
        country = item.pop("_matched_country", "Unknown") # Достаем страну и удаляем служебное поле
        protocol = get_protocol(item)
        
        base_name = f"{country} | {protocol}"
        
        # Считаем, сколько раз встречается такое имя
        if base_name not in name_counts:
            name_counts[base_name] = 1
        else:
            name_counts[base_name] += 1
            
        # Если сервер с таким именем уже есть, добавляем номер
        if name_counts[base_name] > 1:
            new_remarks = f"{base_name} #{name_counts[base_name]}"
        else:
            new_remarks = base_name
            
        # Заменяем старое название на новое
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
