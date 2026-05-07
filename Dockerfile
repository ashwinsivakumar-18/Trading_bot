FROM python:3.11-slim

WORKDIR /app

# Install git + build tools
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install yfinance pandas requests schedule nsepython && \
    pip install git+https://github.com/twopirllc/pandas-ta.git

COPY . .

CMD ["python", "signal_engine_7.py"]