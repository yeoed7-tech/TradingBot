FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-deps . && mkdir -p /app/data/database && useradd --create-home researcher && chown -R researcher:researcher /app
USER researcher
ENV MPLCONFIGDIR=/tmp/matplotlib
CMD ["python", "-m", "trading_bot.main", "demo", "--out", "/app/reports/demo"]
