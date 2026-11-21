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
                    VALUES('P','zmiana_umowy','Zmiana nr 1','Zmiana terminu. Oczekiwanie na decyzję.','pkt 4','BZP 1')""")
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
            self.assertIsNone(llm.infer("Fragment.", "Zmiana"))
            self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "test")
        with patch.object(config, "LLM_PROVIDER", "ollama"):
            post.return_value = Mock(status_code=200, json=lambda: {"message": {"content": raw}})
            self.assertIsNone(llm.infer("Fragment.", "Zmiana"))
            self.assertFalse(post.call_args.kwargs["json"]["stream"])

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
