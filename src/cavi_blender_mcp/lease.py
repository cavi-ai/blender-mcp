"""Application-local edit ownership shared by independent MCP clients."""

import secrets
import threading
import time
from contextlib import contextmanager

# An owner whose lease went unused this long may be displaced with the break action.
BREAK_IDLE_SECONDS = 300


class Lease:
    def __init__(self):
        self.lock = threading.RLock()
        self.clear()

    def clear(self):
        self.token = None
        self.owner = None
        self.project = None
        self.expires = 0.0
        self.touched = 0.0

    def active(self):
        return self.token is not None and time.monotonic() < self.expires

    def status(self, project):
        now = time.monotonic()
        return {
            "active": self.active(),
            "owner": self.owner,
            "project_id": project,
            "claimed_project_id": self.project,
            "expires_in": max(0.0, self.expires - now),
            "idle_seconds": max(0.0, now - self.touched) if self.token else 0.0,
        }

    def matches(self, token):
        # Compare bytes: compare_digest raises TypeError on non-ASCII str.
        return (isinstance(token, str) and self.token is not None
                and secrets.compare_digest(token.encode("utf-8", "surrogatepass"),
                                           self.token.encode()))

    def require(self, token, project):
        if not self.matches(token):
            raise RuntimeError("A valid lease_id is required; inspect and claim the session")
        if time.monotonic() >= self.expires:
            raise RuntimeError("The edit lease expired; inspect and claim the session again")
        if project != self.project:
            raise RuntimeError("The project changed; release the lease and inspect before claiming")

    def control(self, params, project):
        with self.lock:
            project = project() if callable(project) else project
            action = params.get("action")
            if action == "inspect":
                return self.status(project)
            if action == "release":
                if not self.matches(params.get("lease_id")):
                    raise RuntimeError("A matching lease_id is required to release ownership")
                self.clear()
                return self.status(project)
            if action == "break":
                if params.get("expected_project") != project:
                    raise RuntimeError("The inspected project changed; inspect the session again")
                if not self.active():
                    raise RuntimeError("No active lease to break; claim the session instead")
                idle = time.monotonic() - self.touched
                if idle < BREAK_IDLE_SECONDS:
                    raise RuntimeError(
                        f"Lease of {self.owner} was used {idle:.0f} s ago; "
                        f"break requires {BREAK_IDLE_SECONDS} s idle"
                    )
                previous = self.owner
                self.clear()
                return {**self.status(project), "previous_owner": previous}
            if action not in {"claim", "renew"}:
                raise ValueError("Unknown session action")
            ttl = params.get("ttl_seconds", 600)
            if type(ttl) is not int or not 30 <= ttl <= 3600:
                raise ValueError("Lease duration must be an integer from 30 to 3600 seconds")
            if action == "renew":
                self.require(params.get("lease_id"), project)
            else:
                owner = params.get("owner")
                if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
                    raise ValueError("Owner must be a nonempty label of at most 128 characters")
                if params.get("expected_project") != project:
                    raise RuntimeError("The inspected project changed; inspect the session again")
                if self.active():
                    raise RuntimeError(f"Application is owned by {self.owner}; wait for release")
                self.token, self.owner, self.project = secrets.token_urlsafe(32), owner, project
            now = time.monotonic()
            self.expires, self.touched = now + ttl, now
            result = self.status(project)
            if action == "claim":
                result["lease_id"] = self.token
            return result

    @contextmanager
    def edit(self, token, identity):
        with self.lock:
            self.require(token, identity())
            self.touched = time.monotonic()
            try:
                yield
                # Owned saves and project transitions may change the project identity.
                self.project = identity()
            finally:
                self.touched = time.monotonic()
