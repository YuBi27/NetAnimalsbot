FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

CMD ["uvicorn", "bot.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--timeout-keep-alive", "30", \
     "--timeout-graceful-shutdown", "10", \
     "--log-level", "info"]
