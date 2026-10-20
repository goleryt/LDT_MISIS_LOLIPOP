ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM ${PYTHON_IMAGE}
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY ml_combined/requirements-sensor-fire.txt /requirements-sensor-fire.txt
RUN pip install --no-cache-dir -r /requirements-sensor-fire.txt
COPY backend/requirements.txt /requirements-backend.txt
RUN pip install --no-cache-dir -r /requirements-backend.txt
COPY ml_combined /opt/combined
RUN python /opt/combined/unpack.py && useradd --uid 10001 --create-home app \
    && install -d -o app -g app -m 0700 /work
COPY backend /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TMPDIR=/work SCENARIO_COMPUTE_SCRIPT=/opt/combined/compute.py
# Disabled unless explicitly enabled; does not start the gas scheduler.
CMD ["python", "-m", "scripts.scenario_scheduler"]
