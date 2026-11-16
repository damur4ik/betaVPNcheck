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

FILTER_WORD = "poland"
OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
TIMEOUT = 5  # Время на проверку сервера (секунды)
MAX_WORKERS = 5  # Количество одновременных проверок
XRAY_PATH = "./xray_bin/xray"  # Путь к ядру Xray
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()

def real_ping(item_json, index):
    """Запускает Xray, делает запрос через прокси и возвращает реальный пинг."""
    port = 10000 + index
    # Создаем временный конфиг для Xray
    temp_config = {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks"}],
        "outbounds": item_json.get("outbounds", [])
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(temp_config, f)
        temp_path = f.name

    try:
        # Запускаем Xray
        proc = subprocess.Popen([XRAY_PATH, "run", "-c", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Ждем, пока локальный порт откроется (макс 2 сек)
        start_wait = time.time()
        while time.time() - start_wait < 2:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            proc.terminate()
            return None  # Xray не запустился

        # Делаем реальный запрос через прокси
        proxies = {
            'http': f'socks5h://127.0.0.1:{port}',
            'https': f'socks5h://127.0.0.1:{port}'
        }
        
        start_ping = time.time()
        try:
            # Запрашиваем страницу генерации 204 (быстрый ответ)
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

    print(f"[2/4] Поиск серверов по слову '{FILTER_WORD}'...")
    matched_items = []
    
    if raw.startswith("[") and raw.endswith("]"):
        print("  [DEBUG] Формат подписки: JSON массив (Xray)")
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                if FILTER_WORD.lower() in remarks.lower():
                    matched_items.append(item)
        except json.JSONDecodeError:
            pass

    print(f"  Найдено по названию: {len(matched_items)}")
    if not matched_items:
        print("  Нет серверов с таким названием. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return

    print(f"[3/4] РЕАЛЬНАЯ проверка через Xray (таймаут {TIMEOUT} сек)...")
    alive_items = [] # (ping_ms, item_json, remarks)
    
    # Запускаем проверки параллельно
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
                alive_items.append((ping, item, remarks))
            else:
                print(f"  ❌ НЕ РАБОТАЕТ: {remarks}")

    print(f"[4/4] Сортировка и сохранение...")
    # Сортируем по реальному пингу
    alive_items.sort(key=lambda x: x[0])
    
    print("\n--- РЕЙТИНГ САМЫХ БЫСТРЫХ РАБОЧИХ СЕРВЕРОВ ---")
    for i, (ping, item, remarks) in enumerate(alive_items):
        print(f"  {i+1}. {remarks[:35]} | {ping} ms")

    alive_json = [item for ping, item, remarks in alive_items]

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
