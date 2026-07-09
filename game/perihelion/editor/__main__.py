"""CLI entry point: `uv run python -m perihelion.editor [file.json]`."""

from __future__ import annotations

import argparse


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="perihelion.editor")
    parser.add_argument("file", nargs="?", default=None,
                         help="level JSON to open (omit for a blank level)")
    args = parser.parse_args(argv)

    from .view import run

    run(args.file)


if __name__ == "__main__":
    main()
