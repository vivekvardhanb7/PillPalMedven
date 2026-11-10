FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install -r requirements.txt
RUN groupadd --system app && useradd --system --uid 10001 --gid app app \
    && mkdir -p /app/instance \
    && chown app:app /app/instance

USER app

EXPOSE 8080

CMD ["waitress-serve", "--listen=0.0.0.0:8080", "app:app"]