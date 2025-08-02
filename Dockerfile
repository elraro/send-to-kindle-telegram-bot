FROM python:3.12-alpine

EXPOSE 8080

COPY requirements.txt /
RUN pip3 install -r requirements.txt

WORKDIR /app

ADD app /app

ENTRYPOINT ["python3", "bot.py"]