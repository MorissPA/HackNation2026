from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

from riskminer import config, db, expert, llm, local_model


class RiskModelTests(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.addCleanup(self.con.close)
        with self.con:
            self.con.execute("INSERT INTO project(project_id,name,created_at,updated_at) VALUES('P','Projekt','','')")
            self.con.execute("""INSERT INTO event(project_id,event_type,title,quote,source_section,source_notice)
                    VALUES('P','zmiana_umowy','Zmiana nr 1','Przesunięto termin robót. Oczekiwanie na decyzję.','pkt 4','BZP 1')""")
        self.enter_config = patch.object(config, "LLM_PROVIDER", "llama.cpp")
        self.enter_config.start()
        self.addCleanup(self.enter_config.stop)

    def response(self, result):
        return json.dumps({"wynik": result})

    @patch("riskminer.llm.local_model.complete")
    def test_evidence_repeat_and_expert_decision(self, complete):
        complete.return_value = self.response({"kategoria": "R04", "przyczyna": "Oczekiwanie na decyzję.", "fragment_id": 2})
        self.assertEqual(llm.analyze_project(self.con, "P")["created"], 1)
        event = self.con.execute("SELECT * FROM event WHERE kind='propozycja'").fetchone()
        self.assertEqual((event["quote"], event["source_section"]), ("Oczekiwanie na decyzję.", "pkt 4"))
        expert.decide_event(self.con, event["id"], "reject")
        self.assertEqual(llm.analyze_project(self.con, "P")["cached"], 1)
        self.assertEqual(complete.call_count, 1)

    @patch("riskminer.llm.local_model.complete")
    def test_invalid_and_abstention(self, complete):
        for code, index in [("R99", 1), ("R01", 0), ("R01", True)]:
            complete.return_value = self.response({"kategoria": code, "przyczyna": "opis", "fragment_id": index})
            with self.assertRaises(llm.ModelError):
                llm.analyze_project(self.con, "P")
        self.assertEqual(self.con.execute("SELECT count(*) FROM llm_run").fetchone()[0], 0)
        complete.return_value = self.response(None)
        self.assertEqual(llm.analyze_project(self.con, "P")["abstained"], 1)
        self.assertEqual(llm.analyze_project(self.con, "P")["cached"], 1)

    @patch("riskminer.llm.local_model.complete")
    def test_changed_evidence_invalidates_pending_proposal(self, complete):
        complete.return_value = self.response({"kategoria": "R04", "przyczyna": "Decyzja.", "fragment_id": 2})
        llm.analyze_project(self.con, "P")
        with self.con:
            self.con.execute("UPDATE event SET quote='Nowe źródło.' WHERE event_type='zmiana_umowy'")
        self.assertEqual(self.con.execute("SELECT count(*) FROM event WHERE kind='propozycja'").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM llm_run").fetchone()[0], 0)

    @patch("riskminer.llm.local_model.complete")
    def test_rejected_bip_source_is_excluded(self, complete):
        with self.con:
            self.con.execute("DELETE FROM event")
            self.con.execute("INSERT INTO document(url,source) VALUES('bip-url','BIP')")
            self.con.execute("""INSERT INTO document_link(project_id,url,relation,review_status)
                    VALUES('P','bip-url','powiązana inwestycja','odrzucone')""")
            self.con.execute("""INSERT INTO event(project_id,event_type,title,quote,source_url,source_section)
                    VALUES('P','dokument BIP','Decyzja','Uzasadnienie decyzji.','bip-url','str. 1')""")
        self.assertEqual(llm.analyze_project(self.con, "P")["sources"], 0)
        complete.assert_not_called()

    @patch("riskminer.llm.requests.post")
    def test_anthropic_and_ollama_protocols(self, post):
        raw = json.dumps({"wynik": None})
        with patch.object(config, "LLM_PROVIDER", "anthropic"), patch.object(config, "LLM_API_KEY", "test"):
            post.return_value = Mock(status_code=200, json=lambda: {"content": [{"type": "text", "text": raw}]})
            self.assertIsNone(llm.infer("Oczekiwanie na decyzję organu.", "Zmiana"))
            self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "test")
        with patch.object(config, "LLM_PROVIDER", "ollama"):
            post.return_value = Mock(status_code=200, json=lambda: {"message": {"content": raw}})
            self.assertIsNone(llm.infer("Oczekiwanie na decyzję organu.", "Zmiana"))
            self.assertFalse(post.call_args.kwargs["json"]["stream"])

class GuardrailTests(unittest.TestCase):
    """P1: formułki bez przyczyny, przyczyna bez pokrycia w cytacie, duplikaty sekcji, pewność."""
    def setUp(self):
        self.con = db.connect(":memory:")
        self.addCleanup(self.con.close)
        with self.con:
            self.con.execute("INSERT INTO project(project_id,name,created_at,updated_at) VALUES('P','Projekt','','')")
        patcher = patch.object(config, "LLM_PROVIDER", "llama.cpp")
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_source(self, quote, section="pkt 5.3", title="Zmiana umowy"):
        with self.con:
            self.con.execute("""INSERT INTO event(project_id,event_type,title,quote,source_section,source_notice)
                    VALUES('P','zmiana_umowy',?,?,?,'BZP 1')""", (title, quote, section))

    def test_boilerplate_only_is_abstention_without_model(self):
        statute = ("5.3.) Przyczyny dokonania zmian umowy/umowy ramowej: Zmiana konieczna z powodu okoliczności, "
                   "których zamawiający działający z należytą starannością nie mógł przewidzieć.")
        self.assertEqual(llm.split_excerpts(statute), [])
        self.assertEqual(llm.split_excerpts(statute + "\nW związku z pracami na terenie ronda (inwestycja ZZDW)"),
                         ["W związku z pracami na terenie ronda (inwestycja ZZDW)"])
        with patch("riskminer.llm.local_model.complete") as complete:
            self.assertIsNone(llm.infer(statute, "Zmiana"))
            complete.assert_not_called()

    @patch("riskminer.llm.local_model.complete")
    def test_cause_copied_from_instructions_is_rejected(self, complete):
        complete.return_value = json.dumps({"wynik": {"kategoria": "R13", "fragment_id": 1,
                                                       "przyczyna": "Zmiana dokonana z powodu braku środków na płatność."}})
        self.assertIsNone(llm.infer("Ponadto wstrzymano roboty z powodu braku ustalenia granic.", "Zmiana"))

    @patch("riskminer.llm.local_model.complete")
    def test_duplicate_sections_share_one_proposal(self, complete):
        text = "Ujawniono niekorzystne warunki gruntowe oraz wysoki poziom wód gruntowych."
        self.add_source("5.3.) Przyczyny dokonania zmian umowy/umowy ramowej: " + text)
        self.add_source("5.4.4.) Przyczyny dokonania zmian: " + text, section="pkt 5.4.4", title="Zmiana umowy nr 1")
        complete.return_value = json.dumps({"wynik": {"kategoria": "R02", "przyczyna": text, "fragment_id": 1}})
        counts = llm.analyze_project(self.con, "P")
        self.assertEqual((counts["created"], counts["duplicates"], complete.call_count), (1, 1, 1))
        e = self.con.execute("SELECT * FROM event WHERE kind='propozycja'").fetchall()
        self.assertEqual(len(e), 1)
        self.assertIn("pkt 5.4.4", e[0]["details"])
        self.assertEqual(e[0]["confidence"], "wysoka")  # reguły też wskazują R02 („warunki gruntowe”)
        self.assertEqual(llm.analyze_project(self.con, "P")["created"], 0)  # ponowne uruchomienie – bez zmian
        self.assertEqual(self.con.execute("SELECT count(*) FROM event WHERE kind='propozycja'").fetchone()[0], 1)

    @patch("riskminer.llm.local_model.complete")
    def test_disagreement_with_rules_is_low_confidence(self, complete):
        text = "Agregat zaprojektowany w 2019 roku nie jest obecnie dostępny."
        self.add_source(text)
        complete.return_value = json.dumps({"wynik": {"kategoria": "R07", "przyczyna": text, "fragment_id": 1}})
        llm.analyze_project(self.con, "P")
        self.assertEqual(self.con.execute("SELECT confidence FROM event WHERE kind='propozycja'").fetchone()[0], "niska")


class P2Tests(GuardrailTests):
    """P2: dwie przyczyny, przykłady eksperta bez przecieku z projektu, ocena na zbiorze testowym."""
    @patch("riskminer.llm.local_model.complete")
    def test_two_causes_become_two_proposals_and_are_replaced_together(self, complete):
        self.add_source("Wstrzymano roboty z powodu braku ustalenia granic działek. Agregat zaprojektowany w 2019 roku jest niedostępny.")
        complete.return_value = json.dumps({"wyniki": [
            {"kategoria": "R03", "przyczyna": "Brak ustalenia granic działek.", "fragment_id": 1},
            {"kategoria": "R12", "przyczyna": "Agregat jest niedostępny.", "fragment_id": 2}]})
        self.assertEqual(llm.analyze_project(self.con, "P")["created"], 2)
        titles = [r[0] for r in self.con.execute("SELECT title FROM event WHERE kind='propozycja' ORDER BY id")]
        self.assertTrue(titles[1].endswith("#2"))
        with self.con:  # zmiana źródła usuwa obie oczekujące propozycje
            self.con.execute("UPDATE event SET quote='Nowy tekst przyczyny zmiany umowy.' WHERE event_type='zmiana_umowy'")
        self.assertEqual(self.con.execute("SELECT count(*) FROM event WHERE kind='propozycja'").fetchone()[0], 0)

    def test_expert_examples_skip_same_project(self):
        with self.con:
            self.con.execute("INSERT INTO project(project_id,name,created_at,updated_at) VALUES('Q','Inny','','')")
            for pid in ("P", "Q"):
                self.con.execute("""INSERT INTO event(project_id,event_type,kind,status,title,quote,source_notice)
                        VALUES(?,'ryzyko','propozycja','zaakceptowane','R02 Stan','Natrafiono na grunt skalny w wykopie.',?)""",
                                 (pid, f"BZP {pid}"))
        self.assertEqual(len(llm.expert_examples(self.con, "Grunt skalny w wykopie przy drodze.")), 1)  # ten sam cytat raz
        ex = llm.expert_examples(self.con, "Grunt skalny w wykopie przy drodze.", exclude_project="Q")
        self.assertEqual(ex, [{"cytat": "Natrafiono na grunt skalny w wykopie.", "kategoria": "R02"}])

    @patch("riskminer.llm.local_model.complete")
    def test_evaluation_scores_against_gold(self, complete):
        from riskminer import evaluate
        self.add_source("Ujawniono niekorzystne warunki gruntowe w wykopach.")
        self.add_source("Obwieszczenie o wszczęciu postępowania w sprawie decyzji.", section="str. 1", title="Obwieszczenie")
        with TemporaryDirectory() as d:
            gold = Path(d) / "gold.csv"
            with open(gold, "w", encoding="utf-8") as fh:
                fh.write(",".join(evaluate.FIELDS) + "\n")
                fh.write(f"P,{evaluate.text_key('Ujawniono niekorzystne warunki gruntowe w wykopach.')},R02,,zespół,,\n")
                fh.write(f"P,{evaluate.text_key('Obwieszczenie o wszczęciu postępowania w sprawie decyzji.')},brak,R04,zespół,,\n")
            complete.side_effect = [
                json.dumps({"wyniki": [{"kategoria": "R02", "przyczyna": "Niekorzystne warunki gruntowe.", "fragment_id": 1}]}),
                json.dumps({"wyniki": [{"kategoria": "R04", "przyczyna": "Postępowanie w sprawie decyzji.", "fragment_id": 1}]})]
            rep = evaluate.evaluate(self.con, gold, log=lambda m: None)
        self.assertEqual((rep["n"], rep["correct"], rep["partial"], rep["score_pct"]), (2, 1, 1, 75.0))
        self.assertIn("| P |", evaluate.to_markdown(rep))


class EmbeddedModelTests(unittest.TestCase):
    @patch("riskminer.local_model.requests.get")
    def test_download_publishes_only_complete_verified_weights(self, get):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "qwen.gguf"
            response = get.return_value.__enter__.return_value
            response.iter_content.return_value = [b"gguf"]
            with self.assertRaises(local_model.LocalModelError):
                local_model._download(path)
            self.assertEqual(list(path.parent.iterdir()), [])
            with patch.object(local_model, "MODEL_SHA256", hashlib.sha256(b"gguf").hexdigest()):
                local_model._download(path)
            self.assertEqual(path.read_bytes(), b"gguf")

    @patch("riskminer.local_model.requests.get")
    def test_local_weights_loaded_once_without_network(self, get):
        with TemporaryDirectory() as directory, patch("llama_cpp.Llama") as llama:
            path = Path(directory) / "qwen.gguf"
            path.touch()
            self.addCleanup(local_model._load.cache_clear)
            with patch.object(config, "LLM_MODEL_PATH", path):
                llama.return_value.create_chat_completion.return_value = {
                    "choices": [{"message": {"content": '{"wynik":null}'}}]}
                for _ in range(2):
                    self.assertEqual(local_model.complete([], {}), '{"wynik":null}')
            llama.assert_called_once()
            get.assert_not_called()
