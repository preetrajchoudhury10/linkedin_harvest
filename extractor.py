import re
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

BLOCKED_DOMAINS = {
    "linkedin.com", "example.com", "domain.com", "email.com",
    "mail.com", "test.com", "yourcompany.com", "company.com",
    "yourdomain.com", "mydomain.com", "your.email", "company.co",
    "abc.com", "xyz.com", "domain.co", "site.com",
}


def is_valid_email(email):
    email_lower = email.lower()
    local_part, domain = email_lower.split("@", 1)
    if domain in BLOCKED_DOMAINS:
        return False
    if len(local_part) < 2 or len(domain) < 4:
        return False
    if re.search(r"(\.{2,}|_{2,})", email_lower):
        return False
    return True


def extract_emails(posts_with_keyword):
    email_set = set()
    keyword_map = {}

    for post_text, keyword in posts_with_keyword:
        found = EMAIL_REGEX.findall(post_text)
        for email in found:
            clean = email.strip().lower()
            if is_valid_email(clean):
                email_set.add(clean)
                if clean not in keyword_map:
                    keyword_map[clean] = keyword

    return list(email_set), keyword_map


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


def categorize_and_write(ai_ml_posts, backend_posts, output_dir, email_db=None, date_str=None):
    ai_emails, ai_keyword_map = extract_emails(ai_ml_posts)
    backend_emails, backend_keyword_map = extract_emails(backend_posts)

    if email_db:
        ai_new = email_db.add_emails([(e, ai_keyword_map.get(e, "")) for e in ai_emails], "ai")
        backend_new = email_db.add_emails([(e, backend_keyword_map.get(e, "")) for e in backend_emails], "backend")
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
