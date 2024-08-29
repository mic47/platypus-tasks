"""Parse tasks, add ids and store it to DB"""

import argparse
import os

from tasks import handle_file


def main() -> None:
    db_file = f"{os.path.dirname(os.path.abspath(__file__))}/tasks.jsonl"
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    args = parser.parse_args()
    handle_file(args.file, db_file)


if __name__ == "__main__":
    main()
