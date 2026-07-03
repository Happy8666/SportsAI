# Dockerfile для SportsAI Telegram бота
# Используем легковесный образ с Python + Tesseract OCR

FROM python:3.11-slim

# Установка системных зависимостей: OpenCV (libgl) и Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs

CMD ["python", "main.py"]
