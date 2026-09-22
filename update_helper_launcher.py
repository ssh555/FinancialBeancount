"""PyInstaller entry point for the standalone update helper."""

from beancount_dedup.update_helper import main

if __name__ == "__main__":
    raise SystemExit(main())
