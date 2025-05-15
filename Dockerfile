# ###############################################################
# #                                                             #
# #                  Spotify Downloader Bot                     #
# #                  Copyright © ftmdeveloperz                  #
# #                       #ftmdeveloperz                        #
# #                                                             #
# ###############################################################

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    libpq-dev \
    curl \
    gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
RUN npm install

# Expose port
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Command to run the application (will be overridden by docker-compose)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "main:app"]
