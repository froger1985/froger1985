#!/usr/bin/env python3
"""Start the Mercari→eBay sourcing web dashboard.

Usage:
    python run_web.py              # http://localhost:5000
    python run_web.py --port 8080
"""
import argparse
import sys
from pathlib import Path

# Make sure the package root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.app import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sourcing tool web dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n🛍  Sourcing Tool Dashboard")
    print(f"   URL: http://localhost:{args.port}")
    print(f"   Ctrl+C で停止\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
