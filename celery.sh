#!/bin/bash
export PYTHONOPTIMIZE=1

if [ $# -ne 0 ];then
  queue=$1
elif [ ! -z $QUEUE ];then
  queue=$QUEUE
else
  queue='celery'
fi

echo "Current Queue: $queue"

celery -A celery_tasks worker --loglevel=info --without-gossip --without-mingle --without-heartbeat -E -Q $queue
