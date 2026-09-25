"""Composition root: summarize a record of model calls (chapter 26).

python -m helpdesk.calls FILE [FILE ...]

python -m helpdesk.gate run --record FILE writes a record: one line a call, with the model, how the
call ended, its tokens and cost, how long it took and a fingerprint of the request. This prints, by
part and model, how many calls there were, what they sent and cost, and how many failed, and says
which token counts are the provider's and which are estimates.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from helpdesk.kb import CHARS_PER_TOKEN
from helpdesk.model.calls import Call, read, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.calls", description="Summarize call records.")
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    args = parser.parse_args(argv)
    calls: list[Call] = []
    for path in args.files:
        if not path.exists():
            print(f"{path}: no such file. python -m helpdesk.gate run --record FILE writes one.")
            return 1
        try:
            calls += read(path)
        except ValueError as error:
            print(error)
            return 1
    names = ", ".join(str(p) for p in args.files)
    print(f"{names}: " + "\n".join(summary(calls, CHARS_PER_TOKEN)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
