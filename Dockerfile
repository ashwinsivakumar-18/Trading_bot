FROM python:3.11

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    gcc \
    build-essential

RUN pip install --upgrade pip

RUN pip install \
    yfinance \
    pandas \
    requests \
    schedule \
    nsepython \
    numpy \
    pandas-ta-openbb

COPY . .

CMD ["python", "signal_engine_7.py"]