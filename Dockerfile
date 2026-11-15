FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NAME_STATE_DIR=/state
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py launcher.py ./
COPY src ./src
COPY config ./config
COPY templates ./templates
RUN useradd -m app && mkdir /state && chown app /state
USER app
EXPOSE 8501
CMD ["python", "launcher.py"]
