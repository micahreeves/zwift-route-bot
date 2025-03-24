FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*
    
# Create data directory and set proper permissions
RUN mkdir -p /app/data && \
    chmod -R 777 /app/data

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY zwiftroutebot.py .
COPY zwift_routes.json .
COPY zwift_koms.json .
COPY zwift_sprint_segments.json .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Command to run the application
CMD ["python", "zwiftroutebot.py"]
