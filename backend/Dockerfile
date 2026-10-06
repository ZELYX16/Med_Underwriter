# MedUnderwrite AI — Backend Dockerfile
# Persona B (Day 2 PM) finalises this.
# TODO: fill in per developer guide Section 4.6

FROM python:3.11-slim

# TODO: Install system deps (libpq-dev, gcc)
# TODO: COPY requirements.txt + pip install
# TODO: COPY app code
# TODO: CMD uvicorn app.main:app --host 0.0.0.0 --port 8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
