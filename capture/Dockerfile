FROM python:3.12-slim

# adb (USB デバイス接続) + Tesseract OCR のインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    tesseract-ocr \
    # opencv-python-headless の依存ライブラリ
    libglib2.0-0 \
    libgl1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "ocr.py"]
