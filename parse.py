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

COUNTER_RE = re.compile("[0-9][0-9]*")
UUID_RE = re.compile("[a-zA-Z0-9][-a-zA-Z0-9]*")
HEADER_BEGIN = "TASK FILE HEADER BEGIN"
HEADER_END = "TASK FILE HEADER END"


def increase_counter(counter: str) -> str:
    """Increase string counter. Assumes that the counter is valid integer number"""
    number = int(counter)
    number += 1
    as_string = str(number)
    if len(counter) > len(as_string):
        diff = len(counter) - len(as_string)
        return counter[:diff] + as_string
    return as_string


@dc.dataclass
class Header(dj.DataClassJsonMixin):
    task_counter: str
    section_counter: str
    identifier: str

    def ser(self) -> t.List[str]:
        return [
            HEADER_BEGIN,
            self.task_counter,
            self.section_counter,
            self.identifier,
            HEADER_END,
        ]


@dc.dataclass
class Section(dj.DataClassJsonMixin):
    identifier: str | None
    title: str
    level: int
    description: t.List[str] = dc.field(default_factory=lambda: [])

    def ser(self) -> t.Iterable[str]:
        level = "#" * self.level
        words = [level]
        if self.identifier is not None:
            words.append(self.identifier)
        words.append(self.title)
        yield " ".join(words)
        yield from self.description


@dc.dataclass
class Task(dj.DataClassJsonMixin):
    identifier: t.Optional[str]
    state: str
    related_tasks: t.List[str]
    tags: t.List[str]
    title: str = dc.field(metadata=dj.config(field_name="content"))
    section: str
    prefix: str = dc.field(default="")  # Originally was missing
    description: t.List[str] = dc.field(default_factory=lambda: [])

    def ser(self) -> t.Iterable[str]:
        used_words = set(SPACE_RE.split(self.title))
        prefix_tags = [tag for tag in self.tags if tag not in used_words]
        words = [self.state]
        if self.identifier is not None:
            words.append(self.identifier)
        words.extend(prefix_tags)
        words.append(self.title)
        yield self.prefix + " ".join(words)
        yield from self.description


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
    header_suffix: t.List[str] = dc.field(default_factory=lambda: [])
    lines_order: t.List[Section | Task] = dc.field(default_factory=lambda: [])

    def ser(self) -> t.Iterable[str]:
        yield from self.prefix
        yield from self.header.ser()
        yield from self.header_suffix
        for line in self.lines_order:
            if isinstance(line, str):
                yield line
            else:
                yield from line.ser()

    def add_missing_ids(self) -> bool:
        """Add missing ids into sections and tasks. Return true if this was done for any sections"""
        updated = False
        for section in self.sections:
            if section.identifier is None:
                self.header.section_counter = increase_counter(
                    self.header.section_counter
                )
                section.identifier = f"s{self.header.section_counter}"
                updated = True
        for task in self.non_id_tasks:
            self.header.task_counter = increase_counter(self.header.task_counter)
            task.identifier = f"t{self.header.task_counter}"
            assert task.identifier not in self.tasks
            self.tasks[task.identifier] = task
            updated = True
        self.non_id_tasks = []
        return updated


def til_sectionlines(lines: mit.peekable) -> t.List[str]:
    out: t.List[str] = []
    while (x_ := lines.peek(None)) is not None:
        x: str = x_.rstrip()
        if x.startswith("#"):
            return out
        out.append(next(lines))
    return out


def parse_header(
    lines: t.List[str],
) -> t.Tuple[Header | None, t.List[str], t.List[str]]:
    index = 0
    prefix = []
    suffix = []
    header = None
    while index < len(lines):
        if (
            header is None
            and lines[index].strip() == HEADER_BEGIN
            and index + 4 < len(lines)
        ):
            task_counter = lines[index + 1].strip()
            section_counter = lines[index + 2].strip()
            identifier = lines[index + 3].strip()
            if (
                lines[index + 4].strip() == HEADER_END
                and COUNTER_RE.fullmatch(task_counter) is not None
                and COUNTER_RE.fullmatch(section_counter) is not None
                and UUID_RE.fullmatch(identifier) is not None
            ):
                header = Header(task_counter, section_counter, identifier)
                index += 5
                continue
        if header is None:
            prefix.append(lines[index])
        else:
            suffix.append(lines[index])
        index += 1
    return header, prefix, suffix


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


def parse_task_line(section: Section, line: str) -> None | Task:
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
    return Task(
        identifier,
        state,
        task_ids,
        tags,
        " ".join(words),
        section.identifier or section.title,
        prefix=match.group("prefix"),
    )


SECTION_ID_RE = re.compile(r"s[0-9][0-9]*")
TASK_LINE_RE = re.compile(r"^(?P<prefix>[ *-]*)(?P<state>\[[^]]*\])(?P<rest>.*)$")
TASK_ID_RE = re.compile(r"t[0-9][0-9]*")
TAG_RE = re.compile(r"#[-a-zA-Z_0-9]*")
SPACE_RE = re.compile(r"\s\s*")


def parse(lines: mit.peekable, file_identifiers: FileIdentifiers) -> None | TodoFile:
    header, header_prefix, header_suffix = parse_header(til_sectionlines(lines))
    if header is None:
        return None
    tasks = {}
    non_id_tasks = []
    sections = []
    lines_order: t.List[Section | Task] = []
    while (section := parse_section_line(lines)) is not None:
        sections.append(section)
        lines_order.append(section)
        raw_tasks = til_sectionlines(lines)
        last_task = None
        for raw_task in raw_tasks:
            task = parse_task_line(section, raw_task)
            if task is None:
                if last_task is not None:
                    last_task.description.append(raw_task.rstrip("\n"))
                else:
                    section.description.append(raw_task.rstrip("\n"))
                continue
            last_task = task
            lines_order.append(task)
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
        [],  # Unmatched lines
        header_prefix,
        header_suffix,
        lines_order,
    )
    return td


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
