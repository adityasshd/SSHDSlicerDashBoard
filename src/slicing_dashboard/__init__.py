"""
Video Slicing Dashboard — Scraping, Data Processing & Reporting System.

Extracts user-level video slicing completion data from the admin dashboard,
transforms it into reporting-ready datasets, and generates Excel reports.
"""
from .runtime import configure_numeric_threads

configure_numeric_threads()

__version__ = '0.1.0'
