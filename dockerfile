# Use the official Python image from the Docker Hub
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install any dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Remove build dependencies
RUN apt-get purge -y build-essential

# Copy the content of the local src directory to the working directory
COPY . .

# Expose the port (optional if not already exposed)
EXPOSE 8000

# Command to run on container start
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]
