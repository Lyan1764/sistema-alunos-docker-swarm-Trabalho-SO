# Imagem base enxuta com Python
FROM python:3.12-slim

# Não gerar .pyc e não "bufferizar" os logs (aparecem na hora no `docker logs`)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Copia só o requirements e instala as dependências.
#    Assim o Docker reaproveita essa camada em cache enquanto o requirements não mudar.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Copia o código da aplicação
COPY app.py .
COPY templates ./templates

# Boa prática: não executar como root dentro do container
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8000

# O Docker marca o container como "healthy" se /health responder
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# Servidor de produção (gunicorn) em vez do servidor de desenvolvimento do Flask
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "30", "app:app"]
