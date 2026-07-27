import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.data = self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                return json.loads(self.db_path.read_text())
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupted DB, starting fresh: {e}")
        return {
            "version": 1,
            "ai_ml": {},
            "backend": {},
        }

    def _save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def is_seen(self, email: str) -> bool:
        email = email.lower()
        return (
            email in self.data["ai_ml"] or email in self.data["backend"]
        )

    def add_emails(self, emails_with_keyword: list, role: str):
        added = []
        for email, keyword in emails_with_keyword:
            email = email.lower()
            if self.is_seen(email):
                continue
            entry = {
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": keyword,
                "role": role,
            }
            if role == "ai":
                self.data["ai_ml"][email] = entry
            else:
                self.data["backend"][email] = entry
            added.append((email, keyword))
        self._save()
        return added

    def get_all_emails(self, role: str = None):
        if role == "ai":
            return list(self.data["ai_ml"].keys())
        if role == "backend":
            return list(self.data["backend"].keys())
        all_emails = set(self.data["ai_ml"].keys())
        all_emails.update(self.data["backend"].keys())
        return sorted(all_emails)

    def total_count(self):
        return len(self.data["ai_ml"]) + len(self.data["backend"])

    def breakdown(self):
        return {
            "ai": len(self.data["ai_ml"]),
            "backend": len(self.data["backend"]),
            "total": self.total_count(),
        }

    def export_all_txt(self, output_path: Path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# Master Email Database — {datetime.now().strftime('%Y-%m-%d')}\n")
            f.write(f"# Total: {self.total_count()} emails\n\n")

            f.write("===== AI/ML ENGINEER ROLES =====\n")
            for email, info in sorted(self.data["ai_ml"].items()):
                f.write(f"{email}  # {info['first_seen']} — {info['keyword']}\n")

            f.write("\n===== JAVA BACKEND ROLES =====\n")
            for email, info in sorted(self.data["backend"].items()):
                f.write(f"{email}  # {info['first_seen']} — {info['keyword']}\n")

        logger.info(f"Master DB exported to {output_path}")
        return output_path
