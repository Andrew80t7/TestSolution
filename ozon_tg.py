import os
import csv
import time
import logging
import requests
import socket
from datetime import datetime
from dotenv import load_dotenv
import urllib3.util.connection as urllib_conn

# Принудительно переключаем сокеты на IPv4
urllib_conn.allowed_gai_family = lambda: socket.AF_INET

load_dotenv()

# Настройки Ozon
OZON_CLIENT_ID = os.getenv("OZON_CLIENT_ID")
OZON_API_KEY = os.getenv("OZON_API_KEY")

# Настройки Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", 5))

# Опциональные параметры обхода блокировки Telegram
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY")  # Например: http://127.0.0.1:2080 или socks5://127.0.0.1:10808
TELEGRAM_CUSTOM_URL = os.getenv("TELEGRAM_CUSTOM_URL")  # Например: https://delicate-scene-fbf2.vysotnik3.workers.dev

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}


# --- 1. ПОЛУЧЕНИЕ ДАННЫХ С ОЗОН ---

def get_product_list():
    """Получаем список Product ID с использованием v3 API"""
    url = "https://api-seller.ozon.ru/v3/product/list"
    product_ids = []
    last_id = ""

    while True:
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": 1000
        }

        response = requests.post(url, headers=HEADERS, json=payload)

        if response.status_code == 429:
            logging.warning("Лимит запросов (429). Ждем 5 секунд...")
            time.sleep(5)
            continue

        if response.status_code != 200:
            logging.error(f"Ошибка API Ozon: {response.status_code} - {response.text}")
            break

        data = response.json().get("result", {})
        items = data.get("items", [])

        if not items:
            break

        for item in items:
            product_id = item.get("product_id")
            if product_id:
                product_ids.append(product_id)

        last_id = data.get("last_id", "")
        if not last_id or len(items) < 1000:
            break

        time.sleep(0.25)

    return product_ids


def get_products_info(product_ids):
    """Получаем детали по товарам (артикул, название, цена, остаток)"""
    url = "https://api-seller.ozon.ru/v3/product/info/list"
    detailed_products = []

    batch_size = 50
    for i in range(0, len(product_ids), batch_size):
        batch = [int(p) for p in product_ids[i:i + batch_size]]
        payload = {
            "offer_id": [],
            "product_id": batch,
            "sku": []
        }

        while True:
            response = requests.post(url, headers=HEADERS, json=payload)
            if response.status_code == 429:
                logging.warning("Лимит запросов (429) при получении инфо. Ждем 5 секунд...")
                time.sleep(5)
                continue
            break

        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])

            for item in items:
                offer_id = item.get("offer_id", "")
                name = item.get("name", "")
                price = item.get("price", "0")

                stocks_info = item.get("stocks", {})
                total_stock = 0
                if isinstance(stocks_info, dict):
                    stock_list = stocks_info.get("stocks", [])
                    if isinstance(stock_list, list):
                        total_stock = sum(s.get("present", 0) for s in stock_list if isinstance(s, dict))

                detailed_products.append({
                    "article": offer_id,
                    "name": name,
                    "price": price,
                    "stock": total_stock
                })
        else:
            logging.error(f"Ошибка получения батча инфо: {response.status_code} - {response.text}")

        time.sleep(0.25)

    return detailed_products


# --- 2. ОТПРАВКА СВОДКИ В TELEGRAM ---

def send_telegram_summary(products):
    """Формирует утренний отчет и отправляет его в Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Ошибка: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы в .env!")
        return

    date_str = datetime.now().strftime("%d.%m.%Y")

    lines = [
        f"📊 <b>Утренняя сводка Ozon ({date_str})</b>\n",
        f"Порог минимального остатка: <b>{LOW_STOCK_THRESHOLD} шт.</b>\n"
    ]

    low_stock_count = 0

    for i, prod in enumerate(products, 1):
        stock = int(prod.get("stock", 0))

        if stock < LOW_STOCK_THRESHOLD:
            low_stock_count += 1
            status_tag = "⚠️ <b>[Заканчивается!]</b>"
        else:
            status_tag = "✅"

        lines.append(
            f"{i}. <b>{prod['name']}</b>\n"
            f"   • Артикул: <code>{prod['article']}</code>\n"
            f"   • Цена: {prod['price']} ₽\n"
            f"   • Остаток: <b>{stock} шт.</b> {status_tag}\n"
        )

    if low_stock_count > 0:
        lines.append(f"🚨 <b>Внимание! Товаров требует пополнения: {low_stock_count}</b>")
    else:
        lines.append("🎉 Все товары в достаточном количестве!")

    message_text = "\n".join(lines)

    # Определение базового URL
    base_domain = TELEGRAM_CUSTOM_URL.rstrip('/') if TELEGRAM_CUSTOM_URL else "https://api.telegram.org"
    url = f"{base_domain}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }

    proxies = None
    if TELEGRAM_PROXY:
        proxies = {
            "http": TELEGRAM_PROXY,
            "https": TELEGRAM_PROXY
        }

    try:
        response = requests.post(url, json=payload, timeout=15, proxies=proxies)

        if response.status_code == 200:
            print("✅ Сводка успешно отправлена в Telegram!")
        else:
            print(f"❌ Ошибка Telegram API: {response.status_code} - {response.text}")

    except requests.exceptions.ProxyError as e:
        print(f"❌ Ошибка подключения к указанному прокси ({TELEGRAM_PROXY}): {e}")
    except requests.exceptions.Timeout:
        print("❌ Ошибка: Превышено время ожидания ответа (Timeout).")
        print("👉 Проверьте работоспособность прокси или доступность Telegram API.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Сетевая ошибка при отправке в Telegram: {e}")


if __name__ == "__main__":
    print(" Старт работы скрипта...")
    print(f"🔍 BOT_TOKEN задан: {'Да' if TELEGRAM_BOT_TOKEN else 'НЕТ (!)'}")
    print(f"🔍 CHAT_ID задан: {'Да' if TELEGRAM_CHAT_ID else 'НЕТ (!)'}")
    if TELEGRAM_PROXY:
        print(f"🌐 Используется прокси: {TELEGRAM_PROXY}")
    if TELEGRAM_CUSTOM_URL:
        print(f"🔗 Используется кастомный URL: {TELEGRAM_CUSTOM_URL}")

    print("1️⃣ Получаем ID товаров с Ozon...")
    p_ids = get_product_list()
    print(f"   Найдено ID: {len(p_ids)}")

    if p_ids:
        print("2️⃣ Получаем детали по товарам...")
        products_info = get_products_info(p_ids)
        print(f"   Получено товаров с деталями: {len(products_info)}")

        if products_info:
            print("3️⃣ Отправляем отчет в Telegram...")
            send_telegram_summary(products_info)
        else:
            print("❌ Не удалось получить детализацию по товарам.")
    else:
        print("❌ Ozon вернул пустой список ID или произошла ошибка подключения.")