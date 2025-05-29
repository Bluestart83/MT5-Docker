FROM python:3.13-slim

WORKDIR /app
COPY ./docker-histo/index.html .

EXPOSE 8089

CMD ["python3", "-m", "http.server", "8089"]
