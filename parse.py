"""Parse tasks, add ids and store it to DB"""

import argparse
import getpass
import os
import platform
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    args = parser.parse_args()
    handle_file(args.file)


if __name__ == "__main__":
    main()
