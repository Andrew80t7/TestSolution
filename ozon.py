import os
import csv
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

CLIENT_ID = os.getenv("OZON_CLIENT_ID")
API_KEY = os.getenv("OZON_API_KEY")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

HEADERS = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}


def get_product_list():
    """Получаем список Product ID с использованием актуального метода v3"""
    url = "https://api-seller.ozon.ru/v3/product/list"
    product_ids = []
    last_id = ""

    while True:
        # Корректный payload для v3
        payload = {
            "filter": {
                "visibility": "ALL"
            },
            "last_id": last_id,
            "limit": 1000
        }

        response = requests.post(url, headers=HEADERS, json=payload)

        if response.status_code == 429:
            logging.warning("Лимит запросов (429). Ждем 5 секунд...")
            time.sleep(5)
            continue

        if response.status_code != 200:
            logging.error(f"Ошибка API: {response.status_code} - {response.text}")
            break

        data = response.json().get("result", {})
        items = data.get("items", [])

        if not items:
            break

        # Извлекаем product_id из словарей
        for item in items:
            product_id = item.get("product_id")
            if product_id:
                product_ids.append(product_id)

        # Берем last_id для следующей страницы
        last_id = data.get("last_id", "")
        if not last_id or len(items) < 1000:
            break

        time.sleep(0.25)  # Защита от лимитов

    logging.info(f"Всего получено ID товаров: {len(product_ids)}")
    return product_ids


def get_products_info(product_ids):
    """Получаем детали по товарам батчами до 50 штук"""
    url = "https://api-seller.ozon.ru/v3/product/info/list"
    detailed_products = []

    batch_size = 50
    for i in range(0, len(product_ids), batch_size):
        # Принудительно конвертируем в int
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

def save_to_csv(products):
    """Сохраняем результат в CSV файл с текущей датой"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"ozon_products_{date_str}.csv"

    with open(filename, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["article", "name", "price", "stock"])
        writer.writeheader()
        writer.writerows(products)

    logging.info(f"Данные успешно сохранены в файл: {filename}")
    return filename


if __name__ == "__main__":
    p_ids = get_product_list()
    if p_ids:
        products_info = get_products_info(p_ids)
        filename = save_to_csv(products_info)

        print("\n" + "=" * 50)
        print(" УСПЕШНЫЙ ВЫВОД РЕЗУЛЬТАТА С ОЗОНА (ПЕРВЫЕ 5 ТОВАРОВ):")
        print("=" * 50)
        for i, prod in enumerate(products_info[:5], 1):
            print(
                f"{i}. Артикул: {prod['article']} | Название: {prod['name'][:40]}... | Цена: {prod['price']} | Остаток: {prod['stock']}"
            )
        print("=" * 50)
        print(f"Всего выгружено товаров: {len(products_info)}")
        print(f"Файл сохранен: {filename}")
        print("=" * 50 + "\n")
    else:
        logging.info("Товары не найдены или ошибка доступа.")