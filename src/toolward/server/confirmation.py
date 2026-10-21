"""Confirmation tokens for confirm_mode="preview_token" (added in Phase 6).

In the baseline mode ("v1"), confirm=true executes a ban or a role change straight away, so
the server has to trust that the model really asked the user first. In "preview_token" mode the
server enforces part of that rule itself:

1. A preview (confirm=false) that passes every check returns a `confirmation_id`.
2. An executing call (confirm=true) must echo a confirmation_id from a preview of the same
   action: same tool, same member and, for assign_role, the same role.
3. A confirmation_id works once, and only within the next TOKEN_LIFETIME_CALLS tool calls on
   this server, so a stale preview can't be reused much later.

A confirm=true call without a valid ID is refused with CONFIRMATION_REQUIRED, and nothing
changes. The IDs are numbered in order (conf_001, conf_002, ...) instead of being random, so a
recorded run replays to exactly the same tool results.

What this can't do: the server never sees the user, so it can't tell whether the user approved
the preview. It only guarantees that a preview of that exact action was made shortly before.
"""

from dataclasses import dataclass, field

from toolward.server.models import ToolFailure

TOKEN_LIFETIME_CALLS = 5  # tool calls (of any tool) after the preview that the ID stays valid


@dataclass
class ConfirmationTokens:
    calls: int = 0  # tool calls made on this server so far
    issued: int = 0
    # confirmation_id -> (action key, number of the call that issued it)
    pending: dict[str, tuple[tuple[str, ...], int]] = field(default_factory=dict)

    def count_call(self) -> None:
        """Every tool call goes through here, so token lifetimes are measured in calls."""
        self.calls += 1

    def issue(self, action: tuple[str, ...]) -> str:
        self.issued += 1
        token = f"conf_{self.issued:03d}"
        self.pending[token] = (action, self.calls)
        return token

    def redeem(self, action: tuple[str, ...], token: str | None) -> None:
        """Use up a token for this action, or raise CONFIRMATION_REQUIRED."""
        how_to = (
            "Nothing was changed. Call again with confirm=false to get a preview and a "
            "confirmation_id, show the preview to the user, and only after the user approves it "
            "call with confirm=true and that confirmation_id."
        )
        token = (token or "").strip()
        if not token:
            raise ToolFailure(
                "CONFIRMATION_REQUIRED",
                "confirm=true needs the confirmation_id of a preview.",
                how_to,
            )
        if token not in self.pending:
            raise ToolFailure(
                "CONFIRMATION_REQUIRED", f"'{token}' is not a valid confirmation_id.", how_to
            )
        issued_action, issued_at = self.pending[token]
        if issued_action != action:
            raise ToolFailure(
                "CONFIRMATION_REQUIRED",
                f"'{token}' was issued for a different action.",
                how_to,
            )
        if self.calls - issued_at > TOKEN_LIFETIME_CALLS:
            del self.pending[token]
            raise ToolFailure("CONFIRMATION_REQUIRED", f"'{token}' has expired.", how_to)
        del self.pending[token]  # one use only
