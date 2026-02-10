FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY poisonarr/ ./poisonarr/
COPY entrypoint.py .

# Install browsers (chromium only for smaller image)
RUN playwright install chromium

# Create non-root user for runtime
RUN useradd -m -u 1000 poisonarr

# Set ownership
RUN chown -R poisonarr:poisonarr /app

USER poisonarr

CMD ["python", "-u", "entrypoint.py"]
