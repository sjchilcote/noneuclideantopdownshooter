"""CLI entry point: `uv run python -m perihelion [options]`."""

from __future__ import annotations

import argparse


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="perihelion")
    parser.add_argument("--level", type=str, default=None,
                         help="path to a level JSON file (overrides the campaign manifest)")
    parser.add_argument("--seed", type=int, default=None, help="sim RNG seed")
    parser.add_argument("--scale", type=int, default=None,
                         help="integer pixel scale for the window (default: fit 1440x810)")
    parser.add_argument("--mute", action="store_true", help="disable all audio")
    parser.add_argument("--fps", action="store_true", help="show the fps overlay")
    parser.add_argument("--autoplay", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    from .app import App

    app = App(args)
    app.run()


if __name__ == "__main__":
    main()
