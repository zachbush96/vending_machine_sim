FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps: tini for clean signal handling
RUN apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Your code
COPY . .

# Small runner that launches both scripts
COPY .docker/runner.sh /usr/local/bin/runner.sh
RUN chmod +x /usr/local/bin/runner.sh

EXPOSE 5000 8000

# tini forwards SIGTERM/SIGINT to both children
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/usr/local/bin/runner.sh"]
