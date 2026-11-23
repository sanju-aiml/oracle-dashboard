"""Standalone app:  uvicorn main:app --host 0.0.0.0 --port 8000
Starts the 24/7 paper bot inside the server (set BOT_ENABLED=0 to run it separately with run_bot.py)."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

import bot
import routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
HERE = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app):
    stop = asyncio.Event()
    task = None
    if os.getenv("BOT_ENABLED", "1") == "1":
        task = asyncio.create_task(bot.run_forever(stop))
    yield
    stop.set()
    if task:
        await asyncio.wait_for(task, timeout=10)


app = FastAPI(title="ORACLE AI", lifespan=lifespan)
app.include_router(routes.router)


@app.get("/")
def demo():
    return FileResponse(os.path.join(HERE, "demo.html"))
