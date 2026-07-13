from collections.abc import Callable
from typing import Any, TypeVar

from typing_extensions import dataclass_transform

T = TypeVar("T")

@dataclass_transform()
class Struct:
    def __init_subclass__(cls, **kwargs: Any) -> None: ...

from . import json  # noqa: F401
