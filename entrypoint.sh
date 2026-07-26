#!/bin/sh

echo "Waiting for MySQL..."

while ! nc -z database 3306; do
    sleep 1
done

echo "MySQL is ready."

python manage.py migrate --noinput

python manage.py collectstatic --noinput

exec "$@"