FROM python:3.12-slim
WORKDIR /app
COPY app.py import_data.py auth.py container_start.py ./
COPY static ./static
EXPOSE 8765
CMD ["python", "container_start.py"]
