# syntax=docker/dockerfile:1
FROM python:3.12

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for fonts and other packages
RUN apt-get update && apt-get install -y \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fontconfig \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# install python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install assets (fonts and flags)
# BuildKit cache mounts persist downloaded files across rebuilds on the same host,
# so flags and fonts are only downloaded once instead of on every rebuild.
RUN mkdir -p static/flags static/logos
RUN --mount=type=cache,target=/cache/flags \
    --mount=type=cache,target=/cache/fonts \
    python3 install_assets.py \
        --flags-dir /cache/flags \
        --fonts-dir /cache/fonts && \
    cp -rp /cache/flags/. static/flags/ && \
    cp -rp /cache/fonts/. /usr/local/share/fonts/

# Update font cache
RUN fc-cache -fv

# Make startup script executable
RUN chmod +x run-app.sh

# Start Server
EXPOSE 5005
CMD ["./run-app.sh"]
