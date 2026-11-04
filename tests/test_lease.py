import threading
import unittest
from unittest.mock import patch

from cavi_blender_mcp import lease


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(lease.time, "monotonic", return_value=100.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.session = lease.Lease()
        self.project = "project-A"

    def claim(self, owner="agent-A"):
        return self.session.control(
            {"action": "claim", "owner": owner, "expected_project": self.project,
             "ttl_seconds": 60}, self.project,
        )["lease_id"]

    def test_foreign_or_missing_token_cannot_edit_and_inspection_hides_token(self):
        token = self.claim()
        for value in (None, "foreign-token"):
            with self.assertRaisesRegex(RuntimeError, "lease"), self.session.edit(value, lambda: self.project):
                self.fail("An unowned edit ran")
        public = self.session.control({"action": "inspect"}, self.project)
        self.assertEqual(public["owner"], "agent-A")
        self.assertNotIn(token, str(public))

    def test_competing_claim_and_release_cannot_steal_ownership(self):
        token = self.claim()
        with self.assertRaisesRegex(RuntimeError, "agent-A"):
            self.claim("agent-B")
        with self.assertRaisesRegex(RuntimeError, "lease"):
            self.session.control({"action": "release", "lease_id": "wrong"}, self.project)
        self.session.control({"action": "release", "lease_id": token}, self.project)
        self.assertNotEqual(self.claim("agent-B"), token)

    def test_expiry_blocks_old_edits_and_allows_new_claim_without_app_actions(self):
        token = self.claim()
        self.now.return_value = 161.0
        with self.assertRaisesRegex(RuntimeError, "expired"), self.session.edit(token, lambda: self.project):
            self.fail("Expired edit ran")
        replacement = self.claim("agent-B")
        self.assertNotEqual(replacement, token)
        self.assertEqual(self.project, "project-A")

    def test_project_switch_refuses_edit_and_renewal(self):
        token = self.claim()
        self.project = "project-B"
        with self.assertRaisesRegex(RuntimeError, "project changed"), self.session.edit(token, lambda: self.project):
            self.fail("Edit targeted another project")
        with self.assertRaisesRegex(RuntimeError, "project changed"):
            self.session.control({"action": "renew", "lease_id": token}, self.project)

    def test_owned_success_updates_binding_but_failed_operation_does_not(self):
        token = self.claim()
        with self.session.edit(token, lambda: self.project):
            self.project = "saved-project"
        with self.session.edit(token, lambda: self.project):
            pass
        with self.assertRaises(ValueError), self.session.edit(token, lambda: self.project):
            self.project = "uncertain-project"
            raise ValueError("operation failed")
        with self.assertRaisesRegex(RuntimeError, "project changed"), self.session.edit(token, lambda: self.project):
            self.fail("Continued after partial project change")

    def test_stale_inspection_and_invalid_ttl_cannot_claim(self):
        for params in (
            {"owner": "agent-A", "expected_project": "old"},
            {"owner": "agent-A", "expected_project": self.project, "ttl_seconds": True},
            {"owner": "agent-A", "expected_project": self.project, "ttl_seconds": 0},
            {"owner": " ", "expected_project": self.project},
        ):
            with self.assertRaises((RuntimeError, ValueError)):
                self.session.control({"action": "claim", **params}, self.project)

    def test_operation_holds_ownership_until_its_effects_finish(self):
        token = self.claim()
        attempted = threading.Event()
        finished = threading.Event()
        result = []

        def contender():
            attempted.set()
            result.append(self.claim("agent-B"))
            finished.set()

        with self.session.edit(token, lambda: self.project):
            self.now.return_value = 161.0
            worker = threading.Thread(target=contender)
            worker.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(finished.is_set())
        worker.join(2)
        self.assertTrue(finished.is_set())
        self.assertNotEqual(result, [token])


    def test_non_ascii_token_is_refused_as_an_invalid_lease(self):
        token = self.claim()
        with self.assertRaisesRegex(RuntimeError, "valid lease_id"):
            self.session.control({"action": "renew", "lease_id": "é"}, self.project)
        with self.assertRaisesRegex(RuntimeError, "matching lease_id"):
            self.session.control({"action": "release", "lease_id": "é"}, self.project)
        with self.assertRaisesRegex(RuntimeError, "valid lease_id"), self.session.edit("é", lambda: self.project):
            self.fail("A non-ASCII token edited")
        with self.session.edit(token, lambda: self.project):
            pass

    def test_break_needs_an_owner_idle_for_the_break_window(self):
        token = self.session.control(
            {"action": "claim", "owner": "agent-A", "expected_project": self.project,
             "ttl_seconds": 3600}, self.project,
        )["lease_id"]
        breaking = {"action": "break", "expected_project": self.project}
        with self.assertRaisesRegex(RuntimeError, "break requires"):
            self.session.control(breaking, self.project)
        self.now.return_value = 150.0
        with self.session.edit(token, lambda: self.project):
            pass
        self.now.return_value = 150.0 + lease.BREAK_IDLE_SECONDS - 1
        with self.assertRaisesRegex(RuntimeError, "break requires"):
            self.session.control(breaking, self.project)
        with self.assertRaisesRegex(RuntimeError, "inspected project changed"):
            self.session.control({**breaking, "expected_project": "old"}, self.project)
        self.now.return_value = 150.0 + lease.BREAK_IDLE_SECONDS
        self.assertEqual(self.session.status(self.project)["idle_seconds"], lease.BREAK_IDLE_SECONDS)
        broken = self.session.control(breaking, self.project)
        self.assertEqual((broken["active"], broken["owner"], broken["previous_owner"]),
                         (False, None, "agent-A"))
        with self.assertRaisesRegex(RuntimeError, "valid lease_id"), self.session.edit(token, lambda: self.project):
            self.fail("A broken lease edited")
        with self.assertRaisesRegex(RuntimeError, "No active lease"):
            self.session.control(breaking, self.project)
        self.assertNotEqual(self.claim("agent-B"), token)

if __name__ == "__main__":
    unittest.main()
