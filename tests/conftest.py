import pathlib
import sys

# Make scripts/ importable so tests can `from sanitize_ical import sanitize`
# without having to install the project or juggle PYTHONPATH in CI.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
