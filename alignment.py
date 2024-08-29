from __future__ import annotations

import dataclasses as dc
import enum
import math
import typing as t

from colored import Fore, Style


class CharType(enum.IntEnum):
    WHITESPACE = 0
    WORD = 1
    OTHER = 2

    @staticmethod
    def get(source: str, position: int) -> CharType:
        if 0 < position < len(source) - 1 and source[position - 1] == "[" and source[position + 1] == "]":
            # Anything between brackets is considered word.
            return CharType.WORD
        char = source[position]
        if char.isspace():
            return CharType.WHITESPACE
        if char.isalnum() or char == "_":
            return CharType.WORD
        return CharType.OTHER


class Block(enum.IntEnum):
    START = 0
    END = 0


TokenType = t.Union[CharType, t.Tuple[Block, int]]

T = t.TypeVar("T")


@dc.dataclass
class Token:
    source: str
    start: int
    end: int
    t: TokenType

    def text(self) -> str:
        return self.source[self.start : self.end]

    def insert_score(self, previous_is_same: bool) -> float:
        add = 1.0 if isinstance(self, tuple) and self[0] == Block.END else 0.0
        if previous_is_same:
            return 0.3 + add
        return 0.7 + add

    def mutation_score(self, other: Token) -> float:
        if self.t != other.t:
            return 100.0
        if isinstance(self.t, tuple) and isinstance(other.t, tuple):
            return abs(self.t[1] - other.t[1])
        return 0.0 if self.text().lower() == other.text().lower() else 1

    def __repr__(self) -> str:
        return f"{self.text()} {self.t} {self.start} {self.end}"


def token_parser(source: str) -> t.Iterable[Token]:
    position = 0
    prev_indentation = 0
    while position < len(source):
        c_type = CharType.get(source, position)
        start_position = position
        while position < len(source) and c_type == CharType.get(source, position):
            position += 1
        token: Token = Token(
            source,
            start_position,
            position,
            c_type,
        )
        if c_type == CharType.WHITESPACE:
            whitespace_text = token.text()
            current_indentation = (
                len(whitespace_text.split("\n")[-1]) if "\n" in whitespace_text else prev_indentation
            )
            if current_indentation != prev_indentation:
                yield Token(
                    source,
                    position,
                    position,
                    (
                        (Block.END, prev_indentation)
                        if current_indentation < prev_indentation
                        else (Block.START, current_indentation)
                    ),
                )
                prev_indentation = current_indentation
        yield token


class Operation(enum.IntEnum):
    MUTATION = 0
    INSERT_LEFT = 1
    INSERT_RIGHT = 2


AlignmentOperation = t.Tuple[T, T] | t.Tuple[T, None] | t.Tuple[None, T]


class PathList:
    def __init__(self, payload: AlignmentOperation[Token], previous: None | PathList) -> None:
        self.payload = payload
        self.previous = previous

    def extract_path(self) -> t.List[AlignmentOperation[Token]]:
        out = []
        this = self
        out.append(self.payload)
        while this.previous is not None:
            this = this.previous
            out.append(this.payload)
        # out.reverse()
        return out


AlignmentData = t.Tuple[float, None | PathList]


def unreachable() -> AlignmentData:
    return (math.inf, None)


def empty() -> AlignmentData:
    return (0, None)


@dc.dataclass
class AlignmentState:
    last_was_mutation: AlignmentData
    last_was_insert_left: AlignmentData
    last_was_insert_right: AlignmentData

    def pick_best(
        self,
        payload: AlignmentOperation[Token],
        mutation_score: float,
        insert_left_score: float,
        insert_right_score: float,
    ) -> AlignmentData:
        if insert_left_score < insert_right_score:
            if insert_left_score < mutation_score:
                score = insert_left_score
                previous = self.last_was_insert_left[1]
            else:
                score = mutation_score
                previous = self.last_was_mutation[1]
        else:
            if insert_right_score < mutation_score:
                score = insert_right_score
                previous = self.last_was_insert_right[1]
            else:
                score = mutation_score
                previous = self.last_was_mutation[1]
        return (score, PathList(payload, previous))

    def extract_best(self) -> AlignmentData:
        if self.last_was_mutation[0] < self.last_was_insert_left[0]:
            if self.last_was_mutation[0] < self.last_was_insert_right[0]:
                return self.last_was_mutation
            return self.last_was_insert_right
        if self.last_was_insert_left[0] < self.last_was_insert_right[0]:
            return self.last_was_insert_left
        return self.last_was_insert_right

    def insert_left_score(self, l: Token) -> AlignmentData:
        mutation_score = self.last_was_mutation[0] + l.insert_score(False)
        insert_left_score = self.last_was_insert_left[0] + l.insert_score(True)
        insert_right_score = self.last_was_insert_right[0] + l.insert_score(False)
        return self.pick_best(
            (l, None),
            mutation_score,
            insert_left_score,
            insert_right_score,
        )

    def insert_right_score(self, r: Token) -> AlignmentData:
        mutation_score = self.last_was_mutation[0] + r.insert_score(False)
        insert_left_score = self.last_was_insert_left[0] + r.insert_score(False)
        insert_right_score = self.last_was_insert_right[0] + r.insert_score(True)
        return self.pick_best(
            (None, r),
            mutation_score,
            insert_left_score,
            insert_right_score,
        )

    def mutation_score(self, l: Token, r: Token) -> AlignmentData:
        s = l.mutation_score(r)
        mutation_score = self.last_was_mutation[0] + s
        insert_left_score = self.last_was_insert_left[0] + s
        insert_right_score = self.last_was_insert_right[0] + s
        return self.pick_best(
            (l, r),
            mutation_score,
            insert_left_score,
            insert_right_score,
        )


AlignmentLineDS = t.List[AlignmentState]

Alignment = t.List[AlignmentOperation[Token]]


def align(left: t.List[Token], right: t.List[Token]) -> Alignment:
    current = []
    current.append(AlignmentState(empty(), unreachable(), unreachable()))
    for l in left:
        prev = current[-1]
        current.append(AlignmentState(unreachable(), prev.insert_left_score(l), unreachable()))
    for r in right:
        next_row = []
        prev = current[0]
        next_row.append(AlignmentState(unreachable(), unreachable(), prev.insert_right_score(r)))
        for l_index, l in enumerate(left):
            l_index += 1
            next_row.append(
                AlignmentState(
                    current[l_index - 1].mutation_score(l, r),
                    next_row[l_index - 1].insert_left_score(l),
                    current[l_index].insert_right_score(r),
                )
            )
        current = next_row
    ret = current[-1].extract_best()[1]
    if ret is None:
        return []
    return ret.extract_path()


Color = t.Literal["red"] | t.Literal["green"]


class ColoredString:
    def __init__(
        self,
        data: str | None = None,
        color: None | Color = None,
        strike_through: bool = False,
    ) -> None:
        self._len = 0
        self._color: None | Color = color
        self._payload: t.List[str | ColoredString] = []
        self._strike_through = strike_through
        if data is not None:
            self.extend(data)

    def isspace(self) -> bool:
        for x in self._payload:
            if len(x) > 0 and not x.isspace():
                return False
        return self._len > 0

    def __len__(self) -> int:
        return self._len

    def extend(self, data: str | ColoredString) -> ColoredString:
        self._len += len(data)
        self._payload.append(data)
        return self

    def strings(self) -> t.Iterable[str]:
        for p in self._payload:
            if isinstance(p, str):
                yield p
            else:
                yield from p.strings()

    def colored_strings(self) -> t.Iterable[str]:
        styled = self._color is not None or self._strike_through
        if self._color is not None:
            if self._color == "red":
                yield Fore.red
            elif self._color == "green":
                yield Fore.green
        if self._strike_through:
            yield Style.strikeout
        for p in self._payload:
            if isinstance(p, str):
                yield p
            else:
                yield from p.colored_strings()
        if styled:
            yield Style.reset

    def __format__(self, _: str) -> str:
        return "".join(self.colored_strings())


def pretty_alignment(alignment: Alignment) -> t.Iterable[str]:
    left_line = ColoredString()
    right_line = ColoredString()

    def flush() -> t.Iterable[str]:
        nonlocal left_line
        nonlocal right_line
        if f"{left_line}" != f"{right_line}":
            if not left_line.isspace():
                yield f"{left_line}"
            if not right_line.isspace():
                yield f"{right_line}"
        else:
            yield f"{right_line}"
        left_line = ColoredString()
        right_line = ColoredString()

    prev_was_space = True
    for left, right in alignment:
        if left is not None and right is not None:
            left_text = left.text()
            right_text = right.text()
            if left_text.lower() == right_text.lower():
                left_line.extend(" " * len(left_text))
                right_line.extend(right_text)
            else:
                left_line.extend(ColoredString(left_text, "red"))
                right_line.extend(ColoredString(right_text, "green"))
            left_len = len(left_text)
            right_len = len(right_text)
            if left_len < right_len:
                left_line.extend(" " * (right_len - left_len))
            elif right_len < left_len:
                right_line.extend(" " * (left_len - right_len))
            prev_was_space = False
        elif left is not None and right is None:
            if left.t == CharType.WHITESPACE:
                # Ignoring whitespace for left
                if not prev_was_space:
                    left_line.extend(" ")
                    right_line.extend(ColoredString(" ", "red", True))
                prev_was_space = True
            else:
                text = left.text()
                left_line.extend(" " * len(text))
                right_line.extend(ColoredString(text, "red", True))
                prev_was_space = False
        elif right is not None and left is None:
            if right.t == CharType.WHITESPACE:
                whitespace_str = right.text()
                if "\n" in whitespace_str:
                    whitespace = whitespace_str.split("\n")
                    first = whitespace[0]
                    left_line.extend(first)
                    right_line.extend(first)
                    for space in whitespace[1:]:
                        yield from flush()
                        left_line.extend(space)
                        right_line.extend(space)
                else:
                    left_line.extend(whitespace_str)
                    right_line.extend(whitespace_str)
                prev_was_space = True
            else:
                text = right.text()
                left_line.extend(" " * len(text))
                right_line.extend(ColoredString(text, "green"))
                prev_was_space = False
    yield from flush()


def add_tokens(old_alignment: Alignment, left: t.List[Token], right: t.List[Token]) -> Alignment:
    new_alignment: Alignment = []
    left_index = 0
    right_index = 0
    left_position = None
    right_position = None
    for a_left, a_right in reversed(old_alignment):
        right_position = a_right if a_right is not None else right_position
        if right_position is not None:
            while right_index < len(right) and right[right_index].start < right_position.start:
                new_alignment.append((None, right[right_index]))
                right_index += 1
        left_position = a_left if left is not None else left_position
        if left_position is not None:
            while left_index < len(left) and left[left_index].start < left_position.start:
                new_alignment.append((left[left_index], None))
                left_index += 1
        new_alignment.append(t.cast(AlignmentOperation[Token], (a_left, a_right)))

    for r in right[right_index:]:
        new_alignment.append((None, r))
    for l in left[left_index:]:
        new_alignment.append((l, None))
    return new_alignment


def align_texts(left_text: str, right_text: str) -> Alignment:
    all_left_tokens = list(token_parser(left_text))
    all_right_tokens = list(token_parser(right_text))
    return add_tokens(
        align(
            [x for x in all_left_tokens if x.t != CharType.WHITESPACE],
            [x for x in all_right_tokens if x.t != CharType.WHITESPACE],
        ),
        [x for x in all_left_tokens if x.t == CharType.WHITESPACE],
        [x for x in all_right_tokens if x.t == CharType.WHITESPACE],
    )


def main() -> None:
    # pylint: disable=import-outside-toplevel
    import sys

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        left_text = f.read()
    with open(sys.argv[2], "r", encoding="utf-8") as f:
        right_text = f.read()
    alignment = align_texts(left_text, right_text)
    for line in pretty_alignment(alignment):
        print(line)


if __name__ == "__main__":
    main()
