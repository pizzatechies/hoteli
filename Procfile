release: python manage.py migrate --no-input && python manage.py ensure_admin
web: gunicorn hoteli.wsgi --workers 3 --timeout 60 --log-file -
