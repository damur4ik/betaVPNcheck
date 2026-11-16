import base64
import re
import os
import requests
from urllib.parse import unquote

# === НАСТРОЙКИ ===
# Ссылка на исходную подписку берётся из переменной окружения GitHub Actions
SOURCE_URL = os.environ.get("SOURCE_URL") 
if not SOURCE_URL:
    raise ValueError("Не задана переменная окружения SOURCE_URL")

FILTER_WORD = "poland"                # Слово для поиска в названии сервера (без учёта регистра)
OUTPUT_FILE = "filtered.txt"          # Имя файла, который попадёт в репозиторий
# =================

def fetch_raw_sub(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def extract_uris(raw: str) -> list[str]:
    """Достаёт все URI (vless://, vmess:// и т.д.) из сырого текста подписки."""
    # Если подписка отдаётся как base64-строка — декодируем
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8", errors="ignore")
        if "://" in decoded:
            raw = decoded
    except Exception:
        pass

    pattern = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?)://[^\s<>"]+'
    return re.findall(pattern, raw, flags=re.IGNORECASE)

def filter_by_name(uris: list[str], keyword: str) -> list[str]:
    """Оставляет только те URI, в теге (после #) которых есть ключевое слово."""
    matched = []
    for uri in uris:
        if "#" in uri:
            tag = unquote(uri.split("#", 1)[1])
            if keyword.lower() in tag.lower():
                matched.append(uri)
    return matched

def main():
    print("[1/3] Загрузка подписки...")
    raw = fetch_raw_sub(SOURCE_URL)

    print("[2/3] Фильтрация по слову...")
    all_uris = extract_uris(raw)
    filtered = filter_by_name(all_uris, FILTER_WORD)
    print(f"    Найдено совпадений: {len(filtered)}")

        if not filtered:
        print("    Нет серверов с таким названием. Создаю пустой файл.")
        # Создаём пустой файл, чтобы git add не выдавал ошибку
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return

    # Сохраняем в формате base64 (стандартная подписка для HAPP)
    content = "\n".join(filtered)
    b64 = base64.b64encode(content.encode()).decode()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(b64)
    print(f"[3/3] Готово. Сохранено серверов: {len(filtered)}")

if __name__ == "__main__":
    main()
