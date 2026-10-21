import os, sys, unittest, tempfile, threading, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ORACLE_DB"] = tempfile.mktemp(suffix=".db")
import core

class T(unittest.TestCase):
    def test_sip_known_value(self):
        self.assertAlmostEqual(core.sip(5000, 12, 10)["value"], 1161695.38, delta=2)
        self.assertEqual(core.sip(1000, 0, 1)["value"], 12000)
    def test_swp_depletes(self):
        self.assertIsNotNone(core.swp(100000, 20000, 6, 2)["depleted_month"])
        self.assertIsNone(core.swp(1000000, 1000, 8, 5)["depleted_month"])
    def test_lic_irr_zero_growth(self):
        self.assertAlmostEqual(core.lic(100, 1, 1, 100)["effective_return_pct"], 0, delta=0.01)
    def test_bad_inputs(self):
        for f in (lambda: core.sip(-1, 5, 5), lambda: core.sip("a", 5, 5)):
            with self.assertRaises(ValueError): f()
    def test_forecast_honest(self):
        f = core.forecast(core.demo_df()["revenue"].values, 6)
        self.assertEqual(len(f["mean"]), 6); self.assertTrue(all(l <= m <= h for l, m, h in zip(f["lo"], f["mean"], f["hi"])))
        self.assertIn("naive", f["backtest_mae"]); self.assertTrue(f["beats_baseline"])
    def test_forecast_rejects_short_and_random_walk_has_no_edge(self):
        with self.assertRaises(ValueError): core.forecast([1, 2, 3], 6)
        import numpy as np
        rw = np.cumsum(np.random.default_rng(1).normal(0, 1, 300)) + 100
        self.assertFalse(core.forecast(rw, 5, 5)["beats_baseline"])
    def test_csv_validation(self):
        with self.assertRaises(ValueError): core.parse_csv("date,revenue\n2024-01-01,-5")
        with self.assertRaises(ValueError): core.parse_csv("a,b\n1,2")
        with self.assertRaises(ValueError): core.parse_csv("date,revenue\n2024-01-01,5\n2024-01-01,6")
    def test_no_keys_means_no_fake_data(self):
        os.environ.pop("ALPHAVANTAGE_KEY", None); os.environ.pop("CRICAPI_KEY", None)
        self.assertEqual(core.quote("gold")["status"], "not_configured"); self.assertEqual(core.cricket()["status"], "not_configured")
    def test_auth_roles_isolation(self):
        core.migrate(); a = core.register("a@x.com", "password1"); b = core.register("b@x.com", "password2")
        ua, ub = core.verify(a["token"]), core.verify(b["token"]); self.assertNotEqual(ua["ws"], ub["ws"])
        csv = core.demo_df().to_csv(index=False); core.save_dataset(ua, "mine.csv", csv)
        self.assertIn("mine.csv", core.workspace_dashboard(ua)["label"]); self.assertIn("SYNTHETIC", core.workspace_dashboard(ub)["label"])
        with self.assertRaises(PermissionError): core.save_dataset({**ub, "role": "viewer"}, "x.csv", csv)
        with self.assertRaises(ValueError): core.login("a@x.com", "wrongpass")
        self.assertIsNone(core.verify(a["token"][:-3] + "abc"))
    def test_chat_and_server(self):
        self.assertIn("1,161", core.chat("sip 5000 12 10", None))
        import server; from http.server import ThreadingHTTPServer
        s = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=s.serve_forever, daemon=True).start()
        u = f"http://127.0.0.1:{s.server_port}"
        d = json.load(urllib.request.urlopen(u + "/api/demo")); self.assertIn("SYNTHETIC", d["label"])
        r = urllib.request.Request(u + "/api/calc/sip", json.dumps({"monthly": 5000, "annual_pct": 12, "years": 10}).encode(), {"Content-Type": "application/json"})
        self.assertAlmostEqual(json.load(urllib.request.urlopen(r))["value"], 1161695.38, delta=2)
        self.assertIn(b"ORACLE", urllib.request.urlopen(u + "/").read()); s.shutdown()
if __name__ == "__main__": unittest.main()
