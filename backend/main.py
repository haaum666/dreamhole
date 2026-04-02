"""Entry point — runs API server and crawler in parallel."""
import asyncio
import logging
import uvicorn

from api import app
from crawler import run_scheduler
from database import get_pool, init_db
from config import DATABASE_URL, API_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)


async def main():
    pool = await get_pool(DATABASE_URL)
    await init_db(pool)

    config = uvicorn.Config(app, host="0.0.0.0", port=API_PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        run_scheduler(),
    )


if __name__ == "__main__":
    asyncio.run(main())
