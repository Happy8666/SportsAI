# SportsAI Bot — инструкция по деплою на Render.com

## Предварительные требования

1. Аккаунт на [Render.com](https://render.com) (регистрация через GitHub)
2. Репозиторий на GitHub с кодом бота
3. Токен Telegram бота (получить у @BotFather)
4. API-ключ Football-Data.org (зарегистрироваться на https://www.football-data.org/)

## Локальная проверка

```bash
# 1. Установите зависимости
pip install -r requirements.txt

# 2. Установите Tesseract OCR (если ещё не установлен)
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus
# macOS: brew install tesseract

# 3. Создайте файл .env из примера
copy .env.example .env
# Заполните TELEGRAM_BOT_TOKEN и FOOTBALL_DATA_API_KEY

# 4. Запустите бота
python main.py
```

## Деплой на Render.com

### Способ 1: Через render.yaml (Blueprint)

1. Залейте код в GitHub-репозиторий
2. Замените `YOUR_USERNAME` в `render.yaml` на ваш GitHub-username
3. На Render.com: Dashboard → Blueprints → New Blueprint Instance
4. Подключите репозиторий
5. Заполните переменные окружения (TELEGRAM_BOT_TOKEN, FOOTBALL_DATA_API_KEY)

### Способ 2: Вручную через Dashboard

1. Render.com → New → Web Service
2. Подключите GitHub-репозиторий
3. Настройки:
   - **Name**: sportsai-bot
   - **Environment**: Docker
   - **Branch**: main
   - **Plan**: Free
4. Environment Variables:
   - `TELEGRAM_BOT_TOKEN` = ваш_токен
   - `FOOTBALL_DATA_API_KEY` = ваш_ключ
   - `LOG_LEVEL` = INFO
5. Health Check Path: `/`
6. Нажмите "Create Web Service"

### Важно для бесплатного плана

- Бесплатный план Render **засыпает** после 15 минут бездействия
- Первый запрос после сна может занять до 30 секунд (холодный старт)
- Лимит: 750 часов в месяц (достаточно для 24/7)
- База SQLite будет **сбрасываться** при перезапуске (бесплатный диск — ephemeral)
- Для постоянной БД нужно подключить Render Disk (платно) или внешнюю БД

### Альтернатива: UptimeRobot для предотвращения сна

1. Зарегистрируйтесь на [UptimeRobot](https://uptimerobot.com) (бесплатно)
2. Добавьте монитор типа HTTP(s) с URL вашего Render-сервиса
3. Интервал проверки: 5 минут
4. Это будет держать сервис "тёплым" и предотвращать засыпание

## Переменные окружения (на Render)

| Переменная | Описание | Обязательно |
|-----------|----------|-------------|
| TELEGRAM_BOT_TOKEN | Токен бота от @BotFather | Да |
| FOOTBALL_DATA_API_KEY | API-ключ Football-Data.org | Да |
| LOG_LEVEL | Уровень логирования (DEBUG/INFO/WARNING) | Нет (по умолчанию INFO) |
| DB_PATH | Путь к файлу БД | Нет (по умолчанию bot_history.db) |
| PORT | Порт health-check сервера | Нет (Render задаёт автоматически) |

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и инструкция |
| `/help` | Подробная справка |
| `/predict Team1 Team2` | Прогноз на матч |
| 📸 Отправить фото | OCR-распознавание скриншота → прогноз |
| `/history` | Последние 5 запросов пользователя |

## Устранение неполадок

**Бот не отвечает:**
- Проверьте логи на Render.com (Dashboard → сервис → Logs)
- Убедитесь, что токен бота валиден
- Проверьте, что сервис не "спит" (Dashboard → статус)

**OCR не распознаёт команды:**
- Убедитесь, что на скриншоте чётко видны названия
- Используйте ручной ввод `/predict Команда1 Команда2`

**Команда не найдена:**
- Попробуйте другие варианты названия (например, "FC Barcelona" вместо "Barcelona")
- Проверьте, что команда есть в Football-Data.org
