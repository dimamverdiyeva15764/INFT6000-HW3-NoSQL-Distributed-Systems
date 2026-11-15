FROM python:3.11-slim

# Pure-Python driver install: avoids compiling C extensions on images without a toolchain.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CASS_DRIVER_NO_CYTHON=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /work
