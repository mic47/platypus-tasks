"""Parse tasks, add ids and store it to DB"""

import argparse
import datetime
import dataclasses
import getpass
import os
import platform

import dataclasses_json as dj
import dateparser
import more_itertools as mit

from datastructures import FileIdentifiers, parse, TodoFile


def load_file(filename: str) -> None | TodoFile:
    with open(filename, "r", encoding="utf-8") as f:
        return parse(
            mit.peekable(f),
            FileIdentifiers(
                os.path.abspath(filename),
                platform.node(),
                getpass.getuser(),
            ),
        )
    return None


def handle_file(filename: str) -> None:
    td = load_file(filename)
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
    td = load_file(filename)
    if td is None:
        print("Not TODO file")
        return
    td.add_missing_ids()
    for line in td.ser():
        print(line)


@dataclasses.dataclass
class TodoFileSkeleton(dj.DataClassJsonMixin):
    update_time: datetime.datetime


def diff(since: datetime.datetime, until: datetime.datetime) -> None:
    db_file = f"{os.path.dirname(os.path.abspath(__file__))}/tasks.jsonl"
    state_at_beginning_of_period = None
    state_at_end_of_period = None
    with open(db_file, "r", encoding="utf-8") as f:
        for line in f:
            todo = TodoFileSkeleton.from_json(line)
            if todo.update_time <= since:
                if (
                    state_at_beginning_of_period is None
                    or state_at_beginning_of_period[0].update_time < todo.update_time
                ):
                    state_at_beginning_of_period = (todo, line)
            if todo.update_time <= until:
                if (
                    state_at_end_of_period is None
                    or state_at_end_of_period[0].update_time < todo.update_time
                ):
                    state_at_end_of_period = (todo, line)
    if state_at_beginning_of_period is None or state_at_end_of_period is None:
        print("Unable to find any files matching your description")
        return
    start = TodoFile.from_json(state_at_beginning_of_period[1])
    end = TodoFile.from_json(state_at_end_of_period[1])
    for line in end.diff(start).ser():
        print(line)


def parse_date(x: str) -> datetime.datetime | None:
    return dateparser.parse(x, settings={"RETURN_AS_TIMEZONE_AWARE": True})


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
    diff_c = subparsers.add_parser("diff", help="Show difference in given time period")
    diff_c.add_argument("--since", type=parse_date, default="3 weeks ago")
    diff_c.add_argument("--until", type=parse_date, default="now")
    diff_c.set_defaults(func=lambda args: diff(args.since, args.until))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
