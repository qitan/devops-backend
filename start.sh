#!/bin/bash

touch logs/daphne.log
daphne devops_backend.asgi:application -b 0.0.0.0 -p 8080 --access-log logs/daphne.log
