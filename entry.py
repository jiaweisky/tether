"""PyInstaller entry point: import tether as a package so relative imports work."""

from tether.__main__ import main

if __name__ == "__main__":
    main()
