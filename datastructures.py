"""Parsing and data structure module for tasks"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import math
import re
import typing as t
import itertools as it

import dataclasses_json as dj
import more_itertools as mit
from colored import Fore, Style

import alignment as aln

COUNTER_RE = re.compile("[0-9][0-9]*")
UUID_RE = re.compile("[a-zA-Z0-9][-a-zA-Z0-9]*")
HEADER_BEGIN = "TASK FILE HEADER BEGIN"
HEADER_END = "TASK FILE HEADER END"

EMPTY_TASK_STATE = "[ ]"


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
    identifier: str

    def ser(self) -> t.List[str]:
        return [
            HEADER_BEGIN,
            self.task_counter,
            self.identifier,
            HEADER_END,
        ]


@dc.dataclass
class DeprecatedSection(dj.DataClassJsonMixin):
    """Exists only for migration of old data"""

    identifier: str | None
    title: str
    level: int
    description: t.List[str] = dc.field(default_factory=lambda: [])

    def migrate_to_task(self, parent_section: Task, line_number: int) -> Task:
        task = parse_task_line(parent_section, self.title, line_number)
        if task is None:
            task = parse_task_line(parent_section, f"{EMPTY_TASK_STATE} {self.title}", line_number)
            if task is not None:
                task.state = None
        if task is None:
            task = Task(
                identifier=None,
                title=self.title,
                level=None,
                description=[],
                state=None,
                related_tasks=[],
                tags=[],
                section=parent_section.identifier or parent_section.title,
                line_number=line_number,
            )
        task.identifier = self.identifier
        task.level = self.level
        task.description = self.description
        return task


@dc.dataclass
class TaskRef(dj.DataClassJsonMixin):
    task: str
    section: str
    title: str
    description: t.List[str]
    line_number: int

    def ser(self) -> t.Iterable[str]:
        yield self.title
        if self.description:
            yield from self.description


@dc.dataclass
class Task(dj.DataClassJsonMixin):
    identifier: t.Optional[str]
    state: t.Optional[str]
    related_tasks: t.List[str]
    tags: t.List[str]
    title: str = dc.field(metadata=dj.config(field_name="content"))
    section: str
    line_number: int = dc.field(default=-1)
    prefix: str = dc.field(default="")  # Originally was missing
    description: t.List[str] = dc.field(default_factory=lambda: [])
    level: t.Optional[int] = dc.field(default=None)

    def ser(self) -> t.Iterable[str]:
        used_words_in_title = set(SPACE_RE.split(self.title))
        prefix_tags = []
        for tag in self.tags:
            if tag in used_words_in_title:
                break
            prefix_tags.append(tag)
        words = [self.state] if self.state is not None else []
        if self.identifier is not None:
            words.append(self.identifier)
        words.extend(prefix_tags)
        words.append(self.title)
        level = ("#" * self.level + " ") if self.level is not None and self.level > 0 else ""
        yield level + self.prefix + " ".join(words)
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
    deprecated_sections: t.List[DeprecatedSection] = dc.field(metadata=dj.config(field_name="sections"))
    tasks: t.Dict[str, Task]
    non_id_tasks: t.List[Task]
    unmatched_lines: t.List[str]
    prefix: t.List[str]
    header_suffix: t.List[str] = dc.field(default_factory=lambda: [])
    task_refs: t.List[TaskRef] = dc.field(default_factory=lambda: [])

    def ordered_tasks_and_refs(self) -> t.List[Task | TaskRef]:
        tasks_or_refs: t.List[Task | TaskRef] = list(it.chain(self.tasks.values(), self.task_refs))
        return sorted(tasks_or_refs, key=lambda x: x.line_number)

    def ser(self) -> t.Iterable[str]:
        yield from self.prefix
        yield from self.header.ser()
        yield from self.header_suffix
        for line in self.ordered_tasks_and_refs():
            yield from line.ser()

    def resolve_issues(self) -> bool:
        """Resolve any possible issues after parsing file from the user."""
        changed = self._add_missing_ids()
        changed |= self._resolve_task_refs()
        changed |= self._migrate_sections_list_to_tasks()
        return changed

    def migrate(self) -> TodoFile:
        """Migrate from old ways of doing things. Should be called after parsing DB file."""
        self._migrate_sections_list_to_tasks()
        return self

    def _resolve_task_refs(self) -> bool:
        updated = False
        for ref in self.task_refs:
            task = self.tasks.get(ref.task)
            if task is None:
                if not ref.title.startswith("!<ERR>"):
                    ref.title = ref.title + " !<ERR>"
                    updated = True
                continue
            if "".join(ref.description).strip() != "":
                updated = True
                if task.description:
                    task.description.append("")
                updatetime = dt.datetime.now().replace(microsecond=0)
                task.description.append(f"Updated at {updatetime.isoformat()}")
                task.description.extend(ref.description)
            ref.description = []
            new_title = f"@{task.identifier} {task.title}"
            if ref.title != new_title:
                ref.title = new_title
                updated = True
        return updated

    def _add_missing_ids(self) -> bool:
        """Add missing ids into sections and tasks. Return true if this was done for any sections"""
        updated = False
        for section in self.deprecated_sections:
            if section.identifier is None:
                self.header.task_counter = increase_counter(self.header.task_counter)
                section.identifier = f"t{self.header.task_counter}"
                updated = True
        for task in self.non_id_tasks:
            self.header.task_counter = increase_counter(self.header.task_counter)
            task.identifier = f"t{self.header.task_counter}"
            assert task.identifier not in self.tasks
            self.tasks[task.identifier] = task
            updated = True
        self.non_id_tasks = []
        return updated

    def _migrate_sections_list_to_tasks(self) -> bool:
        updated = False
        section_stack = SectionStack()
        # When migrating, we need to assign numbers to sections
        virtual_line_counter = 1
        tasks_to_sections: t.Dict[str | None, t.List[Task]] = {}
        for task in self.tasks.values():
            tasks_to_sections.setdefault(task.section, []).append(task)
        for old_section in self.deprecated_sections:
            previous_section = section_stack.get_parent(old_section.level)
            section = old_section.migrate_to_task(previous_section, virtual_line_counter)
            virtual_line_counter += 1
            section_stack.push_section(section)
            for t in it.chain(
                tasks_to_sections.get(section.identifier, []), tasks_to_sections.get(section.title, [])
            ):
                if t.line_number < 0:
                    t.line_number = virtual_line_counter
                    virtual_line_counter += 1
                    updated = True
            if section.identifier in self.tasks:
                raise Exception(f"Section {section.identifier} already exists in tasks")
            if section.identifier is None:
                raise Exception(f"There is section no identifier")
            self.tasks[section.identifier] = section
            updated = True
        for t in self.tasks.values():
            if t.line_number < 0:
                t.line_number = virtual_line_counter
                virtual_line_counter += 1
                updated = True
        self.deprecated_sections = []
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
                    task.line_number,
                    old_section=None,
                    new_section=task.section,
                )
            else:
                o_str = "\n".join(o.ser())
                if task_str != o_str:
                    tasks[task.identifier] = DiffTask(
                        "\n".join(aln.pretty_alignment(aln.align_texts(o_str, task_str))),
                        task.line_number,
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
                task.line_number,
                old_section=task.section,
                new_section=None,
            )
        # TODO: Do something / order with the sections

        result = DiffFile(diff_tasks=tasks, sections=self.tasks, old_sections=other.tasks)
        return result


@dc.dataclass
class DiffTask:
    str_diff: str
    line_number: int
    old_section: str | None
    new_section: str | None


@dc.dataclass
class DiffFile(dj.DataClassJsonMixin):
    diff_tasks: t.Dict[str, DiffTask]
    sections: t.Dict[str, Task]
    old_sections: t.Dict[str, Task]

    def ser(self) -> t.Iterable[str]:
        section_order = {key: section.line_number for key, section in self.sections.items()}
        unprinted_sections = {k: v for k, v in self.sections.items() if k not in self.diff_tasks}
        for task in sorted(
            self.diff_tasks.values(),
            key=lambda x: x.line_number,
        ):
            section = unprinted_sections.get(task.new_section or task.old_section or "")
            level = 1 << 47
            sections: t.List[Task] = []
            while section is not None:
                sections.append(section)
                if section.identifier is not None and section.identifier in unprinted_sections:
                    del unprinted_sections[section.identifier]
                section = unprinted_sections.get(section.section)
            for section in reversed(sections):
                yield from (f"{Style.bold}{x}{Style.reset}" for x in section.ser())
            if (
                task.new_section is not None
                and task.old_section is not None
                and task.new_section != task.old_section
            ):
                old_section = self.old_sections.get(task.old_section)
                old_section_str = (
                    "\n".join(old_section.ser()) if old_section is not None else task.old_section
                )
                yield f"{Fore.yellow}Following task was moved from section '{old_section_str}'{Style.reset}"
            yield task.str_diff


SECTION_LINE_RE = re.compile("##*[ \t]")


def til_sectionlines(lines: mit.peekable[t.Tuple[int, str]]) -> t.List[t.Tuple[int, str]]:
    out: t.List[t.Tuple[int, str]] = []
    while (x_ := lines.peek(None)) is not None:
        n, l = x_
        x: str = l.rstrip()
        if SECTION_LINE_RE.match(x) is not None:
            return out
        out.append(next(lines))
    return out


def parse_header(
    lines: t.List[t.Tuple[int, str]],
) -> t.Tuple[Header | None, t.List[t.Tuple[int, str]], t.List[t.Tuple[int, str]]]:
    index = 0
    prefix = []
    suffix = []
    header = None
    while index < len(lines):
        if header is None:
            if (
                lines[index][1].strip() == HEADER_BEGIN
                and index + 4 < len(lines)
                and lines[index + 4][1].strip() == HEADER_END
            ):
                # OLD format, with section counter, we just validate it
                task_counter = lines[index + 1][1].strip()
                section_counter = lines[index + 2][1].strip()
                identifier = lines[index + 3][1].strip()
                if (
                    COUNTER_RE.fullmatch(task_counter) is not None
                    and COUNTER_RE.fullmatch(section_counter) is not None
                    and UUID_RE.fullmatch(identifier) is not None
                ):
                    header = Header(task_counter, identifier)
                    index += 5
                    continue
            if (
                lines[index][1].strip() == HEADER_BEGIN
                and index + 3 < len(lines)
                and lines[index + 3][1].strip() == HEADER_END
            ):
                # New format, without section counter
                task_counter = lines[index + 1][1].strip()
                identifier = lines[index + 2][1].strip()
                if (
                    COUNTER_RE.fullmatch(task_counter) is not None
                    and UUID_RE.fullmatch(identifier) is not None
                ):
                    header = Header(task_counter, identifier)
                    index += 4
                    continue

        if header is None:
            prefix.append(lines[index])
        else:
            suffix.append(lines[index])
        index += 1
    return header, prefix, suffix


class SectionStack:
    def __init__(self) -> None:
        self.stack = [Task(None, "", [], [], "@root", "", -1, "", [], level=0)]

    def get_parent(self, level: int) -> Task:
        while (self.stack[-1].level or 0) >= level:
            self.stack.pop()
        return self.stack[-1]

    def push_section(self, section: Task) -> None:
        if section.level is None:
            raise Exception("Pushing section without level!")
        self.get_parent(section.level)
        self.stack.append(section)


def parse_section_line(section_stack: SectionStack, lines: mit.peekable[t.Tuple[int, str]]) -> None | Task:
    line_with_index: t.Tuple[int, str] | None = next(lines, None)
    if line_with_index is None:
        return None
    line_number, line = line_with_index
    line = line.strip()
    title_line = line.lstrip("#")
    level = len(line) - len(title_line)
    title_line = title_line.strip()
    parent_section = section_stack.get_parent(level)
    task = parse_task_line(parent_section, title_line, line_number)
    if task is None:
        task = parse_task_line(parent_section, f"{EMPTY_TASK_STATE} {title_line}", line_number)
        if task is None:
            raise Exception(f"Unable to parse section line {title_line}")
            # return None
        task.state = None
    task.level = level
    section_stack.push_section(task)
    return task


def parse_task_line(section: Task, line: str, line_number: int) -> None | Task:
    raw_task = line.rstrip()
    match = TASK_LINE_RE.match(raw_task)
    if match is None:
        return None
    state: str = match.group("state")
    rest: str = match.group("rest").strip()
    identifier: None | str = None
    skipping = True
    words = []
    task_ids: t.List[str] = []
    tags = []
    for word in SPACE_RE.split(rest):
        if ID_RE.fullmatch(word) is not None:
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
        line_number=line_number,
    )


def parse_ref_task_line(section: Task, line: str, line_number: int) -> None | TaskRef:
    raw_task = line.rstrip()
    match = REF_LINE_RE.match(raw_task)
    if match is None:
        return None
    task = match.group("task")
    return TaskRef(task, section.identifier or section.title, raw_task, [], line_number)


# Note: s is used only for historic purposes, where tasks and sections used different counter
ID_RE = re.compile(r"(s|t)[0-9][0-9]*")
TASK_LINE_RE = re.compile(r"^(?P<prefix>[ *-]*)(?P<state>\[[^]]*\])(?P<rest>.*)$")
TAG_RE = re.compile(r"#[-a-zA-Z_0-9]*")
REF_LINE_RE = re.compile(r"^\s*@(?P<task>(s|t)[0-9][0-9]*)(?P<title>\b.*)")
SPACE_RE = re.compile(r"\s\s*")


def parse(lines: mit.peekable[t.Tuple[int, str]], file_identifiers: FileIdentifiers) -> None | TodoFile:
    header, header_prefix, header_suffix = parse_header(til_sectionlines(lines))
    if header is None:
        return None
    tasks = {}
    non_id_tasks = []
    task_refs = []
    section_stack = SectionStack()
    while (section := parse_section_line(section_stack, lines)) is not None:
        if section.identifier is None:
            non_id_tasks.append(section)
        else:
            tasks[section.identifier] = section
        raw_tasks = til_sectionlines(lines)
        last_task_or_ref: None | Task | TaskRef = None
        for raw_task in raw_tasks:
            task_or_ref = parse_ref_task_line(section, raw_task[1], raw_task[0]) or parse_task_line(
                section, raw_task[1], raw_task[0]
            )
            if task_or_ref is None:
                stripped_line = raw_task[1].rstrip("\n")
                if last_task_or_ref is not None:
                    last_task_or_ref.description.append(stripped_line)
                    if isinstance(last_task_or_ref, Task):
                        for word in SPACE_RE.split(stripped_line):
                            if TAG_RE.fullmatch(word) is not None and word not in last_task_or_ref.tags:
                                last_task_or_ref.tags.append(word)
                else:
                    section.description.append(stripped_line)
                continue
            last_task_or_ref = task_or_ref
            if isinstance(task_or_ref, Task):
                if task_or_ref.identifier is None:
                    non_id_tasks.append(task_or_ref)
                else:
                    tasks[task_or_ref.identifier] = task_or_ref
            else:
                task_refs.append(task_or_ref)
    now = dt.datetime.now()
    td = TodoFile(
        header,
        file_identifiers,
        now.isoformat(),
        now,
        [],
        tasks,
        non_id_tasks,
        [],  # Unmatched lines
        [x for _, x in header_prefix],
        [x for _, x in header_suffix],
        task_refs,
    )
    return td
