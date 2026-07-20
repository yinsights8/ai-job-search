"""email_scanner: read-only Gmail ingestion for the job-search workflow.

Archives recruiter correspondence (inbound and outbound) under each tracked
job application folder, classified and linked to the existing
`outcome.md` and `job_search_tracker.csv` pipeline.

Public entry point: `python -m tools.email_scanner <subcommand>`.
"""

__version__ = "0.1.0"
