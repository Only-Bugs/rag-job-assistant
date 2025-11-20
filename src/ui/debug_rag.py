# debug_rag.py
import sys
from pathlib import Path
import traceback

# Go up from /src/ui to the repo root, then into src/
ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

print("SRC_DIR:", SRC_DIR)

from rag.generation.generator import generate_application_package

DUMMY_JD = """
We are looking for a Machine Learning Engineer with experience in Python, PyTorch,
TensorFlow, and cloud deployment (AWS). You will build end-to-end ML systems,
work with LLMs and RAG pipelines, and collaborate with product teams.
"""

print("Calling generate_application_package...")
try:
    res = generate_application_package(DUMMY_JD, save_to_disk=False)
    print("✅ Success. Keys:", list(res.keys()))
except Exception as e:
    print("❌ Python exception:", e)
    print("---- TRACEBACK ----")
    traceback.print_exc()
