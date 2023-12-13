## 环境依赖

* Python 3.9
* MySQL 8.0.25
* ElasticSearch 7.14.0
* Harbor v1.7

## Jenkins

### plugins:

* http request
* docker
* Docker Pipeline

### Jenkins所在机器需要安装如下软件

python3

> 依赖  
> pycryptodome==3.9.8  
> xmltodict==0.12.0  
> requests==2.25.0  
> ansible==2.10.4

## 开发环境

部署MySQL

```shell script
docker run -it --name mysqldb -p 43306:3306 -e MYSQL_ROOT_PASSWORD=password -e MYSQL_DATABASE=ydevopsdb -e MYSQL_USER=devops -e MYSQL_PASSWORD=ops123456 -d mysql:8.0.18 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

部署redis

```shell script
docker run -d --name redis -p 6379:6379 daocloud.io/redis --requirepass 'ops123456'
```

部署ElasticSearch

```python
docker run --name es -p 9200:9200 -p 9300:9300 -e "discovery.type=single-node" -e ES_JAVA_OPTS="-Xms512m -Xmx512m" -d elasticsearch:7.14.0
```

部署GitLab

```shell script
docker run -d --name gitlab -p 8090:8090 -p 2222:2222 gitlab/gitlab-ce
```

## 依赖安装

mysqlclient:

* debian系

```shell script
sudo apt install mysql-client-8.0 libmysqlclient-dev python3-dev python-dev libldap2-dev libsasl2-dev libssl-dev
```

* redhat系

```shell script
--
```

openldap:

* debian系

```shell script
sudo apt-get install libsasl2-dev python-dev libldap2-dev libssl-dev
```

* redhat系:

```shell script
yum install python-devel openldap-devel
```

## ansible依赖

```shell script
yum -y install sshpass
```

## RBAC

### 获取权限

```python
from rest_framework.schemas.openapi import SchemaGenerator
generator = SchemaGenerator(title='DevOps API')
data = []
try:
    generator.get_schema()
except BaseException as e:
    print(str(e))
finally:
    data = generator.endpoints
```

### 初始化配置

```python
python manage.py migrate
# 注释好之后再执行初始化数据
python manage.py initdata --help
```

## Nginx配置

```
server {
    listen 9000;
    server_name localhost;
    error_log /usr/local/nginx/logs/devops_error.log;
    #access_log off;
    access_log /usr/local/nginx/logs/devops_access.log;
    error_page 404 /404.html;
    location = /404.html {
        root /etc/nginx;
    }
    error_page 500 502 503 504 /500.html;
    location = /500.html {
        root /etc/nginx;
    }
    underscores_in_headers on;
    client_max_body_size   2048m;

    location / {
        root /data/frontend/dist;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }
    location ~ ^/(admin|api) {
        proxy_pass http://localhost:8000;
        proxy_connect_timeout    1200s;
        proxy_read_timeout       1200s;
        proxy_send_timeout       1200s;
        proxy_set_header Host $host:$server_port;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## 表关联及报表展示模型配置

模型定义了扩展元数据

* 表是否可关联由related控制
* 报表是否可展示由dashboard控制

```python
    class ExtMeta:
        related = False
        dashboard = False
```
