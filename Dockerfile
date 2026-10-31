# Clearwake inside the merchant's network. Standard library only: no packages are installed.
# Keys are never copied into the image (.dockerignore); compose passes the sandbox names at run time.
FROM python:3.13-slim
WORKDIR /app
COPY . /app
RUN useradd --create-home clearwake && mkdir -p /app/data && chown -R clearwake /app/data
USER clearwake
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "scripts/cases.py"]
