# Minimal Celery demo app (TALOS-ja5). Broker = the RabbitMQ cluster; result backend +
# marker store = the Dragonfly (Redis) instance. A beat schedule fires demo.heartbeat every
# 15s; the task writes a marker key the Go flex util reads back to prove Celery is processing.
import os
import time

from celery import Celery
import redis

BROKER = os.environ["CELERY_BROKER_URL"]
BACKEND = os.environ["CELERY_RESULT_BACKEND"]
MARKER_KEY = os.environ.get("CELERY_MARKER_KEY", "celery:flex:done")

app = Celery("demo", broker=BROKER, backend=BACKEND)
app.conf.timezone = "UTC"
app.conf.beat_schedule = {
    "heartbeat": {"task": "demo.heartbeat", "schedule": 15.0},
}

_r = redis.from_url(BACKEND)


@app.task(name="demo.heartbeat")
def heartbeat():
    """Provisioned-topology job: stamp a marker so the flex util/integration test can see
    that the Celery worker (fed by RabbitMQ, backed by Dragonfly) actually ran a job."""
    _r.set(MARKER_KEY, str(int(time.time())))
    return "ok"
