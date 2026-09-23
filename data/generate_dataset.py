"""
generate_dataset.py - Генератор супер-детализированного набора данных для кейса ТОО «Электрокомплект» (ekt.kz)
Создает Excel-файл с 5 листами:
1. История_Продаж (12 000+ транзакций за 365 дней)
2. Текущие_Остатки_и_В_Пути (остатки, резерв, товары в пути)
3. Справочник_Поставщиков (сроки поставки, MOQ, кратность упаковки)
4. История_Дефицита_Stockout (периоды отсутствия товара для упущенного спроса)
5. Спецификация_ТестКейсов (описание заложенных аномалий: выбросы, сезонность, stockout)
"""

import os
import random
import datetime
import numpy as np
import pandas as pd

# Фиксируем seed для воспроизводимости
np.random.seed(42)
random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT_DIR, exist_ok=True)
EXCEL_PATH = os.path.join(OUT_DIR, "ekt_sales_and_stock_history.xlsx")

# 1. СПРАВОЧНИК ТОВАРОВ ЭЛЕКТРОКОМПЛЕКТ (ekt.kz)
SKU_CATALOG = [
    # Кабельно-проводниковая продукция
    {"sku_id": "EKT-CBL-001", "name": "Кабель ВВГнг(А)-LS 3х1.5 (бухта 100м)", "category": "Кабель и провод", "supplier": "Казэнергокабель", "base_price": 420.0, "unit": "м", "base_daily_sales": 220, "seasonal_type": "construction", "lead_time_days": 12, "moq": 500, "pack": 100},
    {"sku_id": "EKT-CBL-002", "name": "Кабель ВВГнг(А)-LS 3х2.5 (бухта 100м)", "category": "Кабель и провод", "supplier": "Казэнергокабель", "base_price": 680.0, "unit": "м", "base_daily_sales": 340, "seasonal_type": "construction_with_huge_outlier", "lead_time_days": 12, "moq": 500, "pack": 100},
    {"sku_id": "EKT-CBL-003", "name": "Провод СИП-4 4х16 (барабан)", "category": "Кабель и провод", "supplier": "Казэнергокабель", "base_price": 950.0, "unit": "м", "base_daily_sales": 110, "seasonal_type": "construction", "lead_time_days": 14, "moq": 200, "pack": 50},
    {"sku_id": "EKT-CBL-004", "name": "Кабель витая пара UTP 4 пары Cat 5e PVC 305м", "category": "Кабель и провод", "supplier": "ITK (IEK Group)", "base_price": 180.0, "unit": "м", "base_daily_sales": 180, "seasonal_type": "steady", "lead_time_days": 10, "moq": 305, "pack": 305},
    {"sku_id": "EKT-CBL-005", "name": "Провод ПВС 3х2.5 соединительный белый", "category": "Кабель и провод", "supplier": "Казэнергокабель", "base_price": 540.0, "unit": "м", "base_daily_sales": 150, "seasonal_type": "steady", "lead_time_days": 10, "moq": 100, "pack": 100},

    # Модульная автоматика и защита
    {"sku_id": "EKT-AUT-001", "name": "Выключатель автоматический 1P 16A C 4.5кА ВА47-29", "category": "Модульное оборудование", "supplier": "IEK Kazakhstan", "base_price": 1150.0, "unit": "шт", "base_daily_sales": 85, "seasonal_type": "steady_with_stockout", "lead_time_days": 7, "moq": 50, "pack": 12},
    {"sku_id": "EKT-AUT-002", "name": "Выключатель автоматический 1P 25A C 4.5кА ВА47-29", "category": "Модульное оборудование", "supplier": "IEK Kazakhstan", "base_price": 1150.0, "unit": "шт", "base_daily_sales": 90, "seasonal_type": "steady", "lead_time_days": 7, "moq": 50, "pack": 12},
    {"sku_id": "EKT-AUT-003", "name": "Выключатель автоматический 3P 32A C 6кА Easy9", "category": "Модульное оборудование", "supplier": "Schneider Electric / Systeme", "base_price": 4600.0, "unit": "шт", "base_daily_sales": 25, "seasonal_type": "steady", "lead_time_days": 21, "moq": 10, "pack": 6},
    {"sku_id": "EKT-AUT-004", "name": "УЗО 2P 40A 30мА электронное ВД1-63", "category": "Модульное оборудование", "supplier": "IEK Kazakhstan", "base_price": 4200.0, "unit": "шт", "base_daily_sales": 30, "seasonal_type": "steady", "lead_time_days": 7, "moq": 10, "pack": 6},
    {"sku_id": "EKT-AUT-005", "name": "Дифференциальный автомат 1P+N 16A C 30мА АВДТ32", "category": "Модульное оборудование", "supplier": "IEK Kazakhstan", "base_price": 3850.0, "unit": "шт", "base_daily_sales": 40, "seasonal_type": "steady", "lead_time_days": 7, "moq": 12, "pack": 6},
    {"sku_id": "EKT-AUT-006", "name": "Автоматический выключатель дифференциальный 3P+N 63A", "category": "Модульное оборудование", "supplier": "Schneider Electric / Systeme", "base_price": 18500.0, "unit": "шт", "base_daily_sales": 6, "seasonal_type": "steady", "lead_time_days": 25, "moq": 2, "pack": 1},

    # Светотехника
    {"sku_id": "EKT-LGT-001", "name": "Панель светодиодная LED 600x600 36W 4000K Опал", "category": "Светотехника", "supplier": "Philips Lighting / Signify", "base_price": 5400.0, "unit": "шт", "base_daily_sales": 45, "seasonal_type": "autumn_winter_peak", "lead_time_days": 18, "moq": 20, "pack": 4},
    {"sku_id": "EKT-LGT-002", "name": "Прожектор светодиодный 50W 6500K IP65 SMD", "category": "Светотехника", "supplier": "TDM Electric", "base_price": 4800.0, "unit": "шт", "base_daily_sales": 32, "seasonal_type": "winter_peak", "lead_time_days": 14, "moq": 15, "pack": 1},
    {"sku_id": "EKT-LGT-003", "name": "Лампа светодиодная LED A60 11W E27 4000K", "category": "Светотехника", "supplier": "TDM Electric", "base_price": 420.0, "unit": "шт", "base_daily_sales": 140, "seasonal_type": "autumn_winter_peak", "lead_time_days": 14, "moq": 100, "pack": 10},
    {"sku_id": "EKT-LGT-004", "name": "Светильник пылевлагозащищенный ЛСП 2х36W IP65", "category": "Светотехника", "supplier": "IEK Kazakhstan", "base_price": 6200.0, "unit": "шт", "base_daily_sales": 20, "seasonal_type": "steady", "lead_time_days": 10, "moq": 10, "pack": 2},
    {"sku_id": "EKT-LGT-005", "name": "Светильник аварийный светодиодный 30 LED с АКБ", "category": "Светотехника", "supplier": "TDM Electric", "base_price": 3100.0, "unit": "шт", "base_daily_sales": 18, "seasonal_type": "has_large_in_transit", "lead_time_days": 14, "moq": 10, "pack": 5},

    # Электроустановочные изделия
    {"sku_id": "EKT-ELU-001", "name": "Розетка 2-местная с заземлением белая Glossa", "category": "Электроустановочные изделия", "supplier": "Schneider Electric / Systeme", "base_price": 1450.0, "unit": "шт", "base_daily_sales": 70, "seasonal_type": "construction", "lead_time_days": 15, "moq": 40, "pack": 10},
    {"sku_id": "EKT-ELU-002", "name": "Выключатель 1-клавишный белый Glossa", "category": "Электроустановочные изделия", "supplier": "Schneider Electric / Systeme", "base_price": 1200.0, "unit": "шт", "base_daily_sales": 65, "seasonal_type": "construction", "lead_time_days": 15, "moq": 40, "pack": 10},
    {"sku_id": "EKT-ELU-003", "name": "Рамка 3 поста универсальная белая Glossa", "category": "Электроустановочные изделия", "supplier": "Schneider Electric / Systeme", "base_price": 850.0, "unit": "шт", "base_daily_sales": 40, "seasonal_type": "construction", "lead_time_days": 15, "moq": 20, "pack": 10},
    {"sku_id": "EKT-ELU-004", "name": "Вилка каучуковая прямая 16A IP44", "category": "Электроустановочные изделия", "supplier": "TDM Electric", "base_price": 720.0, "unit": "шт", "base_daily_sales": 50, "seasonal_type": "steady", "lead_time_days": 10, "moq": 30, "pack": 10},

    # Кабельнесущие системы
    {"sku_id": "EKT-CNS-001", "name": "Кабель-канал 25х16 мм белый (упак. 40м)", "category": "Кабельнесущие системы", "supplier": "Промрукав Казахстан", "base_price": 160.0, "unit": "м", "base_daily_sales": 260, "seasonal_type": "steady_high_moq", "lead_time_days": 8, "moq": 1000, "pack": 40},
    {"sku_id": "EKT-CNS-002", "name": "Лоток перфорированный оцинкованный 100х50х3000", "category": "Кабельнесущие системы", "supplier": "Промрукав Казахстан", "base_price": 2850.0, "unit": "м", "base_daily_sales": 80, "seasonal_type": "growth_trend", "lead_time_days": 14, "moq": 150, "pack": 3},
    {"sku_id": "EKT-CNS-003", "name": "Труба гофрированная ПВХ d20 с протяжкой (100м)", "category": "Кабельнесущие системы", "supplier": "Промрукав Казахстан", "base_price": 75.0, "unit": "м", "base_daily_sales": 450, "seasonal_type": "construction", "lead_time_days": 6, "moq": 500, "pack": 100},

    # Щитовое оборудование и аксессуары
    {"sku_id": "EKT-SHT-001", "name": "Корпус металлический ЩРн-24з-1 36 УХЛ3 IP31", "category": "Щитовое оборудование", "supplier": "IEK Kazakhstan", "base_price": 14200.0, "unit": "шт", "base_daily_sales": 12, "seasonal_type": "steady", "lead_time_days": 10, "moq": 5, "pack": 1},
    {"sku_id": "EKT-SHT-002", "name": "Счетчик э/э многотарифный 3-фазный прямого включения", "category": "Щитовое оборудование", "supplier": "Энергомера РК", "base_price": 24500.0, "unit": "шт", "base_daily_sales": 8, "seasonal_type": "steady", "lead_time_days": 20, "moq": 5, "pack": 1},
    {"sku_id": "EKT-SHT-003", "name": "Шина нулевая изолированная на DIN-рейку 8х12 / 12 групп", "category": "Щитовое оборудование", "supplier": "IEK Kazakhstan", "base_price": 480.0, "unit": "шт", "base_daily_sales": 95, "seasonal_type": "steady", "lead_time_days": 7, "moq": 50, "pack": 10},
    {"sku_id": "EKT-SHT-004", "name": "Наконечник кабельный медный луженый ТМЛ 16-8-6", "category": "Щитовое оборудование", "supplier": "IEK Kazakhstan", "base_price": 110.0, "unit": "шт", "base_daily_sales": 320, "seasonal_type": "steady", "lead_time_days": 7, "moq": 500, "pack": 100},
]

WAREHOUSES = ["Склад Астана (Главный РЦ)", "Склад Алматы (Южный РЦ)"]

# Пул обезличенных клиентов:
CLIENT_POOL = [f"CLNT-{1000 + i:04d}" for i in range(120)]
VIP_CLIENT = "CLNT-VIP-BIG-PROJECT"

START_DATE = datetime.date(2025, 9, 1)
END_DATE = datetime.date(2026, 8, 31)
NUM_DAYS = (END_DATE - START_DATE).days + 1

sales_records = []

# Отслеживание остатков по каждому товару и складу
stock_tracker = {}
for sku in SKU_CATALOG:
    stock_tracker[sku["sku_id"]] = {
        WAREHOUSES[0]: sku["base_daily_sales"] * 25,
        WAREHOUSES[1]: sku["base_daily_sales"] * 18
    }

# Период зафиксированного дефицита (Stockout) для EKT-AUT-001: 2026-06-10 по 2026-06-25
STOCKOUT_SKU = "EKT-AUT-001"
STOCKOUT_START = datetime.date(2026, 6, 10)
STOCKOUT_END = datetime.date(2026, 6, 25)

# Разовый аномальный выброс для EKT-CBL-002: 2026-04-18
OUTLIER_SKU = "EKT-CBL-002"
OUTLIER_DATE = datetime.date(2026, 4, 18)

print(f"Генерация истории продаж за {NUM_DAYS} дней (с {START_DATE} по {END_DATE})...")

for day_idx in range(NUM_DAYS):
    current_date = START_DATE + datetime.timedelta(days=day_idx)
    month = current_date.month
    day_of_week = current_date.weekday()

    # Сезонные коэффициенты
    # Строительный сезон в Казахстане: май-октябрь
    construction_multiplier = 1.45 if month in [5, 6, 7, 8, 9, 10] else 0.75
    # Зимний пик освещения: ноябрь-февраль
    light_multiplier = 1.65 if month in [11, 12, 1, 2] else 0.8
    # Выходные дни (спад в b2b продажах электротехники):
    weekend_factor = 0.35 if day_of_week in [5, 6] else 1.0

    for sku in SKU_CATALOG:
        sku_id = sku["sku_id"]
        base_sales = sku["base_daily_sales"]
        s_type = sku["seasonal_type"]

        # Расчет дневного тренда спроса
        demand_mult = 1.0
        if "construction" in s_type:
            demand_mult = construction_multiplier
        elif "winter_peak" in s_type or "autumn_winter_peak" in s_type:
            demand_mult = light_multiplier
        elif s_type == "growth_trend":
            # Устойчивый рост спроса +2% в месяц
            demand_mult = 1.0 + (day_idx / 365.0) * 0.35

        # Эмуляция периода дефицита (Stockout)
        if sku_id == STOCKOUT_SKU and (STOCKOUT_START <= current_date <= STOCKOUT_END):
            # В этот период остаток = 0, продажи = 0!
            # Это Must Have №3 для оценки упущенного спроса!
            for wh in WAREHOUSES:
                stock_tracker[sku_id][wh] = 0
            continue

        # Генерация нескольких чеков/транзакций за день
        num_transactions = random.randint(1, 4) if day_of_week < 5 else (1 if random.random() < 0.4 else 0)

        for _ in range(num_transactions):
            wh = WAREHOUSES[0] if random.random() < 0.62 else WAREHOUSES[1]
            client = random.choice(CLIENT_POOL)

            # Базовое количество в одной накладной
            qty = max(1, int(np.random.normal(base_sales / 2.2, base_sales * 0.25) * demand_mult * weekend_factor))

            # Проверка разового выброса (Must Have №4)
            if sku_id == OUTLIER_SKU and current_date == OUTLIER_DATE and client != VIP_CLIENT:
                client = VIP_CLIENT
                qty = 4800  # Разовый гигантский заказ (вместо обычных 100-200 м)

            price = sku["base_price"]
            # Скидка крупным клиентам 3-7%
            if qty > base_sales:
                price = round(price * random.uniform(0.93, 0.97), 2)

            # Списываем со склада
            curr_stock = stock_tracker[sku_id][wh]
            actual_qty = min(qty, curr_stock) if curr_stock > 0 else 0

            # Периодическое пополнение склада (чтобы остатки жили реалистично)
            if curr_stock < base_sales * 8 and random.random() < 0.35:
                replenishment = base_sales * random.randint(15, 30)
                stock_tracker[sku_id][wh] += replenishment

            if actual_qty > 0:
                stock_tracker[sku_id][wh] -= actual_qty
                sales_records.append({
                    "Дата_продажи": current_date.strftime("%Y-%m-%d"),
                    "Артикул": sku_id,
                    "Наименование_товара": sku["name"],
                    "Категория": sku["category"],
                    "Количество": actual_qty,
                    "Единица_измерения": sku["unit"],
                    "Цена_за_ед_KZT": price,
                    "Сумма_KZT": round(actual_qty * price, 2),
                    "ID_Клиента": client,
                    "Склад_отгрузки": wh,
                    "Остаток_на_конец_дня": stock_tracker[sku_id][wh]
                })

df_sales = pd.DataFrame(sales_records)
print(f"Всего создано {len(df_sales)} строк детальной истории продаж.")

# 2. ТЕКУЩИЕ ОСТАТКИ И ТОВАРЫ В ПУТИ (На дату 2026-09-01)
stock_records = []
for sku in SKU_CATALOG:
    sku_id = sku["sku_id"]
    for wh in WAREHOUSES:
        phys_stock = stock_tracker[sku_id][wh]
        reserved = int(phys_stock * random.uniform(0.05, 0.18))
        
        # Товар в пути
        in_transit = 0
        exp_date = "-"
        supplier_order_no = "-"

        # Особый кейс для EKT-LGT-005 (большой товар в пути)
        if sku_id == "EKT-LGT-005" and wh == WAREHOUSES[0]:
            in_transit = 1200
            exp_date = "2026-09-06"
            supplier_order_no = "PO-2026-8812"
        elif random.random() < 0.28:
            in_transit = sku["base_daily_sales"] * random.randint(8, 20)
            in_transit = (in_transit // sku["pack"]) * sku["pack"]
            exp_date = (datetime.date(2026, 9, 1) + datetime.timedelta(days=random.randint(3, 14))).strftime("%Y-%m-%d")
            supplier_order_no = f"PO-2026-{random.randint(1000, 9999)}"

        stock_records.append({
            "Артикул": sku_id,
            "Наименование_товара": sku["name"],
            "Категория": sku["category"],
            "Склад": wh,
            "Физический_остаток": phys_stock,
            "Зарезервировано": reserved,
            "Доступный_остаток": max(0, phys_stock - reserved),
            "Товар_в_пути": in_transit,
            "Ожидаемая_дата_поставки": exp_date,
            "Номер_заказа_поставщику": supplier_order_no
        })

df_stock = pd.DataFrame(stock_records)

# 3. СПРАВОЧНИК ПОСТАВЩИКОВ И УСЛОВИЙ ЗАКУПА
suppliers_records = []
for sku in SKU_CATALOG:
    suppliers_records.append({
        "Артикул": sku["sku_id"],
        "Наименование_товара": sku["name"],
        "Категория": sku["category"],
        "Поставщик": sku["supplier"],
        "Срок_поставки_LeadTime_дней": sku["lead_time_days"],
        "Минимальная_партия_MOQ": sku["moq"],
        "Кратность_упаковки_Pack": sku["pack"],
        "Базовая_закупочная_цена_KZT": sku["base_price"],
        "Единица_измерения": sku["unit"],
        "Условия_оплаты": "Отсрочка 30 дней" if "Schneider" not in sku["supplier"] else "Аванс 50% / 50%",
        "Надежность_поставщика": "Высокая (98%)" if "Казэнергокабель" in sku["supplier"] or "IEK" in sku["supplier"] else "Средняя (90%)"
    })

df_suppliers = pd.DataFrame(suppliers_records)

# 4. ИСТОРИЯ ДЕФИЦИТА (STOCKOUTS) ДЛЯ ОЦЕНКИ УПУЩЕННОГО СПРОСА
stockouts_records = [
    {
        "Артикул": "EKT-AUT-001",
        "Наименование_товара": "Выключатель автоматический 1P 16A C 4.5кА ВА47-29",
        "Склад": "Склад Астана (Главный РЦ)",
        "Дата_начала_дефицита": "2026-06-10",
        "Дата_окончания_дефицита": "2026-06-25",
        "Дней_без_товара": 16,
        "Причина_дефицита": "Задержка на таможенном терминале",
        "Статус_упущенного_спроса": "ТРЕБУЕТ КОМПЕНСАЦИИ (Must Have №3)"
    },
    {
        "Артикул": "EKT-CBL-001",
        "Наименование_товара": "Кабель ВВГнг(А)-LS 3х1.5 (бухта 100м)",
        "Склад": "Склад Алматы (Южный РЦ)",
        "Дата_начала_дефицита": "2026-03-01",
        "Дата_окончания_дефицита": "2026-03-08",
        "Дней_без_товара": 8,
        "Причина_дефицита": "Резкий скачок спроса перед стартом стройсезона",
        "Статус_упущенного_спроса": "ТРЕБУЕТ КОМПЕНСАЦИИ (Must Have №3)"
    },
    {
        "Артикул": "EKT-SHT-002",
        "Наименование_товара": "Счетчик э/э многотарифный 3-фазный прямого включения",
        "Склад": "Склад Астана (Главный РЦ)",
        "Дата_начала_дефицита": "2026-01-15",
        "Дата_окончания_дефицита": "2026-01-26",
        "Дней_без_товара": 12,
        "Причина_дефицита": "Срыв сроков поставки заводом",
        "Статус_упущенного_спроса": "ТРЕБУЕТ КОМПЕНСАЦИИ (Must Have №3)"
    }
]

df_stockouts = pd.DataFrame(stockouts_records)

# 5. СПЕЦИФИКАЦИЯ ТЕСТОВЫХ СЦЕНАРИЕВ ДЛЯ ПРОВЕРКИ ЖЮРИ И РАЗРАБОТКИ
spec_records = [
    {
        "Критерий_ТЗ_MustHave": "1. Базовый расчет по всем источникам",
        "Артикул_для_теста": "EKT-CBL-005, EKT-AUT-002",
        "Что_проверяется": "Алгоритм учитывает остаток, резерв, прогноз продаж и срок поставки Lead Time. При изменении товаров в пути рекомендация меняется."
    },
    {
        "Критерий_ТЗ_MustHave": "2. Сезонность и рост спроса",
        "Артикул_для_теста": "EKT-LGT-001, EKT-LGT-002, EKT-CNS-002",
        "Что_проверяется": "Светотехника показывает пик продаж в осенне-зимний период (ноябрь-январь). Лоток перфорированный показывает устойчивый рост тренда (+15%)."
    },
    {
        "Критерий_ТЗ_MustHave": "3. Упущенный спрос (Stockout)",
        "Артикул_для_теста": "EKT-AUT-001",
        "Что_проверяется": "В период с 10 по 25 июня 2026 продажи = 0 из-за отсутствия остатка. Алгоритм обязан реконструировать упущенный спрос (~85 шт/день * 16 дней = 1360 шт) и скорректировать объем закупки вверх!"
    },
    {
        "Критерий_ТЗ_MustHave": "4. Исключение разовых крупных заказов",
        "Артикул_для_теста": "EKT-CBL-002",
        "Что_проверяется": "18.04.2026 зафиксирована разовая аномальная покупка 4800м клиентом CLNT-VIP-BIG-PROJECT (при норме 340м/день). Алгоритм обязан исключить этот выброс и не раздувать регулярный складской заказ!"
    },
    {
        "Критерий_ТЗ_MustHave": "5. Товары в пути (In-Transit)",
        "Артикул_для_теста": "EKT-LGT-005",
        "Что_проверяется": "Текущий остаток низок, но в пути находится крупная партия 1200 шт с поставкой 06.09.2026. Сервис обязан уменьшить рекомендованный объем на величину поставки в пути."
    },
    {
        "Критерий_ТЗ_MustHave": "Опционально: MOQ и кратность",
        "Артикул_для_теста": "EKT-CNS-001",
        "Что_проверяется": "Кабель-канал: минимальный заказ MOQ = 1000м, кратность пачки = 40м. Алгоритм округляет расчетную потребность до ближайшего допустимого значения поставщика."
    }
]

df_spec = pd.DataFrame(spec_records)

# Сохранение в многостраничный Excel с красивым форматированием
print(f"Запись в Excel: {EXCEL_PATH} ...")
with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
    df_sales.to_excel(writer, sheet_name="История_Продаж", index=False)
    df_stock.to_excel(writer, sheet_name="Текущие_Остатки_и_В_Пути", index=False)
    df_suppliers.to_excel(writer, sheet_name="Справочник_Поставщиков", index=False)
    df_stockouts.to_excel(writer, sheet_name="История_Дефицита_Stockout", index=False)
    df_spec.to_excel(writer, sheet_name="Спецификация_ТестКейсов", index=False)

# Также сохраняем плоские CSV для супер-быстрого чтения в pandas / python
csv_sales = os.path.join(OUT_DIR, "sales_history.csv")
csv_stock = os.path.join(OUT_DIR, "current_stock.csv")
csv_suppliers = os.path.join(OUT_DIR, "suppliers.csv")
csv_stockouts = os.path.join(OUT_DIR, "stockouts.csv")

df_sales.to_csv(csv_sales, index=False, encoding="utf-8-sig")
df_stock.to_csv(csv_stock, index=False, encoding="utf-8-sig")
df_suppliers.to_csv(csv_suppliers, index=False, encoding="utf-8-sig")
df_stockouts.to_csv(csv_stockouts, index=False, encoding="utf-8-sig")

print("✅ Генерация успешно завершена!")
print(f"Excel файл: {EXCEL_PATH}")
print(f"Размер строк продаж: {len(df_sales)}")
