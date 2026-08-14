# Cafe App - CapRover Deployment

This repository is deployed as ONE CapRover application/container.

## Container
- Base image: Python 3.12 slim
- WSGI: Waitress
- Container port: 8000
- Health endpoint: /health

## CapRover
The repository root must contain:
- captain-definition
- Dockerfile
- requirements.txt

In CapRover, set the application's HTTP Container Port to 8000.

## Important
The current application code in this package still uses its existing SQLite database layer.
If the production database should be the MySQL 8.0 database already prepared in Workbench, the database layer must be migrated to MySQL before production deployment.

Do not commit .env or database credentials. Configure secrets as CapRover environment variables.
