"""Allow `python -m research_memory` to run the unified CLI."""

from .cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())
