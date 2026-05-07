FROM python:3.11-slim

WORKDIR /app

# Install git + build tools
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install yfinance pandas pandas-ta requests schedule nsepython

COPY . .

CMD ["python", "signal_engine_7.py"]