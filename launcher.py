"""Entry script for PyInstaller — imports src as a package so relative imports work."""
import sys
from src.main import main

if __name__ == "__main__":
    sys.exit(main())
