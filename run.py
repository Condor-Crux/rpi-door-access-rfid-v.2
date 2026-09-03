#!/usr/bin/env python3
import argparse
import os
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RPi Door Access RFID")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print every RFID poll event to stdout")
    args = parser.parse_args()

    if args.verbose:
        os.environ["VERBOSE"] = "1"

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
