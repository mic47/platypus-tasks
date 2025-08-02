import io
import typing as t


class DummyWriter(io.TextIOBase):
    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def writelines(self, lines: t.Iterable[str]) -> None:  # type: ignore
        pass

    def __enter__(self) -> "DummyWriter":
        return self

    def __exit__(
        self, exc_type: t.Optional[type], exc_val: t.Optional[BaseException], exc_tb: t.Optional[object]
    ) -> None:
        return None
