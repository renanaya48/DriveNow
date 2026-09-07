"""Message-queue consumer worker (run as a separate process).

Placeholder entrypoint so ``python -m app.messaging.consumer`` and the
docker-compose ``consumer`` service are valid today. The real RabbitMQ consumer
(subscribe to rental.* events, write an audit log) is implemented in step 9.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "Consumer placeholder started (mq_enabled=%s). Real consumer arrives in step 9.",
        settings.enable_message_queue,
    )


if __name__ == "__main__":
    main()
