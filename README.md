# StockPilot — Explainable Warehouse Replenishment OS

Система автоматического и объяснимого расчёта заказов поставщикам для пополнения распределительных складов дистрибьютора электротехники **ТОО «Электрокомплект» (ekt.kz)**.

StockPilot объединяет историю продаж, текущие остатки, товары в пути, логистические сроки (Lead Time), минимальные партии (MOQ), кванты упаковки и периоды дефицита (stockouts) для ответа на ключевой вопрос закупщика: **что, сколько и почему нужно заказать прямо сейчас?**

---

## ⚡️ Быстрый запуск в 1 команду (Docker)

```bash
docker compose up --build
```

- **Frontend Dashboard:** [http://localhost:5173](http://localhost:5173)
- **Backend Swagger API:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 🛠 Локальный запуск для разработки

### 1. Backend (FastAPI + Python 3.12/3.13)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend (React + Vite + TypeScript)

```powershell
cd frontend
npm install
npm run dev
```

Откройте [http://localhost:5173](http://localhost:5173). В приложении доступны:
1. Кнопка **«⚡️ ekt.kz Dataset (Казахстан)»** — мгновенная загрузка реального датасета ТОО «Электрокомплект» с расчётом заказов и бюджета в тенге (₸).
2. Кнопка **«↻ Synthetic demo»** — синтетический эталонный сценарий (105 SKU, 3 склада, 5 поставщиков).
3. Раздел **«Data Intake»** — загрузка файлов по отдельности или книги Excel целиком (`ekt_sales_and_stock_history.xlsx`, 5 листов в 1 клик).

---

## 📐 Архитектура и математический аппарат

StockPilot строго следует пяти ключевым критериям Must Have ТЗ хакатона:

### 1. Формула расчёта потребности
$$\text{Demand during Lead Time} = \text{Lead Time (days)} \times \text{Average Daily Demand} \times \text{Seasonality} \times (1 + \text{Trend})$$
$$\text{Safety Stock} = Z \times \sigma_{\text{daily}} \times \sqrt{\text{Lead Time}} \quad (Z = 1.65 \text{ для 95\% уровня сервиса})$$
$$\text{Net Requirement} = \max(0, \text{Demand during Lead Time} + \text{Safety Stock} - \text{Current Stock} - \text{Goods In Transit})$$

### 2. Учёт ограничений поставщиков (MOQ и квант упаковки)
- Если $\text{Net Requirement} > 0$ и задан $\text{MOQ}$: $\text{Order} = \max(\text{Net Requirement}, \text{MOQ})$.
- Если задана кратность упаковки/бухты ($\text{Package Size} > 1$): $\text{Order} = \lceil \frac{\text{Order}}{\text{Package Size}} \rceil \times \text{Package Size}$.

### 3. Фильтрация разовых выбросов (Robust MAD)
Алгоритм использует медианное абсолютное отклонение (Median Absolute Deviation, MAD) вместо чувствительного к выбросам стандартного отклонения:
$$\text{MAD} = \text{median}(|x_i - \text{median}(X)|), \quad \text{Modified Z} = 0.6745 \times \frac{x_i - \text{median}(X)}{\text{MAD}}$$
Разовые гигантские оптовые партии (например, заказ на 4800 м от `CLNT-VIP-BIG-PROJECT`) исключаются из прогнозирования регулярного спроса, но сохраняются в журнале аномалий (**Audit Trail**) без потери данных.

### 4. Реконструкция упущенного спроса (Stockout Compensation)
Периоды обнуления остатков (дефицит товара) не снижают прогноз. Система сопоставляет даты дефицита и восстанавливает упущенный объём продаж на основе спроса в смежные обеспеченные периоды.

### 5. Сезонность и тренд
- Выявление внутринедельной и помесячной сезонности (например, пик светотехники +65% в зимние месяцы и строительный пик кабельной продукции летом).
- Оценка долгосрочного тренда спроса (MoM / YoY).

### 6. Учёт товаров в пути (In-Transit) и бюджета (KZT)
- Все размещённые на заводах заказы в пути вычитаются из текущей потребности.
- Для каждой строки и поставщика рассчитывается общая сумма закупки в казахстанских тенге (**₸ KZT**).

---

## 🧪 Тестирование

Комплексный набор автоматических тестов проверяет математику и валидацию:

```powershell
cd backend
pytest
```

**Покрытие тестов (`tests/test_replenishment.py`):**
1. Влияние текущих остатков на снижение объёма закупки.
2. Корректное вычитание товаров в пути (In-Transit).
3. Изоляция выбросов с сохранением в реестре аудита.
4. Гарантия неотрицательности рекомендаций.
5. Соблюдение квантов упаковки и минимальной партии (MOQ).
6. Восстановление упущенного спроса при дефиците.
7. Нормализация русскоязычных заголовков партнёра (Артикул, Количество, Склад и т.д.).
8. Корректный расчёт бюджета в KZT.

---

## 🔌 API Endpoints

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| `GET` | `/health` | Проверка жизнеспособности сервиса |
| `POST` | `/api/data/load-ekt` | Загрузка и расчёт реального датасета ТОО «Электрокомплект» |
| `POST` | `/api/data/upload-workbook` | Загрузка единой 5-листовой книги Excel (.xlsx) |
| `POST` | `/api/data/upload/{dataset}` | Загрузка отдельного датасета (sales, stock, transit, suppliers, stockouts) |
| `POST` | `/api/data/demo` | Загрузка синтетического сценария |
| `POST` | `/api/recommendations/calculate` | Перерасчёт с настраиваемыми параметрами (Z, threshold, safety days) |
| `GET` | `/api/recommendations` | Получение списка рекомендаций с фильтрами |
| `GET` | `/api/analytics/{sku}` | Детализированные точки спроса, прогноз и дефицит для графика |
| `GET` | `/api/outliers` | Реестр выявленных аномалий и выбросов |
| `POST` | `/api/orders/{id}/adjust` | Ручная корректировка количества закупщиком |
| `POST` | `/api/orders/{id}/approve` | Утверждение заказа в производство/закупку |
| `GET` | `/api/orders/export` | Экспорт итогового плана закупок в Excel / CSV |
