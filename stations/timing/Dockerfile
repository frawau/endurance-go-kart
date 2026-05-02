FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir websockets toml pyserial-asyncio

COPY . .

RUN chmod +x run-timing.sh

ENTRYPOINT ["./run-timing.sh"]
