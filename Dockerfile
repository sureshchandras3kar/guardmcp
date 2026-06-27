FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY policies/ policies/

RUN mkdir -p logs

# Fix 1: agent identity is set by the operator via env var, never by AI
ENV GUARDMCP_AGENT=default-agent
ENV GUARDMCP_MONGODB_URI=mongodb://mongo:27017
ENV GUARDMCP_MONGODB_DATABASE=mydb
ENV GUARDMCP_TRANSPORT=streamable-http
ENV GUARDMCP_HOST=0.0.0.0
ENV GUARDMCP_PORT=8000
ENV GUARDMCP_APPROVAL_PORT=8001

EXPOSE 8000 8001

CMD ["python", "-m", "guardmcp"]
