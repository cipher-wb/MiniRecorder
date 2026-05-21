"""Dev launcher: `python run.py`."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.main import main
if __name__ == "__main__":
    sys.exit(main())
