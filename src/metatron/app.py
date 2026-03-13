"""Unified entry point — runs API server and channel bots in one process.

Starts FastAPI (uvicorn) and messaging channels (Telegram, Discord, Slack)
as concurrent async tasks sharing a single AgentRouter instance. Channels
are started dynamically based on enabled connections in the database.

Usage:
    python -m metatron.app
"""

from __future__ import annotations

import asyncio

import structlog
import uvicorn

from metatron.agent.router import AgentRouter
from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.core.logging import configure_logging

logger = structlog.get_logger()


async def _run_api(settings: Settings) -> None:
    """Run FastAPI via uvicorn as an async server."""
    app = create_app(settings)
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_all() -> None:
    """Start all configured services in a single event loop."""
    settings = Settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )

    router = AgentRouter(settings=settings)

    tasks: list[asyncio.Task] = []

    # API server — always runs
    tasks.append(asyncio.create_task(_run_api(settings)))
    logger.info("app.api.scheduled", port=settings.port)

    # One-time migration: env-var credentials → DB connections (idempotent)
    try:
        from metatron.storage.migrate_env_connections import migrate_env_to_db

        mig = await migrate_env_to_db(
            postgres_dsn=settings.postgres_dsn,
            workspace_id=settings.default_workspace_id,
            fernet_key=settings.fernet_key,
        )
        if mig["created"]:
            logger.info(
                "app.env_migration.done",
                created=mig["created"],
            )
    except Exception as exc:
        logger.warning(
            "app.env_migration.failed", error=str(exc),
        )

    # Start channels from DB config
    from metatron.channels.manager import ChannelManager

    channel_manager = ChannelManager(router=router)
    try:
        started = await channel_manager.start_channels_from_db(
            postgres_dsn=settings.postgres_dsn,
            fernet_key=settings.fernet_key,
            default_workspace_id=settings.default_workspace_id,
        )
        logger.info("app.channels.started", count=started)
    except Exception as exc:
        logger.error(
            "app.channels.startup_failed",
            error=str(exc),
            exc_info=True,
        )

    logger.info("app.starting", services=len(tasks))

    try:
        await asyncio.gather(*tasks)
    finally:
        await channel_manager.stop_all()


def main() -> None:
    """CLI entry point for unified launcher."""
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
