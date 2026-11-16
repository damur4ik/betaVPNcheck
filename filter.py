import base64
import re
import os
import json
import socket
import requests
import time
from urllib.parse import unquote_plus, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# === НАСТРОЙКИ ===
SOURCE_URL = os.environ.get("SOURCE_URL")
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

FILTER_WORD = "poland"
OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
TIMEOUT = 3        # Таймаут подключения к серверу (в секундах)
MAX_WORKERS = 10   # Количество параллельных проверок
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()

def check_tcp_connection(host: str, port: int, timeout: int):
    """Пытается установить TCP-соединение. Возвращает пинг в мс или None, если сервер мертв."""
    if not host or not port:
        return None
    try:
        start_time = time.time()
        with socket.create_connection((host, int(port)), timeout=timeout):
            end_time = time.time()
            # Переводим секунды в миллисекунды и округляем
            ping_ms = int((end_time - start_time) * 1000)
            return ping_ms
    except (socket.timeout, ConnectionRefusedError, OSError):
        return None

def get_host_port_from_json(item):
    try:
        outbounds = item.get("outbounds", [])
        for ob in outbounds:
            protocol = ob.get("protocol", "")
            if protocol in ["vless", "vmess", "trojan", "shadowsocks"]:
                settings = ob.get("settings", {})
                if "vnext" in settings and settings["vnext"]:
                    return settings["vnext"][0].get("address"), settings["vnext"][0].get("port")
                if "servers" in settings and settings["servers"]:
                    return settings["servers"][0].get("address"), settings["servers"][0].get("port")
    except Exception:
        pass
    return None, None

def get_host_port_from_uri(uri):
    try:
        if uri.startswith("vmess://"):
            b64 = uri.replace("vmess://", "").split("#")[0]
            b64 += "=" * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode("utf-8"))
            return data.get("add"), data.get("port")
        elif "://" in uri:
            parsed = urlparse(uri)
            return parsed.hostname, parsed.port
    except Exception:
        pass
    return None, None

def main():
    print("[1/4] Загрузка подписки...")
    try:
        raw = fetch_raw_sub(SOURCE_URL)
    except Exception as e:
        print(f"  Ошибка при скачивании: {e}")
        return

    print(f"[2/4] Поиск серверов по слову '{FILTER_WORD}'...")
    matched_items = []  # Храним кортежи: (type, data, host, port, name)
    
    # 1. JSON формат
    if raw.startswith("[") and raw.endswith("]"):
        print("  [DEBUG] Формат подписки: JSON массив (Xray)")
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                if FILTER_WORD.lower() in remarks.lower():
                    host, port = get_host_port_from_json(item)
                    matched_items.append(("json", item, host, port, remarks))
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] Ошибка парсинга JSON: {e}")

    # 2. Base64 / URI формат
    else:
        print("  [DEBUG] Формат подписки: Base64 или сырые URI")
        try:
            missing_padding = len(raw) % 4
            if missing_padding:
                raw_padded = raw + '=' * (4 - missing_padding)
            else:
                raw_padded = raw
            decoded = base64.b64decode(raw_padded).decode("utf-8", errors="ignore")
            if "://" in decoded:
                raw = decoded
        except Exception:
            pass

        pattern = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?)://[^\s<>"]+'
        uris = re.findall(pattern, raw, flags=re.IGNORECASE)
        
        for uri in uris:
            if "#" in uri:
                tag = unquote_plus(uri.split("#", 1)[1])
                if FILTER_WORD.lower() in tag.lower():
                    host, port = get_host_port_from_uri(uri)
                    matched_items.append(("uri", uri, host, port, tag))

    print(f"  Найдено по названию: {len(matched_items)}")
    if not matched_items:
        print("  Нет серверов с таким названием. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return

    print(f"[3/4] Проверка доступности и замер пинга (таймаут {TIMEOUT} сек)...")
    
    alive_items = [] # Сюда складываем: (ping_ms, type, data, host, port, name)
    
    # Запускаем проверки параллельно
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(check_tcp_connection, item[2], item[3], TIMEOUT): item 
            for item in matched_items
        }
        
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            item_type, data, host, port, name = item
            ping = future.result()  # Получаем пинг (или None)
            
            if ping is not None:
                print(f"  ✅ ЖИВ (ping: {ping} ms): {name[:40]} ({host}:{port})")
                alive_items.append((ping, item_type, data, host, port, name))
            else:
                print(f"  ❌ МЕРТВ: {name[:40]} ({host}:{port})")

    print(f"[4/4] Сортировка и сохранение...")
    
    # СОРТИРОВКА: сортируем по первому элементу кортежа (по пингу) по возрастанию
    alive_items.sort(key=lambda x: x[0])
    
    alive_json = []
    alive_uri = []
    
    # Разделяем обратно на JSON и URI после сортировки
    print("\n--- ТОП-5 САМЫХ БЫСТРЫХ СЕРВЕРОВ ---")
    for i, (ping, item_type, data, host, port, name) in enumerate(alive_items):
        if i < 5:
            print(f"  {i+1}. {name[:30]} | {ping} ms")
            
        if item_type == "json":
            alive_json.append(data)
        else:
            alive_uri.append(data)
            
    total_alive = len(alive_json) + len(alive_uri)
    print(f"\n  Всего рабочих серверов: {total_alive} из {len(matched_items)}")

    if alive_json:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(alive_json, f, ensure_ascii=False, indent=2)
        print(f"  Сохранено JSON серверов: {len(alive_json)}")
    elif alive_uri:
        content = "\n".join(alive_uri)
        b64 = base64.b64encode(content.encode()).decode()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(b64)
        print(f"  Сохранено URI серверов: {len(alive_uri)}")
    else:
        print("  Все найденные серверы оказались нерабочими. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")

if __name__ == "__main__":
    main()
