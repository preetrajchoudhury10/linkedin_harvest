import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def write_email_file(emails, role_label, output_dir, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{role_label}_{date_str}.txt"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        for email in sorted(emails):
            f.write(f"{email}\n")

    logger.info(f"Wrote {len(emails)} emails to {filepath}")
    return filepath


def categorize_and_write(ai_ml_pairs, backend_pairs, output_dir, email_db=None, date_str=None):
    ai_emails = [e for e, _ in ai_ml_pairs]
    backend_emails = [e for e, _ in backend_pairs]

    if email_db:
        ai_new = email_db.add_emails(ai_ml_pairs, "ai")
        backend_new = email_db.add_emails(backend_pairs, "backend")
        new_ai_emails = [e for e, _ in ai_new]
        new_backend_emails = [e for e, _ in backend_new]
    else:
        new_ai_emails = ai_emails
        new_backend_emails = backend_emails

    ai_file = write_email_file(new_ai_emails, "ai", output_dir, date_str)
    backend_file = write_email_file(new_backend_emails, "backend", output_dir, date_str)

    db_stats = email_db.breakdown() if email_db else None

    return {
        "ai": {
            "new": len(new_ai_emails),
            "total_found": len(ai_emails),
            "file": str(ai_file),
            "emails": new_ai_emails,
        },
        "backend": {
            "new": len(new_backend_emails),
            "total_found": len(backend_emails),
            "file": str(backend_file),
            "emails": new_backend_emails,
        },
        "db_stats": db_stats,
    }
