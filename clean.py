import os
import re
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

INPUT_FILE = "catalog_raw.csv"
OUTPUT_FILE = "catalog_clean.csv"


def clean_price(price_val):
    """Приводит различные форматы цен ('1 500 руб', '1500.00', '1500р', '1 500 rub') к float."""
    if pd.isna(price_val):
        return None

    # Приводим к строке, меняем запятые на точки, убираем неразрывные пробелы
    s = str(price_val).replace('\xa0', ' ').replace(',', '.').strip()

    # Удаляем пробелы между цифрами (например, '1 500' -> '1500')
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)

    # Ищем число (целое или с дробной частью)
    match = re.search(r'\d+(?:\.\d+)?', s)
    if match:
        return float(match.group())
    return None


def parse_details(name_str):
    """Извлекает из исходного названия: Бренд, OEM-номер и Тип упаковки (Штука/Комплект)."""
    if pd.isna(name_str) or not str(name_str).strip():
        return pd.Series({"brand": "", "oem": "", "quantity_type": ""})

    text = str(name_str).strip()

    # 1. Извлечение количества / фасовки (Комплект или Штука)
    quantity_type = "Штука"
    if re.search(r'\b(комплект|компл|набор|set|пачка)\b', text, re.IGNORECASE):
        quantity_type = "Комплект"

    # 2. Извлечение OEM-номера (типовые авто-артикулы: 90919-01253, 0242236564, 22401-AA630, C25004)
    oem_match = re.search(r'\b([A-Z0-9]{3,}(?:-[A-Z0-9]+)+|[A-Z0-9]{6,15})\b', text, re.IGNORECASE)
    oem = oem_match.group(1) if oem_match else ""

    # 3. Извлечение бренда (известные производители автокомпонентов или первое латинское/кириллическое слово)
    brand_pattern = r'\b(BOSCH|NGK|DENSO|TOYOTA|NISSAN|HYUNDAI|KIA|MANN-FILTER|MANN|SANGSIN|BREMBO|VALEO|KAVO|PATRON|SAKURA|SCT|JAPANPARTS|MILES)\b'
    brand_match = re.search(brand_pattern, text, re.IGNORECASE)

    if brand_match:
        brand = brand_match.group(1).upper()
    else:
        # Если бренда нет в словаре, берем первое отдельное слово из букв (от 2 символов)
        words = re.findall(r'\b[A-Za-zА-Яа-я]{2,}\b', text)
        brand = words[0].upper() if words else ""

    return pd.Series({
        "brand": brand,
        "oem": oem,
        "quantity_type": quantity_type
    })


def process_catalog():
    if not os.path.exists(INPUT_FILE):
        logging.error(f"Файл {INPUT_FILE} не найден в текущей директории!")
        return

    logging.info(f"Читаем сырой файл {INPUT_FILE}...")

    # Чтение CSV (авто-определение разделителя или стандартная запятая/точка с запятой)
    try:
        df = pd.read_csv(INPUT_FILE, sep=None, engine='python')
    except Exception:
        df = pd.read_csv(INPUT_FILE)

    initial_count = len(df)
    logging.info(f"Загружено строк: {initial_count}")

    # 1. Удаление полностью пустых строк
    df.dropna(how='all', inplace=True)

    # Определяем колонки (ищем наиболее похожие на Name и Price)
    name_col = next(
        (col for col in df.columns if 'name' in col.lower() or 'название' in col.lower() or 'товар' in col.lower()),
        df.columns[0])
    price_col = next((col for col in df.columns if 'price' in col.lower() or 'цена' in col.lower()),
                     df.columns[1] if len(df.columns) > 1 else df.columns[0])

    # Удаляем строки без названия или без цены
    df.dropna(subset=[name_col, price_col], inplace=True)

    # 2. Очистка цен
    df['clean_price'] = df[price_col].apply(clean_price)
    df.dropna(subset=['clean_price'], inplace=True)  # Удаляем, если цену не удалось распознать

    # 3. Парсинг характеристик (Бренд, OEM, Количество)
    parsed_fields = df[name_col].apply(parse_details)
    df[['brand', 'oem', 'quantity_type']] = parsed_fields

    # Переименовываем и упорядочиваем колонки
    df.rename(columns={name_col: 'name', 'clean_price': 'price'}, inplace=True)

    output_df = df[['name', 'brand', 'oem', 'quantity_type', 'price']]

    # 4. Удаление дубликатов
    output_df = output_df.drop_duplicates()

    # Сохранение в CSV
    output_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')

    cleaned_count = len(output_df)
    logging.info(
        f"Очистка завершена! Удалено дублей/мусора: {initial_count - cleaned_count}. Сохранено строк: {cleaned_count}")
    logging.info(f"Результат записан в {OUTPUT_FILE}")


if __name__ == "__main__":
    process_catalog()