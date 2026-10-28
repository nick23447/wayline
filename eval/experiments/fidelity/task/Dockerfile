# Dummy task for the fidelity experiments. Build from the repo root:
#   sudo docker build -f eval/experiments/fidelity/task/Dockerfile \
#     -t localhost:5000/wl-fidelity-task:latest .
FROM python:3.11-slim
WORKDIR /app
# The wl SDK imports pyzmq for its zeromq transport.
RUN pip install --no-cache-dir pyzmq
COPY sdk/python/wl ./wl
COPY eval/experiments/fidelity/task/task.py .
CMD ["python", "task.py"]
