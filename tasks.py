"""Parse tasks, add ids and store it to DB"""

import argparse
import getpass
import os
import platform
import re
import typing as t

import dataclasses_json as dj
import more_itertools as mit

from datastructures import FileIdentifiers, parse


def handle_file(filename: str) -> None:
    with open(filename, "r", encoding="utf-8") as f:
        td = parse(
            mit.peekable(f),
            FileIdentifiers(
                os.path.abspath(filename),
                platform.node(),
                getpass.getuser(),
            ),
        )
    if td is None:
        print("Not TODO file")
        return
    if td.add_missing_ids():
        with open(filename, "w", encoding="utf-8") as f:
            for line in td.ser():
                print(line, file=f)
    db_file = f"{os.path.dirname(os.path.abspath(__file__))}/tasks.jsonl"
    with open(db_file, "a", encoding="utf-8") as f:
        print(td.to_json(ensure_ascii=False), file=f)


def debug_file(filename: str) -> None:
    with open(filename, "r", encoding="utf-8") as f:
        td = parse(
            mit.peekable(f),
            FileIdentifiers(
                os.path.abspath(filename),
                platform.node(),
                getpass.getuser(),
            ),
        )
    if td is None:
        print("Not TODO file")
        return
    td.add_missing_ids()
    for line in td.ser():
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(title="commands", required=True)
    update_and_store = subparsers.add_parser(
        "update-and-store", help="Update IDs in the file and then store it in DB"
    )
    update_and_store.add_argument("--file")
    update_and_store.set_defaults(func=lambda args: handle_file(args.file))
    debug = subparsers.add_parser("debug", help="Parse file and print it")
    debug.add_argument("--file")
    debug.set_defaults(func=lambda args: debug_file(args.file))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
