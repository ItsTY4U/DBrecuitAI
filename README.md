# DBRecruitAI - Recruitment Screening System

An AI-powered web recruitment screening system built with **Django**. DBRecruitAI streamlines hiring with automated resume parsing, candidate scoring, AI-driven video interview evaluations, and real-time application tracking.

---

## Tech Stack

- **Framework**: Python 3.12+, Django 6.x, Django REST Framework
- **Databases**:
  - **SQLite** (Default & zero-config for local development)
  - **PostgreSQL / Supabase** (Production & Realtime events)
  - **MySQL 8.x** (Supported alternative)
- **AI & Cloud Services**:
  - Google Gemini API (Video interview & resume evaluation)
  - Supabase Realtime (Live applicant tracking)
  - Cloudflare R2 (Media / file storage via S3 API)
- **Package & Environment Management**: `uv` (Recommended) or standard `pip` / `venv`
- **Frontend**: Django Templates, HTML5, CSS3, JavaScript
- **CI / Testing**: GitHub Actions, pytest-django, flake8, black, isort

---

## Project Structure

```
DBrecuitAI/
├── accounts/             # User authentication, profiles & Google OAuth
├── config/               # Django project settings, URLs, WSGI/ASGI
├── hr/                   # HR & recruiter dashboard, candidate reviews
├── jobs/                 # Job listings, job postings, candidate applications
├── main/                 # Landing pages and core site navigation
├── track_application/    # Real-time candidate application tracker (Supabase)
├── video_interview/      # AI video interview screening & evaluation (Gemini)
├── static/               # Static files (CSS, JS, images, icons)
├── templates/            # HTML templates
├── requirements.txt      # Production dependencies
├── requirements-dev.txt  # Development, linting & testing tools
├── .env.example          # Template for local environment variables
├── docker-compose.yml    # Docker Compose setup (web + database)
├── Dockerfile            # Container build configuration
├── pytest.ini            # Pytest configuration
├── setup.cfg             # Flake8 configuration
└── manage.py             # Django management CLI
```

---

## Local Setup

Follow the steps below to run DBRecruitAI locally on your machine.

### 1. Clone the Repository

```bash
git clone https://github.com/ItsTY4U/DBrecuitAI.git
cd DBrecuitAI
```

---

### 2. Set Up Virtual Environment & Install Dependencies

You can use either **`uv`** (fastest and recommended) or standard **`python -m venv` / `pip`**.

#### Option A: Using `uv` (Recommended)

[`uv`](https://github.com/astral-sh/uv) is an extremely fast Python package manager and project tool written in Rust.

**1. Install `uv` (if not already installed):**

- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  *Or via winget:*
  ```powershell
  winget install --id=astral-sh.uv -e
  ```

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  *Or via Homebrew:*
  ```bash
  brew install uv
  ```

- **Via pip:**
  ```bash
  pip install uv
  ```

**2. Create a virtual environment:**

```bash
uv venv
```
*(Optionally specify a Python version: `uv venv --python 3.12`)*

**3. Activate the virtual environment:**

- **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Windows (Command Prompt):**
  ```cmd
  .venv\Scripts\activate.bat
  ```
- **macOS / Linux / Git Bash:**
  ```bash
  source .venv/bin/activate
  ```

**4. Install dependencies:**

```bash
uv pip install -r requirements-dev.txt
```

> **Tip with `uv`**: You can also prefix any command with `uv run` to run it directly without manually activating the virtual environment, e.g.:
> ```bash
> uv run python manage.py migrate
> uv run python manage.py runserver
> ```

---

#### Option B: Using Standard Python (`venv` + `pip`)

If you prefer using standard Python tools:

**1. Create and activate a virtual environment:**

```bash
# Create virtual environment
python -m venv .venv

# Activate:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate
```

**2. Install dependencies:**

```bash
pip install -r requirements-dev.txt
```

---

### 3. Configure Environment Variables

Create your local `.env` file from the provided `.env.example` template:

- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **Windows (CMD):**
  ```cmd
  copy .env.example .env
  ```
- **macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

---

### 4. Database Setup

DBRecruitAI supports **SQLite**, **PostgreSQL / Supabase**, and **MySQL**.

#### A. SQLite Setup (Recommended for Quick Local Development)

SQLite requires **zero external installation or background database servers**. Django handles file creation and migrations automatically.

In your `.env` file, configure the database section:

```env
# ==========================================
# Database Configuration (SQLite)
# ==========================================
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3

# Core Django Settings
DJANGO_SECRET_KEY=django-insecure-local-dev-key
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

*(Note: `DB_ENGINE=sqlite` is also accepted as a convenient shorthand.)*

When you run migrations in Step 5, Django will automatically generate the `db.sqlite3` database file in the project root.

---

#### B. MySQL Setup (Optional)

If you prefer using MySQL locally:

1. Create a database in your local MySQL instance:
   ```sql
   CREATE DATABASE DBrecruitAI_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
2. In your `.env` file, configure:
   ```env
   DB_ENGINE=django.db.backends.mysql
   DB_NAME=DBrecruitAI_database
   DB_USER=root
   DB_PASSWORD=your_mysql_password
   DB_HOST=127.0.0.1
   DB_PORT=3306
   ```

---

#### C. PostgreSQL / Supabase (Optional)

To connect to a local PostgreSQL database or remote Supabase instance:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
DB_PORT=5432
```

---

### 5. Run Database Migrations

Apply the database schema:

- **Using `uv`:**
  ```bash
  uv run python manage.py migrate
  ```
- **Using standard Python (venv active):**
  ```bash
  python manage.py migrate
  ```

---

### 6. Create Superuser (Admin Account)

Create an administrator account to access the Django admin portal (`/admin/`):

- **Using `uv`:**
  ```bash
  uv run python manage.py createsuperuser
  ```
- **Using standard Python:**
  ```bash
  python manage.py createsuperuser
  ```

Follow the interactive prompts to enter a username, email, and password.

---

### 7. Start the Development Server

Launch the local web server:

- **Using `uv`:**
  ```bash
  uv run python manage.py runserver
  ```
- **Using standard Python:**
  ```bash
  python manage.py runserver
  ```

Once running, access the application in your browser:
- **Application**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Django Admin Portal**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## Running Tests

Run the test suite using `test` or `pytest`:

```bash
# Using uv
uv run python manage.py test

# Or using standard python
python manage.py test
```

### Running with Coverage

```bash
# With uv
uv run coverage run manage.py test
uv run coverage report

# Standard python
coverage run manage.py test
coverage report
```

---

## Code Quality & Formatting

Format and lint the codebase before submitting changes:

```bash
# With uv
uv run black .
uv run isort .
uv run flake8 .

# Standard python
black .
isort .
flake8 .
```

---

## Running with Docker (Alternative)

To spin up the web app and a MySQL database container simultaneously:

```bash
docker compose up --build
```

The application will be accessible at [http://127.0.0.1:8000/](http://127.0.0.1:8000/).