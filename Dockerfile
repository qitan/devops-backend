FROM python:3.9.14-slim-buster
LABEL maintainer="Charles Lai"

ARG APP
RUN mkdir -p /app/${APP} /data/nfs/web; apt update && apt -y install nginx libmariadb-dev-compat libmariadb-dev python3-dev python-dev libldap2-dev libsasl2-dev libssl-dev build-essential libffi-dev && apt -y autoclean
COPY requirements.txt /data/requirements.txt
COPY devops.conf /etc/nginx/sites-enabled/default

RUN pip install -r /data/requirements.txt -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com
COPY . /app/${APP}
ADD dist.tar.gz /app/${APP}/
WORKDIR /app/${APP}
RUN chmod +x *.sh

ENTRYPOINT ["supervisord", "-n", "-c", "daemon.conf"] 

