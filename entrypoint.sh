#!/bin/sh

echo "Waiting for MySQL..."

while ! nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
done

echo "MySQL is ready."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"