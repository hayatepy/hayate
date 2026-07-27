# AWS's Python image supplies CPython, the Runtime Interface Client, and the
# local Runtime Interface Emulator. Hayate replaces only the handler loop so
# Python can use Lambda's streaming Runtime API without ASGI or a web adapter.
FROM public.ecr.aws/lambda/python:3.14@sha256:d9fdb7a2ab12758852282d500ff6de488ddbf452d49cc0d7141165f4e9bc8cb6

COPY *.whl /tmp/hayate-wheelhouse/
RUN pip install \
      --no-cache-dir \
      --no-index \
      --find-links=/tmp/hayate-wheelhouse \
      /tmp/hayate-wheelhouse/hayate-*.whl \
    && rm -r /tmp/hayate-wheelhouse

COPY app.py bootstrap.py entry.sh ${LAMBDA_TASK_ROOT}/
RUN chmod +x ${LAMBDA_TASK_ROOT}/entry.sh

ENTRYPOINT ["/var/task/entry.sh"]
