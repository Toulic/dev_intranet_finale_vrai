FROM python:3.10-slim
ENV PYTHONUNBUFFERED=1 
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p static/uploads/cours && chmod 777 static/uploads/cours
CMD ["python", "app.py"]