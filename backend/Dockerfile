FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend ./backend
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["uvicorn", "finagent.api:app", "--host", "0.0.0.0", "--port", "8000"]
