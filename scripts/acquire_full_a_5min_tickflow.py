"""
acquire_full_a_5min_tickflow.py
================================
TickFlow 5min K line batch downloader for CN A shares.
Saves to local Parquet with checkpoint/resume support.

Usage:
  python acquire_full_a_5min_tickflow.py [--data-dir DIR] [--count 500] [--delay 0.3] [--max-retries 5]

Each batch: up to 5 symbols, up to 500 5min bars each.
~5540 symbols = ~1108 API calls.
"""
