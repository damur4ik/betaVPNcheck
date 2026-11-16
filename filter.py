import base64
import re
import os
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
    return resp.text

def extract_uris(raw: str) -> list:
    # --- ОТЛАДКА: смотрим, что пришло в подписке ---
    print(f"  [DEBUG] Размер сырого ответа: {len(raw)} символов")
    print(f"  [DEBUG] Первые 200 символов: {raw[:200]!r}")

    # Пытаемся декодировать Base64 (с добавлением padding, если нужно)
    try:
        # Иногда Base64 приходит без символов '=' в конце. Добавляем их при необходимости.
        missing_padding = len(raw) % 4
        if missing_padding:
            raw_padded = raw + '=' * (4 - missing_padding)
        else:
            raw_padded = raw
            
        decoded = base64.b64decode(raw_padded).decode("utf-8", errors="ignore")
        if "://" in decoded:
            print("  [DEBUG] Подписка была в Base64, успешно декодирована.")
            raw = decoded
        else:
            print("  [DEBUG] Подписка не в Base64 (или декодирование не дало ссылок).")
    except Exception as e:
        print(f"  [DEBUG] Ошибка декодирования Base64: {e}")
        pass

    # --- ОТЛАДКА: показываем кусок текста после возможного декодирования ---
    print(f"  [DEBUG] Текст после обработки (первые 300 символов): {raw[:300]!r}")

    # Ищем все ссылки на прокси-протоколы
    pattern = r'(?:vless|vmess|trojan|ss|ssr|hysteria2?)://[^\s<>"]+'
    uris = re.findall(pattern, raw, flags=re.IGNORECASE)
    
    # --- ОТЛАДКА: выводим найденные ссылки (или их часть) ---
    print(f"  [DEBUG] Найдено URI всего: {len(uris)}")
    for i, uri in enumerate(uris[:5]):  # Показываем первые 5 для примера
        print(f"    [DEBUG] URI {i+1}: {uri[:150]}...")
    return uris

def filter_by_name(uris: list, keyword: str) -> list:
    matched = []
    for uri in uris:
        if "#" in uri:
            # Декодируем тег. Иногда используется '+' как пробел, поэтому unquote_plus надёжнее.
            raw_tag = uri.split("#", 1)[1]
            tag = unquote_plus(raw_tag) 
            
            # --- ОТЛАДКА: смотрим на теги ---
            # (Раскомментируйте строку ниже, если нужно увидеть все теги)
            # print(f"    [DEBUG] Тег: {tag!r}")

            if keyword.lower() in tag.lower():
                print(f"  [DEBUG] Совпадение найдено: {tag!r}")
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
        print("  Нет серверов с таким названием. Создаю пустой файл.")
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
