"""Parsing and data structure module for tasks"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import re
import typing as t

import dataclasses_json as dj
import more_itertools as mit
from colored import Fore, Style

import alignment as aln

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
        used_words_in_title = set(SPACE_RE.split(self.title))
        prefix_tags = []
        for tag in self.tags:
            if tag in used_words_in_title:
                break
            prefix_tags.append(tag)
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
    lines_order: t.List[Section | Task] = dc.field(
        default_factory=lambda: [], metadata=dj.config(encoder=lambda _: [])
    )

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

    def diff(self, other: TodoFile) -> DiffFile:
        # Basically -- find tasks that changed
        tasks: t.Dict[str, DiffTask] = {}
        used_tasks = set()
        for task in self.tasks.values():
            if task.identifier is None:
                # TODO
                continue
            used_tasks.add(task.identifier)
            task_str = "\n".join(task.ser())
            o = other.tasks.get(task.identifier)
            if o is None:
                tasks[task.identifier] = DiffTask(
                    "\n".join(aln.pretty_alignment(aln.align_texts("", task_str))),
                    old_section=None,
                    new_section=task.section,
                )
            else:
                o_str = "\n".join(o.ser())
                if task_str != o_str:
                    tasks[task.identifier] = DiffTask(
                        "\n".join(
                            aln.pretty_alignment(aln.align_texts(o_str, task_str))
                        ),
                        old_section=o.section,
                        new_section=task.section,
                    )

        for task in other.tasks.values():
            if task.identifier is None:
                continue
            if task.identifier in used_tasks:
                continue
            task_str = "\n".join(task.ser())
            tasks[task.identifier] = DiffTask(
                "\n".join(aln.pretty_alignment(aln.align_texts(task_str, ""))),
                old_section=task.section,
                new_section=None,
            )
        # TODO: Do something / order with the sections

        result = DiffFile(
            tasks=tasks, sections=self.sections, old_sections=other.sections
        )
        return result


@dc.dataclass
class DiffTask:
    str_diff: str
    old_section: str | None
    new_section: str | None


@dc.dataclass
class DiffFile(dj.DataClassJsonMixin):
    tasks: t.Dict[str, DiffTask]
    sections: t.List[Section]
    old_sections: t.List[Section]

    def ser(self) -> t.Iterable[str]:
        section_order = {
            section.identifier: index for index, section in enumerate(self.sections)
        }
        unprinted_sections = {section.identifier: section for section in self.sections}
        old_sections = {section.identifier: section for section in self.old_sections}
        for task in sorted(
            self.tasks.values(),
            key=lambda x: section_order.get(x.new_section or x.old_section) or -1,
        ):
            section = unprinted_sections.get(task.new_section or task.old_section)
            if section is not None:
                yield from section.ser()
                del unprinted_sections[section.identifier]
            if (
                task.new_section is not None
                and task.old_section is not None
                and task.new_section != task.old_section
            ):
                old_section = old_sections.get(task.old_section)
                old_section_str = (
                    "\n".join(old_section.ser())
                    if old_section is not None
                    else task.old_section
                )
                yield f"{Fore.yellow}Following task switched section from {old_section_str}{Style.reset}"
            yield task.str_diff


SECTION_LINE_RE = re.compile("##*[ \t]")


def til_sectionlines(lines: mit.peekable) -> t.List[str]:
    out: t.List[str] = []
    while (x_ := lines.peek(None)) is not None:
        x: str = x_.rstrip()
        if SECTION_LINE_RE.match(x) is not None:
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
                stripped_line = raw_task.rstrip("\n")
                if last_task is not None:
                    last_task.description.append(stripped_line)
                    for word in SPACE_RE.split(stripped_line):
                        if (
                            TAG_RE.fullmatch(word) is not None
                            and word not in last_task.tags
                        ):
                            last_task.tags.append(word)
                else:
                    section.description.append(stripped_line)
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
