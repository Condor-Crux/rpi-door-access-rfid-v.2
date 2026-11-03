#!/usr/bin/env python3
import argparse
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RPi Door Access RFID")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print every RFID poll event to stdout")
    args = parser.parse_args()

    if args.verbose:
        os.environ["VERBOSE"] = "1"

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=_env_flag("RELOAD", True),
    )
