# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# The private generation engine is installed here in deployments that have
# access to the private index. Absent from the public image, which is why
# ctgan_pipeline.py falls back to the bootstrap generator.
#
#   ARG PRIVATE_INDEX_URL
#   RUN --mount=type=secret,id=pip_netrc,target=/root/.netrc \
#       pip install --extra-index-url "$PRIVATE_INDEX_URL" pretrial-synthecore-private
# ---------------------------------------------------------------------------

COPY app ./app

RUN useradd --create-home --uid 10001 synthecore && chown -R synthecore:synthecore /srv
USER synthecore

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health').status==200 else 1)"

# The worker runs this same image with the command overridden in compose and
# in the ECS task definition. One image, two roles, no drift between the code
# the API validates against and the code the worker runs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
