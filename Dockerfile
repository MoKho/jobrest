# Use an official lightweight Python image.
FROM python:3.10-slim

# Set environment variables
# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED True

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file and install them
# This step is separated to take advantage of Docker's layer caching
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Specify the command to run on container startup.
# Cloud Run will set the PORT environment variable.
# We tell Gunicorn to bind to all network interfaces (0.0.0.0)
# on the port specified by the PORT variable.
# main:app tells Gunicorn to look for an object named 'app' in the 'main.py' file.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "main:app"]