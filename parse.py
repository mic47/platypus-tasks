import argparse
import dataclasses as dc
import datetime as dt
import getpass
import os
import platform
import re
import typing as t

import dataclasses_json as dj
import more_itertools as mit


@dc.dataclass
class Header(dj.DataClassJsonMixin):
    task_counter: str
    section_counter: str
    identifier: str


@dc.dataclass
class Section(dj.DataClassJsonMixin):
    identifier: str | None
    title: str
    level: int


@dc.dataclass
class Task(dj.DataClassJsonMixin):
    identifier: t.Optional[str]
    state: str
    related_tasks: t.List[str]
    tags: t.List[str]
    content: str
    section: str


@dc.dataclass
class FileIdentifiers:
    filename: str
    hostname: str
    username: str


@dc.dataclass
class TodoFile(dj.DataClassJsonMixin):
    header: Header
    file_identifiers: FileIdentifiers
    update_time_pretty: str
    update_time: dt.datetime
    sections: t.List[Section]
    tasks: t.Dict[str, Task]
    non_id_tasks: t.List[Task]
    unmatched_lines: t.List[str]
    prefix: t.List[str]


def til_sectionlines(lines: mit.peekable) -> t.List[str]:
    out: t.List[str] = []
    while (x_ := lines.peek(None)) is not None:
        x: str = x_.rstrip()
        if x.startswith("#"):
            return out
        out.append(next(lines))
    return out


COUNTER_RE = re.compile("[0-9][0-9]*")
UUID_RE = re.compile("[a-zA-Z0-9][-a-zA-Z0-9]*")


def parse_header(lines: t.List[str]) -> t.Tuple[Header | None, t.List[str]]:
    index = 0
    unparsed = []
    header = None
    while index < len(lines):
        if header is None and lines[index].strip() == "TASK FILE HEADER BEGIN" and index + 4 < len(lines):
            task_counter = lines[index + 1].strip()
            section_counter = lines[index + 2].strip()
            identifier = lines[index + 3].strip()
            if (
                lines[index + 4].strip() == "TASK FILE HEADER END"
                and COUNTER_RE.fullmatch(task_counter) is not None
                and COUNTER_RE.fullmatch(section_counter) is not None
                and UUID_RE.fullmatch(identifier) is not None
            ):
                header = Header(task_counter, section_counter, identifier)
                index += 5
                continue
        unparsed.append(lines[index])
        index += 1
    return header, unparsed


SECTION_ID_RE = re.compile(r"s[0-9][0-9]*")
TASK_LINE_RE = re.compile(r"^[ *-]*(?P<state>\[[^]]*\])(?P<rest>.*)$")
TASK_ID_RE = re.compile(r"t[0-9][0-9]*")
TAG_RE = re.compile(r"#[-a-zA-Z_0-9]*")
SPACE_RE = re.compile(r"\s\s*")


def parse_section_line(lines: mit.peekable) -> None | Section:
    line: str | None = next(lines, None)
    if line is None:
        return None
    line = line.strip()
    title_line = line.lstrip("#")
    level = len(line) - len(title_line)
    title_line = title_line.strip()
    identifier = None
    title = []
    for word in SPACE_RE.split(title_line):
        if SECTION_ID_RE.fullmatch(word) is not None:
            if identifier is None:
                identifier = word
            else:
                title.append(word)
        else:
            title.append(word)

    return Section(identifier, " ".join(title), level)


def parse_task(section: Section, line: str) -> None | Task:
    raw_task = line.rstrip()
    match = TASK_LINE_RE.match(raw_task)
    if match is None:
        return None
    state: str = match.group("state")
    rest: str = match.group("rest").strip()
    identifier = None
    skipping = True
    words = []
    task_ids: t.List[str] = []
    tags = []
    for word in SPACE_RE.split(rest):
        if TASK_ID_RE.fullmatch(word) is not None:
            if identifier is None:
                identifier = word
            else:
                task_ids.append(word)
            if not skipping:
                words.append(word)
        elif TAG_RE.fullmatch(word) is not None:
            tags.append(word)
            if not skipping:
                words.append(word)
        else:
            skipping = False
            words.append(word)
    return Task(identifier, state, task_ids, tags, " ".join(words), section.identifier or section.title)


def parse(lines: mit.peekable, file_identifiers: FileIdentifiers) -> None | TodoFile:
    header, prefix = parse_header(til_sectionlines(lines))
    if header is None:
        return None
    tasks = {}
    non_id_tasks = []
    sections = []
    unmatched_lines = []
    while (section := parse_section_line(lines)) is not None:
        sections.append(section)
        raw_tasks = til_sectionlines(lines)
        for raw_task in raw_tasks:
            task = parse_task(section, raw_task)
            if task is None:
                print("Unable to match", raw_task)
                unmatched_lines.append(raw_task)
                continue
            if task.identifier is None:
                non_id_tasks.append(task)
            else:
                tasks[task.identifier] = task
    now = dt.datetime.now()
    td = TodoFile(
        header,
        file_identifiers,
        now.isoformat(),
        now,
        sections,
        tasks,
        non_id_tasks,
        unmatched_lines,
        prefix,
    )
    return td

def handle_file(filename: str) -> None:
    with open(filename, "r", encoding="utf-8") as f:
        td= parse(
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
