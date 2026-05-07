FROM python:3.11

WORKDIR /app

# Install git + build tools
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install yfinance pandas-ta pandas requests schedule nsepython && \

COPY . .

CMD ["python", "signal_engine_7.py"]