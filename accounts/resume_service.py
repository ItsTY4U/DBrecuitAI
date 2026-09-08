"""
Deprecated: accounts.resume_service has been consolidated into jobs.ai.
This module re-exports extract_resume_text and parse_resume for backwards compatibility.
"""
from jobs.ai import extract_resume_text, parse_resume, get_genai_client

__all__ = ["extract_resume_text", "parse_resume", "get_genai_client"]