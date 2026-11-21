import json
import unittest
from unittest.mock import Mock, patch

from riskminer import config, db, expert, llm


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
        return Mock(status_code=200, json=lambda: {"choices": [{"message": {"content": json.dumps({"wynik": result})}}]})

    @patch("riskminer.llm.requests.post")
    def test_evidence_repeat_and_expert_decision(self, post):
        post.return_value = self.response({"kategoria": "R04", "przyczyna": "Oczekiwanie na decyzję.", "fragment_id": 2})
        self.assertEqual(llm.analyze_project(self.con, "P")["created"], 1)
        event = self.con.execute("SELECT * FROM event WHERE kind='propozycja'").fetchone()
        self.assertEqual((event["quote"], event["source_section"]), ("Oczekiwanie na decyzję.", "pkt 4"))
        expert.decide_event(self.con, event["id"], "reject")
        self.assertEqual(llm.analyze_project(self.con, "P")["cached"], 1)
        self.assertEqual(post.call_count, 1)

    @patch("riskminer.llm.requests.post")
    def test_invalid_and_abstention(self, post):
        for code, index in [("R99", 1), ("R01", 0), ("R01", True)]:
            post.return_value = self.response({"kategoria": code, "przyczyna": "opis", "fragment_id": index})
            with self.assertRaises(llm.ModelError):
                llm.analyze_project(self.con, "P")
        self.assertEqual(self.con.execute("SELECT count(*) FROM llm_run").fetchone()[0], 0)
        post.return_value = self.response(None)
        self.assertEqual(llm.analyze_project(self.con, "P")["abstained"], 1)
        self.assertEqual(llm.analyze_project(self.con, "P")["cached"], 1)

    @patch("riskminer.llm.requests.post")
    def test_changed_evidence_invalidates_pending_proposal(self, post):
        post.return_value = self.response({"kategoria": "R04", "przyczyna": "Decyzja.", "fragment_id": 2})
        llm.analyze_project(self.con, "P")
        with self.con:
            self.con.execute("UPDATE event SET quote='Nowe źródło.' WHERE event_type='zmiana_umowy'")
        self.assertEqual(self.con.execute("SELECT count(*) FROM event WHERE kind='propozycja'").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM llm_run").fetchone()[0], 0)

    @patch("riskminer.llm.requests.post")
    def test_rejected_bip_source_is_excluded(self, post):
        with self.con:
            self.con.execute("DELETE FROM event")
            self.con.execute("INSERT INTO document(url,source) VALUES('bip-url','BIP')")
            self.con.execute("""INSERT INTO document_link(project_id,url,relation,review_status)
                    VALUES('P','bip-url','powiązana inwestycja','odrzucone')""")
            self.con.execute("""INSERT INTO event(project_id,event_type,title,quote,source_url,source_section)
                    VALUES('P','dokument BIP','Decyzja','Uzasadnienie decyzji.','bip-url','str. 1')""")
        self.assertEqual(llm.analyze_project(self.con, "P")["sources"], 0)
        post.assert_not_called()

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
