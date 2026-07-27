# AWS documents this image as including the Python runtime, Runtime Interface
# Client, and Runtime Interface Emulator. The multi-architecture manifest was
# resolved and pinned on 2026-07-27.
FROM public.ecr.aws/lambda/python:3.14@sha256:d9fdb7a2ab12758852282d500ff6de488ddbf452d49cc0d7141165f4e9bc8cb6

COPY *.whl /tmp/hayate-wheelhouse/
RUN pip install \
      --no-cache-dir \
      --no-index \
      --find-links=/tmp/hayate-wheelhouse \
      /tmp/hayate-wheelhouse/hayate-*.whl \
    && rm -r /tmp/hayate-wheelhouse

COPY app.py ${LAMBDA_TASK_ROOT}/app.py

CMD ["app.handler"]
