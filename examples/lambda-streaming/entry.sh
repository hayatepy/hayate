#!/bin/sh
set -eu

if [ -z "${AWS_LAMBDA_RUNTIME_API:-}" ]; then
  exec /usr/local/bin/aws-lambda-rie /var/lang/bin/python3.14 /var/task/bootstrap.py
fi

exec /var/lang/bin/python3.14 /var/task/bootstrap.py
