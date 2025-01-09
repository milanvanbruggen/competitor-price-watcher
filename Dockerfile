FROM python:3.11-slim

# Chrome en dependencies installeren
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Voor Streamlit versie
CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0

# Voor API versie
# CMD uvicorn api:app --host 0.0.0.0 --port $PORT 