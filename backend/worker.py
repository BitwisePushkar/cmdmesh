import logging
from celery import Celery
from celery.signals import after_setup_logger
from backend.config import get_settings

def create_celery() -> Celery:
    settings = get_settings()
    broker_url = settings.redis_url.rstrip("/").rsplit("/", 1)[0] + "/1"
    result_backend = settings.redis_url.rstrip("/").rsplit("/", 1)[0] + "/2"
    app = Celery(
        "cmdmesh",
        broker=broker_url,
        backend=result_backend,
        include=["backend.tasks.email_tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_routes={
            "backend.tasks.email_tasks.*": {"queue": "email"},
        },
        task_default_queue="default",
        broker_connection_retry_on_startup=True,
    )
    return app

celery_app = create_celery()

@after_setup_logger.connect
def configure_logging(logger, *args, **kwargs):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )