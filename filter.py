import base64
import re
import os
import requests
from urllib.parse import unquote

# === НАСТРОЙКИ ===
# Ссылка на исходную подписку берётся из секретов GitHub
SOURCE_URL = os.environ.get("SOURCE_URL") 
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

FILTER_WORD = "poland"                # Слово для поиска в названии сервера
OUTPUT_FILE = "filtered.txt"          # Имя файла для сохранения

# Заголовки для запроса. Если ваш провайдер требует HWID, добавьте его сюда.
# Например: "x-hwid": "ваш_уникальный_ид"
HEADERS = {
    "User-Agent": "HAPP/1.0",  # Притворяемся клиентом HAPP
    # "x-hwid": "YOUR_HWID_HERE", # Раскомментируйте и вставьте HWID, если нужно
}
# =================

def fetch_raw_sub(url: str) -> str:
    print("  Скачивание подписки...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def extract_uris(raw: str) -> list:
    # Если подписка отдаётся как base64-строка — декодируем
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8", errors="ignore")
        if "://" in decoded:
            raw = decoded
    except Exception:
        pass

    pattern = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?)://[^\s<>"]+'
    return re.findall(pattern, raw, flags=re.IGNORECASE)

def filter_by_name(uris: list, keyword: str) -> list:
    matched = []
    for uri in uris:
        if "#" in uri:
            tag = unquote(uri.split("#", 1)[1])
            if keyword.lower() in tag.lower():
                matched.append(uri)
    return matched

def main():
    print("[1/3] Загрузка подписки...")
    try:
        raw = fetch_raw_sub(SOURCE_URL)
    except Exception as e:
        print(f"  Ошибка при скачивании: {e}")
        return

    print("[2/3] Фильтрация по слову...")
    all_uris = extract_uris(raw)
    filtered = filter_by_name(all_uris, FILTER_WORD)
    print(f"  Всего найдено конфигов: {len(all_uris)}")
    print(f"  Совпало по слову '{FILTER_WORD}': {len(filtered)}")

    if not filtered:
        print("  Нет серверов с таким названием. Создаю пустой файл, чтобы GitHub не падал.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return

    print("[3/3] Сохранение результата...")
    content = "\n".join(filtered)
    b64 = base64.b64encode(content.encode()).decode()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(b64)
    print(f"  Готово. Сохранено серверов: {len(filtered)}")

if __name__ == "__main__":
    main()
