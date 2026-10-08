"""
MedUnderwrite AI — RAGAS Evaluation Runner Script

Runs RAGAS evaluation on 20 test queries and prints metric scores.

Usage:
    python backend/scripts/run_ragas_eval.py
"""
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.ragas_eval import main

if __name__ == "__main__":
    main()

