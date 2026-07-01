# Recruitment Screening System

A web-based recruitment screening system. Backend built with **Django** and **MySQL**.

## Tech stack

- Python 3.12+
- Django 5.2+/6.x
- MySQL 8.x
- Django REST Framework (for the API layer)
- GitHub Actions (CI/CD)

## Project structure

```
recruitment-screening-system/
├── config/              # Django project settings, URLs, WSGI/ASGI
├── screening/           # Main app (models, views, tests)
├── requirements.txt     # Production dependencies
├── requirements-dev.txt # + linting/testing tools
├── .env.example         # Template for local environment variables
├── pytest.ini           # pytest-django config
├── setup.cfg            # flake8 config
└── .github/workflows/   # CI pipeline
```

## Local setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd recruitment-screening-system

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements-dev.txt   # includes prod deps + lint/test tools
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your local MySQL credentials and a real `DJANGO_SECRET_KEY`.

### 4. Set up MySQL

Create the database (adjust user/password as needed):

```sql
CREATE DATABASE DBrecruitAI_database CHARACTER SET utf8mb4;
```

> Tip: if you don't want to install MySQL locally yet, set `DB_ENGINE=sqlite` in `.env`
> to fall back to SQLite for quick local development.

### 5. Run migrations and start the server

```bash
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin access
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

## Running tests

```bash
python manage.py test
# or, with coverage:
coverage run manage.py test && coverage report
```

## Linting & formatting

```bash
flake8 .
black .
isort .
```