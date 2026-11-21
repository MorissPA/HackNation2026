import unittest

from riskminer import bip, db


class BipTests(unittest.TestCase):
    def test_wpf_quote_contains_only_matching_investment(self):
        pages = ["1.3.2.1 Plan gminy 2026 2028 24 000,00 "
                 "1.3.2.2 Budowa oczyszczalni w Modlikowicach 2023 2026 13 700 000,00 "
                 "1.3.2.3 Budowa wodociągu w Brochocinie 2025 2026 600 000,00"]
        self.assertEqual(bip._find(pages, "Modlik", "oczyszczal", financial=True),
                         (1, "1.3.2.2 Budowa oczyszczalni w Modlikowicach 2023 2026 13 700 000,00"))
        self.assertIsNone(bip._find(pages, "Modlik", "wodociąg", financial=True))

    def test_upgrade_previous_document_link(self):
        con = db.connect(":memory:")
        self.addCleanup(con.close)
        con.executescript("""
            DROP VIEW visible_event;
            DROP VIEW visible_fact;
            DROP TABLE document_link;
            CREATE TABLE document_link (project_id TEXT, url TEXT, updated_at TEXT, PRIMARY KEY(project_id,url));
            INSERT INTO document_link VALUES ('project','document','yesterday');
        """)
        db._migrate(con)
        db.upsert(con, "document_link", {"project_id": "project", "url": "document",
                  "review_status": "odrzucone", "updated_at": "today"}, ["project_id", "url"])
        db.upsert(con, "document_link", {"project_id": "project", "url": "document",
                  "reason": "numer BZP", "updated_at": "tomorrow"}, ["project_id", "url"])
        row = con.execute("SELECT reason, review_status FROM document_link").fetchone()
        self.assertEqual(tuple(row), ("numer BZP", "odrzucone"))
