FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY cookflow_agent/requirements.txt cookflow_agent/requirements.txt
RUN pip install --no-cache-dir -r cookflow_agent/requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn[standard] jinja2 python-multipart

# Copy application code
COPY cookflow_agent/ cookflow_agent/
COPY api/ api/

# Run FastAPI with uvicorn
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
