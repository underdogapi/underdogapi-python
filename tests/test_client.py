import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from underdog_api import Client, PlanLimitError, UnderdogAPIError  # noqa: E402


class Fake:
    """Records requests and replays canned answers, so the tests never touch the network."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, headers))
        status, body = self.answers.pop(0)
        return status, {"Content-Type": "application/json"}, json.dumps(body).encode()


class ClientTest(unittest.TestCase):
    def test_sends_bearer_key_and_filters(self):
        fake = Fake([(200, {"data": [{"id": "udm_1"}], "meta": {"next_cursor": None}})])
        body = Client(api_key="ud_test", transport=fake).projections(league="NBA", view="compact", limit=5)
        self.assertEqual(body["data"][0]["id"], "udm_1")
        method, url, headers = fake.calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.startswith("https://underdogapi.com/api/v1/projections?"))
        self.assertIn("league=NBA", url)
        self.assertIn("view=compact", url)
        self.assertEqual(headers["Authorization"], "Bearer ud_test")

    def test_demo_needs_no_key(self):
        fake = Fake([(200, {"data": [], "meta": {}})])
        Client(api_key="ud_test", transport=fake).demo("projections", league="NBA")
        self.assertNotIn("Authorization", fake.calls[0][2])
        self.assertIn("/api/v1/demo/projections", fake.calls[0][1])

    def test_pages_follow_cursor(self):
        fake = Fake([
            (200, {"data": [{"id": 1}, {"id": 2}], "meta": {"next_cursor": "udm_x"}}),
            (200, {"data": [{"id": 3}], "meta": {"next_cursor": None}}),
        ])
        rows = list(Client(api_key="k", transport=fake).pages("/api/v1/changes", league="NBA"))
        self.assertEqual([r["id"] for r in rows], [1, 2, 3])
        self.assertIn("cursor=udm_x", fake.calls[1][1])

    def test_402_is_a_plan_limit_with_sample_and_link(self):
        err = {"error": {"code": "UPGRADE_REQUIRED", "message": "Free does not include graded results.", "upgrade_url": "https://underdogapi.com/upgrade?plan=developer", "sample": [{"result": "higher"}]}}
        fake = Fake([(402, err)])
        with self.assertRaises(PlanLimitError) as ctx:
            Client(api_key="k", transport=fake).results(league="NBA")
        self.assertEqual(ctx.exception.code, "UPGRADE_REQUIRED")
        self.assertEqual(ctx.exception.upgrade_url, "https://underdogapi.com/upgrade?plan=developer")
        self.assertEqual(ctx.exception.sample, [{"result": "higher"}])

    def test_retries_per_minute_429_but_not_monthly(self):
        fake = Fake([(429, {"error": {"code": "RATE_LIMITED"}}), (200, {"data": [], "meta": {}})])
        c = Client(api_key="k", transport=fake, retries=1)
        import underdog_api
        underdog_api.time.sleep = lambda s: None
        c.coverage()
        self.assertEqual(len(fake.calls), 2)
        fake2 = Fake([(429, {"error": {"code": "MONTHLY_QUOTA_EXCEEDED", "message": "out of credits"}})])
        with self.assertRaises(UnderdogAPIError) as ctx:
            Client(api_key="k", transport=fake2, retries=3).coverage()
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(len(fake2.calls), 1)

    def test_history_path_is_quoted(self):
        fake = Fake([(200, {"data": [], "meta": {}})])
        Client(api_key="k", transport=fake).history("udm_00000000-0000-4000-8000-000000000001")
        self.assertIn("/api/v1/projections/udm_00000000-0000-4000-8000-000000000001/history", fake.calls[0][1])


@unittest.skipUnless(os.environ.get("UNDERDOG_LIVE") == "1", "set UNDERDOG_LIVE=1 to call the real keyless demo")
class LiveDemoTest(unittest.TestCase):
    def test_keyless_demo(self):
        body = Client(api_key=None).demo("projections", league="NBA", limit=1)
        self.assertTrue(body["data"])
        self.assertIn("selections", body["data"][0])


if __name__ == "__main__":
    unittest.main()
