FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the agent code
COPY . .

# The command that will run daily against their 100 test companies
CMD ["python", "main.py"]
