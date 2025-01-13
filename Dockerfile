FROM python:3.11-slim

WORKDIR /app

# Installeer system dependencies voor Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y \
    google-chrome-stable \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-freefont-ttf \
    libxss1 \
    && rm -rf /var/lib/apt/lists/*

# Kopieer requirements eerst voor betere caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installeer Playwright browsers
RUN playwright install chromium
RUN playwright install-deps

# Kopieer de rest van de applicatie
COPY . .

# Expose de poort
EXPOSE 8000

# Start de applicatie
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"] 