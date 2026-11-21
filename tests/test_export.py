import io
import json
import unittest
import zipfile

from riskminer import db, export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.addCleanup(self.con.close)
        ts = db.now()
        db.upsert(self.con, "project", {"project_id": "RM-1", "name": "Budowa oczyszczalni", "public_id_type": "Ogłoszenie BZP",
                                        "public_id": "2024/BZP 00000001/01", "created_at": ts, "updated_at": ts}, ["project_id"])
        db.upsert(self.con, "project_link", {"project_id": "RM-1", "ocid": "ocds-1", "part_no": 0, "method": "numer_bzp",
                                             "status": "potwierdzone", "created_at": ts, "updated_at": ts}, ["project_id", "ocid"])
        db.upsert(self.con, "fact", {"project_id": "RM-1", "kind": "obliczenie", "key": "wzrost_wyplaty_pct", "part_no": 0,
                                     "value_num": 40.3, "unit": "%", "source_notice": "2026/BZP 1/01", "updated_at": ts},
                  ["project_id", "key", "part_no", "source_notice"])

    def test_json_keeps_relations_and_sources(self):
        data = export.to_json(self.con)
        p = data["projekty"][0]
        self.assertEqual(p["project_id"], "RM-1")
        self.assertEqual(p["powiazania"][0]["ocid"], "ocds-1")
        self.assertEqual(p["fakty"][0]["value_num"], 40.3)
        self.assertEqual(p["fakty"][0]["source_notice"], "2026/BZP 1/01")
        json.dumps(data, default=str)  # serializowalne

    def test_csv_zip_has_every_table_and_readme(self):
        z = zipfile.ZipFile(io.BytesIO(export.to_csv_zip(self.con)))
        names = set(z.namelist())
        self.assertIn("CZYTAJ_MNIE.txt", names)
        self.assertTrue({f"{t}.csv" for t in export.TABLES} <= names)
        self.assertIn("wzrost_wyplaty_pct", z.read("fakty.csv").decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
