FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TERM=xterm
# Playwright configuratie
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome-stable
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

# Installeer system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    google-chrome-stable \
    fonts-freefont-ttf \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-symbola \
    fonts-noto \
    fonts-freefont-ttf \
    xvfb \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Kopieer requirements en installeer Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Configureer Playwright
RUN mkdir -p /ms-playwright \
    && playwright install --with-deps chromium

# Kopieer de rest van de applicatie
COPY . .

# Expose de port
EXPOSE ${PORT:-8000}

# Start script maken
RUN echo '#!/bin/bash\n\
xvfb-run --server-args="-screen 0 1280x1024x24" \
uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} \
--workers 1 --timeout-keep-alive 75' > /start.sh \
&& chmod +x /start.sh

# Start de applicatie
CMD ["/start.sh"] 