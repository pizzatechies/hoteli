FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --no-input

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --no-input && python manage.py ensure_admin && gunicorn hoteli.wsgi --bind 0.0.0.0:${PORT} --workers 3 --timeout 60"]
