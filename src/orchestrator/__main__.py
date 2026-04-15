"""Allow `python -m orchestrator ...` in addition to the installed console script."""

from .cli import app

if __name__ == "__main__":
    app()
