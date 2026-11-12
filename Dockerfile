FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Madrid
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -m appuser && mkdir -p /data && chown appuser /data
USER appuser
EXPOSE 8000
# Un solo worker: el planificador de avisos vive dentro del proceso y no debe duplicarse.
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1","--proxy-headers","--forwarded-allow-ips=172.16.0.0/12"]
