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

# Сюда можно добавлять страны в будущем: ["poland", "germany", "netherlands"]
FILTER_WORDS = ["poland"] 
OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
TIMEOUT = 5            # Таймаут проверки (секунды)
MAX_WORKERS = 5        # Количество параллельных проверок
XRAY_PATH = "./xray_bin/xray"  # Путь к ядру Xray
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
    """Определяет реальную страну и интернет-провайдера (ISP) по IP."""
    if not ip:
        return "XX", "Unknown ISP"
    try:
        # Запрашиваем код страны и провайдера
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,countryCode,isp", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                code = data.get("countryCode", "XX")
                isp = data.get("isp", "Unknown ISP")
                # Сокращаем слишком длинные названия провайдеров
                isp = isp[:20] + "..." if len(isp) > 20 else isp
                return code, isp
    except Exception:
        pass
    return "XX", "Unknown ISP"

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
    # Формируем временный конфиг для локального запуска Xray
    temp_config = {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks"}],
        "outbounds": item_json.get("outbounds", [])
    }
    
    # Создаем временный файл конфигурации
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(temp_config, f)
        temp_path = f.name

    try:
        # Запускаем ядро Xray
        proc = subprocess.Popen([XRAY_PATH, "run", "-c", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Ждем, пока локальный порт откроется (макс 2 секунды)
        start_wait = time.time()
        while time.time() - start_wait < 2:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            proc.kill()
            return None # Порт так и не открылся

        # Делаем реальный запрос через локальный прокси
        proxies = {
            'http': f'socks5h://127.0.0.1:{port}',
            'https': f'socks5h://127.0.0.1:{port}'
        }
        
        start_ping = time.time()
        try:
            # Запрашиваем страницу генерации 204 (быстрый ответ от Cloudflare)
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
        # Удаляем временный конфиг
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
    
    # Парсим JSON подписку
    if raw.startswith("[") and raw.endswith("]"):
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                # Проверяем, есть ли в названии хотя бы одна из стран
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
                alive_items.append((ping, item))
            else:
                print(f"  ❌ НЕ РАБОТАЕТ: {remarks}")

    print(f"[4/4] Сортировка, переименование и сохранение...")
    
    # Сортируем по реальному пингу (от лучшего к худшему)
    alive_items.sort(key=lambda x: x[0])
    
    name_counts = {}
    alive_json = []

    print("\n--- ИТОГОВЫЙ СПИСОК В HAPP ---")
    for i, (ping, item) in enumerate(alive_items):
        ip = get_server_ip(item)
        code, isp = get_country_info(ip)
        
        flag = country_code_to_flag(code)
        protocol = get_protocol(item)
        
        # 1. Формируем базовое имя для подсчета дублей (Флаг, Код, Протокол)
        base_name = f"{flag} {code} {protocol}"
        
        # 2. Считаем количество таких серверов
        if base_name not in name_counts:
            name_counts[base_name] = 1
        else:
            name_counts[base_name] += 1
            
        # 3. Добавляем номер, если сервер повторяется, и провайдера в конце
        if name_counts[base_name] > 1:
            new_remarks = f"{base_name} #{name_counts[base_name]} | {isp}"
        else:
            new_remarks = f"{base_name} | {isp}"
            
        # Заменяем старое название на новое
        item["remarks"] = new_remarks
        alive_json.append(item)
        
        print(f"  {i+1}. {new_remarks:<35} | {ping} ms")

    # Сохраняем результат
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
