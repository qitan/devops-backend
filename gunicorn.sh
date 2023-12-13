#!/bin/bash

touch logs/gunicorn.log
gunicorn devops_backend.wsgi -b 0.0.0.0:8080 -t 60 --thread 20 --access-logfile logs/gunicorn.log