"""PyInstaller entry point for the FinancialBeancount desktop application."""

from __future__ import annotations

from beancount_dedup.desktop_app import main

if __name__ == "__main__":
    main()
