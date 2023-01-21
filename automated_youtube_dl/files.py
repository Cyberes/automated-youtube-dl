import tempfile
from pathlib import Path
from typing import Union


def create_directories(*paths: Union[str, Path]):
    for path in paths:
        resolve_path(path).mkdir(parents=True, exist_ok=True)


def mktemp(directory=True) -> Path:
    if directory:
        return Path(tempfile.mkdtemp())
    else:
        return Path(tempfile.mkstemp()[1])


def resolve_path(p: Union[str, Path]) -> Path:
    return Path(p).expanduser().absolute().resolve()
