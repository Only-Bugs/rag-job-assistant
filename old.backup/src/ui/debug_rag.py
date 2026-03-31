# debug_rag.py
import sys
import importlib.util
from pathlib import Path
import time
import traceback

# Go up from /src/ui to the repo root, then into src/
ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

print("SRC_DIR:", SRC_DIR)
LOGGING_PATH = SRC_DIR / "rag" / "utils" / "logging.py"
spec = importlib.util.spec_from_file_location("rag_timing_logging", LOGGING_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load logging utility from {LOGGING_PATH}")
logging_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logging_module)
timed_call = logging_module.timed_call

DUMMY_JD = """
We are looking for a Machine Learning Engineer with experience in Python, PyTorch,
TensorFlow, and cloud deployment (AWS). You will build end-to-end ML systems,
work with LLMs and RAG pipelines, and collaborate with product teams.
"""

print("Calling generate_application_package...")
try:
    from rag.generation.generator import generate_application_package

    res = timed_call(generate_application_package, DUMMY_JD, save_to_disk=False)
    print("Success. Keys:", list(res.keys()))
except Exception as e:
    print("Python exception:", e)
    print("---- TRACEBACK ----")
    traceback.print_exc()


def _demo_work(duration_sec: float) -> str:
    time.sleep(duration_sec)
    return "done"


def _demo_fail() -> None:
    raise RuntimeError("example failure")


print("Running timing demo calls...")
timed_call(_demo_work, 0.05)
try:
    timed_call(_demo_fail)
except RuntimeError:
    print("Captured expected demo failure after timing log.")
