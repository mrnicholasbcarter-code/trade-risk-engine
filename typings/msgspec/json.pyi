from typing import Any, TypeVar, overload

T = TypeVar("T")

@overload
def decode(buf: str | bytes | bytearray, *, type: type[T]) -> T: ...

@overload
def decode(buf: str | bytes | bytearray, *, type: None = ...) -> Any: ...

def encode(obj: Any) -> bytes: ...
