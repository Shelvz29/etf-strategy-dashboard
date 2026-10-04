"""Runs independently of a Streamlit browser session; never sends orders."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import time

import core
import macro_sources
import market_factors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    core.init_db()
    lock = (core.RUNTIME / "worker.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("已有后台监测程序运行。")
        return
    logger = logging.getLogger("monitor")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(core.RUNTIME / "worker.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    core.bootstrap()
    full_due = quote_due = macro_due = 0
    last_request = core.get("refresh_handled")
    try:
        while True:
            clock = core.market_clock()
            core.put("heartbeat", {"time": core.iso_now(), "pid": os.getpid(), "busy": False})
            request = core.get("refresh_request")
            forced = request is not None and request != last_request
            snap = core.get("snapshot")
            missing = snap["last"]["date"] != clock["expected_date"] or snap["source"] != "Yahoo 公开日线"
            needs_daily_check = core.get("validated_session") != clock["expected_date"]
            retry_pending = core.get("last_error") is not None
            if forced or (time.monotonic() >= full_due and (missing or needs_daily_check or retry_pending)) or args.once:
                core.put("heartbeat", {"time": core.iso_now(), "pid": os.getpid(), "busy": True})
                core.put("last_attempt", core.iso_now())
                try:
                    snap = core.refresh_full()
                    core.put("validated_session", clock["expected_date"])
                    core.put("quotes", {"data": snap["quotes"], "fetched": core.iso_now()})
                    logger.info("Confirmed %s %s %.2f", snap["last"]["date"], snap["last"]["symbol"], snap["last"]["weight"])
                    full_due = time.monotonic() + 300
                except core.StrategyChanged:
                    logger.info("Strategy changed during refresh; retrying with the current profile")
                    full_due = 0
                except Exception as exc:
                    core.record_failure(exc)
                    logger.exception("Daily refresh failed")
                    full_due = time.monotonic() + 300
                last_request = request
                core.put("refresh_handled", request)
                quote_due = 0
            if forced or args.once or time.monotonic() >= macro_due:
                core.put("heartbeat", {"time": core.iso_now(), "pid": os.getpid(), "busy": True})
                try:
                    macro_sources.refresh(force=forced or args.once)
                    logger.info("Macro observations checked independently of strategy targets")
                except Exception:
                    logger.exception("Macro refresh failed; confirmed trading signals are unchanged")
                try:
                    market_factors.refresh(force=forced or args.once)
                    logger.info("Extended factors checked independently of strategy targets")
                except Exception:
                    logger.exception("Extended factor refresh failed; confirmed trading signals are unchanged")
                macro_due = time.monotonic() + 1800
            if args.once:
                break
            if clock["is_open"] and time.monotonic() >= quote_due:
                try:
                    core.refresh_quotes()
                except Exception as exc:
                    core.put("preview", None)
                    core.record_failure(exc)
                    logger.exception("Quote refresh failed")
                quote_due = time.monotonic() + 300
            elif not clock["is_open"]:
                core.put("preview", None)
            core.put("heartbeat", {"time": core.iso_now(), "pid": os.getpid(), "busy": False})
            time.sleep(5)
    finally:
        core.put("heartbeat", {"time": core.iso_now(), "pid": os.getpid(), "stopped": True})
        lock.close()
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    main()
