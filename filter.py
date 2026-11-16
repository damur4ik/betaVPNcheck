import base64
import re
import os
import json
import requests
from urllib.parse import unquote, unquote_plus

# === НАСТРОЙКИ ===
SOURCE_URL = os.environ.get("SOURCE_URL")
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

FILTER_WORD = "poland"
OUTPUT_FILE = "filtered.txt"
HEADERS = {"User-Agent": "HAPP/1.0"}
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()

def main():
    print("[1/3] Загрузка подписки...")
    try:
        raw = fetch_raw_sub(SOURCE_URL)
    except Exception as e:
        print(f"  Ошибка при скачивании: {e}")
        return

    print("[2/3] Фильтрация...")
    matched_json_items = []
    matched_uris = []

    # 1. Проверяем, является ли ответ JSON-массивом (как в вашем логе)
    if raw.startswith("[") and raw.endswith("]"):
        print("  [DEBUG] Формат подписки: JSON массив (Xray)")
        try:
            data = json.loads(raw)
            for item in data:
                remarks = item.get("remarks", "")
                if FILTER_WORD.lower() in remarks.lower():
                    # Проверяем, есть ли среди outbounds протокол vless (если нужно)
                    outbounds = item.get("outbounds", [])
                    is_vless = any(ob.get("protocol") == "vless" for ob in outbounds)
                    
                    if is_vless:
                        print(f"  [DEBUG] Найден VLESS: {remarks}")
                        matched_json_items.append(item)
                    else:
                        # Если протокол не vless, но вы хотите брать всё подряд, 
                        # просто раскомментируйте строку ниже и удалите проверку is_vless
                        # matched_json_items.append(item)
                        pass
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] Ошибка парсинга JSON: {e}")

    # 2. Если это не JSON, используем старую логику (Base64 и URI)
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
                    matched_uris.append(uri)

    print(f"  Найдено совпадений: {len(matched_json_items) + len(matched_uris)}")

    # 3. Сохранение результата
    if matched_json_items:
        # Сохраняем как JSON (HAPP отлично понимает такой формат)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(matched_json_items, f, ensure_ascii=False, indent=2)
        print(f"[3/3] Готово. Сохранено JSON серверов: {len(matched_json_items)}")
        
    elif matched_uris:
        # Сохраняем как Base64 (стандартный формат для ссылок)
        content = "\n".join(matched_uris)
        b64 = base64.b64encode(content.encode()).decode()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(b64)
        print(f"[3/3] Готово. Сохранено URI серверов: {len(matched_uris)}")
        
    else:
        print("  Нет серверов с таким названием. Создаю пустой файл.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")

if __name__ == "__main__":
    main()
