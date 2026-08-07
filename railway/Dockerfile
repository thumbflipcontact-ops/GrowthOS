FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e backend -e plugins/dummy -e plugins/reddit -e plugins/twitter -e plugins/linkedin

WORKDIR /app/backend

CMD ["python", "-c", "raise SystemExit('Set a Start Command for this service.')"]
