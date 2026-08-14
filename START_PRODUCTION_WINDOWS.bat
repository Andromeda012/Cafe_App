@echo off
setlocal
if "%NOIR_SECRET_KEY%"=="" echo UYARI: NOIR_SECRET_KEY ayarlanmadi.
python -m waitress --listen=0.0.0.0:8000 wsgi:app
