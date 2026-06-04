from pathlib import Path
import sys

import uvicorn

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from doc_translator.worker_service import worker_app


if __name__ == "__main__":
    uvicorn.run(worker_app, host="0.0.0.0", port=8001)
