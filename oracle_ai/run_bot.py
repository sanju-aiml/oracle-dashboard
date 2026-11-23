"""Run the 24/7 paper bot on its own (no web server):  python run_bot.py"""
import asyncio
import logging
import signal

import bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:          # Windows
            pass
    await bot.run_forever(stop)


if __name__ == "__main__":
    asyncio.run(main())
