# docker-histo/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Copier le template HTML
COPY ./docker-histo/index_template.html /app/

# Copier le script Python
COPY ./docker-histo/start.py /app/

# Rendre le script exécutable
RUN chmod +x /app/start.py

EXPOSE 8089

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request, sys; \
  sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8089/').status == 200 else sys.exit(1)"


CMD ["python3", "/app/start.py"]