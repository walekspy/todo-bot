FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY get_google_token.py .

VOLUME /app/data
VOLUME /app/credentials

CMD ["python", "-m", "bot.main"]
