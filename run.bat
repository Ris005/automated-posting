@echo off
REM One-command setup + run (Windows)
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -q -r requirements-dev.txt
)
if not exist .env copy .env.example .env
echo Swagger UI -^> http://localhost:4000/docs
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 4000
