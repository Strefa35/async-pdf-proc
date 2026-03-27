FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn

COPY mistral_mock.py /app/mistral_mock.py

EXPOSE 8001

CMD ["uvicorn", "mistral_mock:app", "--host", "0.0.0.0", "--port", "8001"]
