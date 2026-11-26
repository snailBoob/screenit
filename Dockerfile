FROM python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
LABEL org.opencontainers.image.version="1.1.7"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SCREENIT_BIND=0.0.0.0 SCREENIT_DATA=/data
WORKDIR /app
COPY requirements.txt .
COPY LICENSE .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
RUN groupadd --gid 10001 screenit && useradd --no-create-home --uid 10001 --gid 10001 screenit && mkdir /data && chown screenit:screenit /data
COPY src/ src/
ARG RUNTIME_USER=10001:10001
USER ${RUNTIME_USER}
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3).read()"
CMD ["python", "-m", "src.app"]
