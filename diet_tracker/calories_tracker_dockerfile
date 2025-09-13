FROM python:3.11-slim

WORKDIR /app

#Install Python dependencies
RUN pip install --no-cache-dir pipenv
COPY Pipfile Pipfile.lock .
RUN pipenv install --system --deploy
