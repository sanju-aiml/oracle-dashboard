"""Phone notifications. Two free channels, either or both:
  * ntfy  - install the free "ntfy" app, subscribe to a private topic name, done (no account).
  * Telegram - create a bot with @BotFather, put its token in TELEGRAM_BOT_TOKEN, send /start to it,
    and give ORACLE your chat id.
Every alert is also stored in alerts_log, so nothing is lost if a push fails."""
import logging
import time

import requests

import config
import store

log = logging.getLogger("oracle.notify")


def set_channel(user_id, ntfy_topic=None, telegram_chat_id=None):
    with store.db() as c:
        row = c.execute("SELECT * FROM user_channels WHERE user_id=?", (user_id,)).fetchone()
        cur = dict(row) if row else {"ntfy_topic": None, "telegram_chat_id": None}
        c.execute("INSERT OR REPLACE INTO user_channels VALUES (?,?,?)",
                  (user_id, ntfy_topic or cur["ntfy_topic"], telegram_chat_id or cur["telegram_chat_id"]))


def get_channel(user_id):
    with store.db() as c:
        row = c.execute("SELECT * FROM user_channels WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else {"ntfy_topic": None, "telegram_chat_id": None}


def _ntfy(topic, title, body, priority="default"):
    r = requests.post(f"{config.NTFY_SERVER}/{topic}", data=body.encode("utf-8"),
                      headers={"Title": title.encode("utf-8"), "Priority": priority}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()


def _telegram(chat_id, title, body):
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": f"{title}\n\n{body}"}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()


def send(user_id, symbol, kind, title, body, priority="default"):
    """Store the alert, then push it to the user's channels. Never raises."""
    ch = get_channel(user_id)
    delivered = []
    if ch["ntfy_topic"]:
        try:
            _ntfy(ch["ntfy_topic"], title, body, priority)
            delivered.append("ntfy")
        except Exception as e:
            delivered.append(f"ntfy-failed:{type(e).__name__}")
    if ch["telegram_chat_id"] and config.TELEGRAM_BOT_TOKEN:
        try:
            _telegram(ch["telegram_chat_id"], title, body)
            delivered.append("telegram")
        except Exception as e:
            delivered.append(f"telegram-failed:{type(e).__name__}")
    if not delivered:
        delivered.append("in-app-only")
    with store.db() as c:
        c.execute("INSERT INTO alerts_log(user_id,ts,symbol,kind,title,body,delivered) VALUES (?,?,?,?,?,?,?)",
                  (user_id, int(time.time()), symbol, kind, title, body, ",".join(delivered)))
    return delivered
