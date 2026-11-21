"""Przypadki z audytu MFiPR. Testy używają bazy w pamięci i lokalnych odpowiedzi BZP."""
import asyncio
import io
import json
import unittest
from unittest.mock import Mock

from fastapi import HTTPException, UploadFile

import api
from riskminer import analysis, db, expert, importer, llm, pipeline, report


WATER = "Budowa wodociągu: łącznie 5 km, w tym 3 km sieci głównej i 2 km odgałęzień. Dofinansowanie 2 mln zł. Budżet inwestycji 8 mln zł."
LIBRARY = "Wyposażenie czytelni miejskiej w nowe meble biblioteczne. Budżet 2 mln zł."
OLAWA = "2022/BZP 00058537/01"
STEKLIN = "2024/BZP 00349631/01"


class FeatureTests(unittest.TestCase):
    def test_grant_and_components_do_not_replace_totals(self):
        for text in (WATER, "Budżet inwestycji: 8 000 000 PLN. Dofinansowanie 2 mln zł. "
                            "Sieć ma 5 km, w tym odgałęzienia o długości 2000 m."):
            with self.subTest(text=text):
                features = analysis.extract_features(text)
                self.assertEqual(features["scale"]["length_km"]["value"], 5)
                self.assertEqual(features["budget_pln"]["value"], 8_000_000)
                self.assertIn("Budżet", features["budget_pln"]["source"])
                self.assertFalse(features["conflicts"])

    def test_budget_range_keeps_both_options(self):
        features = analysis.extract_features("Budżet inwestycji 8 mln lub 10 mln zł.")
        self.assertIsNone(features["budget_pln"])
        self.assertEqual([v["value"] for v in features["conflicts"]["budget_pln"]], [8e6, 10e6])

    def test_grant_alone_and_depth(self):
        features = analysis.extract_features("Dofinansowanie 2 mln zł. Sieć ma 750 m, głębokość 2 m.")
        self.assertIsNone(features["budget_pln"])
        self.assertEqual(features["scale"]["length_km"]["value"], .75)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.addCleanup(self.con.close)

    def project(self, pid="P", name="Budowa wodociągu", status="Zakończone"):
        self.con.execute("INSERT INTO project(project_id,name,status,created_at,updated_at) VALUES(?,?,?,'','')",
                         (pid, name, status))

    def link(self, pid, ocid, method="numer_bzp", status="potwierdzone"):
        return self.con.execute("""INSERT INTO project_link(project_id,ocid,method,status,part_no,created_at,updated_at)
                                 VALUES(?,?,?,?,0,'','')""", (pid, ocid, method, status)).lastrowid

    def contract(self, ocid, performing="wykonanie"):
        self.con.execute("""INSERT INTO contract(ocid,value,paid_total,signed_date,planned_end,actual_end,performing_notice)
                          VALUES(?,8000000,8800000,'2024-01-01','2024-10-01','2024-10-10',?)""", (ocid, performing))

    def risk(self, code, ocid=None, url=None):
        return self.con.execute("""INSERT INTO event(project_id,ocid,event_type,kind,title,quote,source_url,source_section)
                                VALUES('P',?,'ryzyko','propozycja',?,'Oczekiwanie na decyzję wodnoprawną.',?,'pkt 1')""",
                                (ocid, code, url)).lastrowid

    def import_bzp(self, number):
        header = "Identyfikator rekordu;Nazwa przedsięwzięcia;Rodzaj identyfikatora publicznego;Identyfikator publiczny;Identyfikator odbiorcy"
        content = f"{header}\nP;Budowa sieci w Oławie;Ogłoszenie BZP;{number};9121715754\n"
        counts = importer.import_file(self.con, "projekty.csv", content.encode())["counts"]
        self.assertEqual(counts["błąd"], 0)

    def fetch(self, number, nip, title, ocid="a", reference=False):
        client = Mock()
        meta = {"noticeNumber": number, "noticeType": "ContractNotice", "organizationNationalId": nip,
                "orderObject": title, "tenderId": ocid}
        client.find_by_number.return_value = None if reference else meta
        client.find_via_references.return_value = (meta, "numer w odwołaniu")
        client.related_notices.return_value = ([], "cache testowy")
        result = pipeline.fetch_project(self.con, "P", client, log=lambda _: None)
        return result, client

    def test_reimport_foreign_notice_archives_only_automatic_link(self):
        self.import_bzp(OLAWA)
        ok, _ = self.fetch(OLAWA, "PL 912-171-57-54", "Budowa sieci w Oławie")
        self.assertEqual(ok["status"], "ok")
        self.contract("a")
        event = self.risk("R04", "a")
        expert.decide_event(self.con, event, "accept")
        manual = self.link("P", "manual", method="numer_bzp")
        self.con.execute("INSERT INTO expert_decision(target,target_id,decision,created_at) VALUES('project_link',?,'zaakceptowane','')",
                         (manual,))
        manual_event = self.risk("R07", "manual")
        self.con.execute("UPDATE event SET updated_at='2000-01-01' WHERE id=?", (manual_event,))
        self.import_bzp(STEKLIN)
        before = api.project_card("P", self.con)
        self.assertEqual([l["ocid"] for l in before["links"]], ["manual"])
        self.assertFalse(before["contracts"])
        result, client = self.fetch(STEKLIN, "8792466869", "Oczyszczalnia w Steklinie", "s")
        self.assertEqual(result["status"], "do_weryfikacji")
        self.assertIn("NIP", result["message"])
        client.related_notices.assert_not_called()
        card = api.project_card("P", self.con)
        self.assertEqual([row["id"] for row in card["events"]], [manual_event])
        self.assertEqual([l["ocid"] for l in card["links"]], ["manual"])
        self.assertEqual(self.con.execute("SELECT status FROM event WHERE id=?", (event,)).fetchone()[0], "zaakceptowane")
        self.import_bzp(OLAWA)
        self.fetch(OLAWA, "9121715754", "Budowa sieci w Oławie")
        card = api.project_card("P", self.con)
        self.assertEqual({l["ocid"] for l in card["links"]}, {"a", "manual"})
        self.assertEqual({row["id"] for row in card["events"]}, {manual_event, event})

    def test_exact_number_and_reference_both_require_buyer_and_scope(self):
        self.import_bzp(OLAWA)
        for nip, title, reference in [
                ("", "Budowa sieci w Oławie", False),
                ("9121715754", "Budowa sieci w Steklinie", False),
                ("8792466869", "Budowa sieci w Oławie", True)]:
            with self.subTest(nip=nip, reference=reference):
                result, client = self.fetch(OLAWA, nip, title, reference=reference)
                self.assertEqual(result["status"], "do_weryfikacji")
                client.related_notices.assert_not_called()
        self.link("P", "a", status="odrzucone")
        result, _ = self.fetch(OLAWA, "9121715754", "Budowa sieci w Oławie")
        self.assertEqual(result["status"], "do_weryfikacji")
        self.assertFalse(api.project_card("P", self.con)["links"])

    def test_requested_part_must_exist_in_result(self):
        self.import_bzp(OLAWA)
        self.con.execute("UPDATE project SET part_no=7 WHERE project_id='P'")
        result, _ = self.fetch(OLAWA, "9121715754", "Budowa sieci w Oławie")
        self.assertEqual(result["status"], "do_weryfikacji")
        self.assertIn("części 7", result["message"])
        self.assertFalse(api.project_card("P", self.con)["links"])

    def historical_cases(self):
        for pid in ("W1", "W2", "W3", "pending", "building", "no-evidence", "library"):
            name = "Budowa biblioteki" if pid == "library" else "Budowa wodociągu"
            self.project(pid, name, "W toku" if pid == "building" else "Zakończone")
            self.link(pid, pid, status="proponowane" if pid == "pending" else "potwierdzone")
            self.contract(pid, None if pid == "no-evidence" else "wykonanie")

    def test_forecast_requires_relevant_completed_cases_above_threshold(self):
        self.historical_cases()
        for result in (analysis.analyze(self.con, LIBRARY), analysis.analyze(self.con, WATER, min_score=101)):
            self.assertEqual(result["similar"], [])
            self.assertIsNone(result["comparison"]["confidence"])
            self.assertNotIn("budget_after_growth", result["comparison"])
        single = analysis.analyze(self.con, WATER, top_k=1)
        self.assertEqual(len(single["similar"]), 1)
        self.assertNotIn("budget_after_growth", single["comparison"])
        result = analysis.analyze(self.con, WATER)
        self.assertEqual({s["project_id"] for s in result["similar"]}, {"W1", "W2", "W3"})
        self.assertEqual(result["comparison"]["budget_after_growth"]["value"], 8_800_000)
        net = analysis.analyze(self.con, WATER.replace("8 mln zł.", "8 mln zł netto."))
        self.assertNotIn("budget_after_growth", net["comparison"])

    def test_conflicting_source_values_require_explicit_choice_including_export(self):
        self.historical_cases()
        text = "Budowa wodociągu. Wariant A: budżet 8 mln zł, trasa 5 km. Wariant B: budżet 10 mln zł, trasa 6 km."
        result = api.run_analysis(api.AnalysisRequest(text=text), self.con)
        conflicts = result["features"]["conflicts"]
        self.assertEqual({c["value"] for c in conflicts["budget_pln"]}, {8e6, 10e6})
        self.assertEqual({c["value"] for c in conflicts["length_km"]}, {5, 6})
        self.assertNotIn("budget_after_growth", result["comparison"])
        invalid = api.run_analysis(api.AnalysisRequest(text=text, choices={"budget_pln": 1, "length_km": 5}), self.con)
        self.assertNotIn("budget_after_growth", invalid["comparison"])
        req = api.AnalysisRequest(text=text, choices={"budget_pln": 10e6, "length_km": 6})
        exported = json.loads(api.export_analysis(req, "json", self.con).body)
        self.assertTrue(exported["features"]["budget_pln"]["selected"])
        self.assertEqual(exported["comparison"]["budget_after_growth"]["value"], 11e6)

    def test_rejected_bip_exemplar_leaves_history_and_cannot_teach_model(self):
        self.project()
        url = "https://example.test/zagrodno_2_885.pdf"
        self.con.execute("INSERT INTO document(url,source) VALUES(?,'BIP')", (url,))
        self.con.execute("INSERT INTO document_link(project_id,url,relation) VALUES('P',?,'projekt')", (url,))
        event = self.risk("R04", url=url)
        expert.decide_event(self.con, event, "accept", exemplar=True)
        def examples():
            return llm.expert_examples(self.con, "Oczekiwanie na decyzję wodnoprawną.", exclude_project="inny")
        self.assertEqual(examples()[0]["kategoria"], "R04")
        api.document_decision("P", api.DocumentDecision(url=url, action="reject"), self.con)
        self.assertEqual(examples(), [])
        self.assertEqual(self.con.execute("SELECT exemplar FROM event WHERE id=?", (event,)).fetchone()[0], 1)
        api.document_decision("P", api.DocumentDecision(url=url, action="accept"), self.con)
        self.assertEqual(examples()[0]["kategoria"], "R04")

    def test_contract_results_are_scoped_context_for_expert_review(self):
        self.project()
        for ocid, value in (("steklin", 277), ("other", 30)):
            self.link("P", ocid)
            self.con.execute("""INSERT INTO fact(project_id,ocid,kind,key,label,value_num,unit)
                              VALUES('P',?,'obliczenie','opoznienie_vs_pierwotny_dni','Opóźnienie',?,'dni')""", (ocid, value))
        for code, ocid in (("R04", "steklin"), ("R07", "steklin"), ("R03", "other"), ("R02", None)):
            self.risk(code, ocid)
        effect = "Z powodu oczekiwania na decyzję przedłużono termin o 30 dni."
        self.con.execute("UPDATE event SET quote=? WHERE title='R04'", (effect,))
        queue = api.verify_queue(self.con)
        self.assertEqual({i["code"]: i["event_effect_quote"] for i in queue},
                         {"R04": effect, "R07": None, "R03": None, "R02": None})
        self.assertTrue(all("impact" not in item for item in queue))
        self.assertEqual({i["code"]: [v["value_num"] for v in i["contract_context"]] for i in queue},
                         {"R04": [277], "R07": [277], "R03": [30], "R02": []})

    def test_form_upload_and_export_use_same_trimmed_character_limit(self):
        self.assertEqual(api.stats(self.con)["analysis_min_chars"], 30)
        for length in (29, 30):
            text = "  " + "ą" * length + " "
            req = api.AnalysisRequest(text=text)
            upload = UploadFile(filename="opis.txt", file=io.BytesIO(text.encode()))
            for call in (lambda: api.run_analysis(req, self.con), lambda: api.export_analysis(req, "json", self.con),
                         lambda: asyncio.run(api.run_analysis_file(upload, self.con))):
                if length == 29:
                    with self.assertRaises(HTTPException) as ctx:
                        call()
                    self.assertEqual(ctx.exception.status_code, 400)
                    self.assertIn("30 znaków", ctx.exception.detail)
                else:
                    self.assertIsNotNone(call())
        self.assertTrue(report.build(self.con)["analyses"])
