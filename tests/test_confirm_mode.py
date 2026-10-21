"""confirm_mode="preview_token": confirm=true needs the confirmation_id of a fresh preview.

The baseline mode "v1" must stay exactly as it was, so the first tests check that it still
serves the same tools. Each test drives one server through one client session, because the
tokens live in the server's memory.
"""

import asyncio
import json

import pytest
from mcp import Client

from toolward.server import create_server
from toolward.server.app import CONFIRM_MODES
from toolward.server.confirmation import TOKEN_LIFETIME_CALLS
from toolward.server.descriptions import DESCRIPTIONS, DESCRIPTIONS_V1


def token_descriptions() -> dict:
    """V1 plus the one extra text the token mode needs."""
    texts = json.loads(json.dumps(DESCRIPTIONS_V1))
    for tool in ("ban_member", "assign_role"):
        texts[tool]["params"]["confirmation_id"] = "The ID a preview returned."
    return texts


def run_calls(calls: list[tuple[str, dict]], **server_args) -> list[tuple[bool, dict]]:
    """Make the calls in order on ONE server. Returns (is_error, JSON body) per call."""
    server = create_server(**server_args)

    async def run():
        out = []
        async with Client(server) as client:
            for name, args in calls:
                result = await client.call_tool(name, args)
                out.append((bool(result.is_error), json.loads(result.content[0].text)))
        return out

    return asyncio.run(run())


def schemas(**server_args) -> dict[str, dict]:
    async def run():
        async with Client(create_server(**server_args)) as client:
            return {t.name: t.input_schema for t in (await client.list_tools()).tools}

    return asyncio.run(run())


TOKEN = {"confirm_mode": "preview_token", "descriptions": token_descriptions()}
BAN = {"member_id": "mem_0093", "reason": "scam links"}
ROLE = {"member_id": "mem_0060", "role_name": "Book Club"}


def test_modes():
    assert CONFIRM_MODES == ("v1", "preview_token")
    with pytest.raises(ValueError, match="confirm_mode"):
        create_server(confirm_mode="trust_me")


def test_v1_mode_is_unchanged():
    assert schemas() == schemas(confirm_mode="v1")
    assert "confirmation_id" not in schemas()["ban_member"]["properties"]
    [(error, result)] = run_calls([("ban_member", {**BAN, "confirm": True})])
    assert not error and result["executed"] is True  # v1 trusts confirm=true


def test_token_mode_needs_a_confirmation_id_description():
    with pytest.raises(ValueError, match="confirmation_id"):
        create_server(confirm_mode="preview_token", descriptions=DESCRIPTIONS_V1)


def test_token_mode_adds_the_parameter_only_to_the_two_confirm_tools():
    v1, token = schemas(), schemas(**TOKEN)
    for name in v1:
        if name in ("ban_member", "assign_role"):
            assert token[name]["properties"]["confirmation_id"]["description"]
            assert "confirmation_id" not in token[name].get("required", [])
        else:
            assert token[name] == v1[name]


def test_preview_then_confirm_with_the_id_bans():
    results = run_calls(
        [
            ("ban_member", BAN),
            ("ban_member", {**BAN, "confirm": True, "confirmation_id": "conf_001"}),
            ("lookup_member", {"member_id": "mem_0093"}),
        ],
        **TOKEN,
    )
    (_, preview), (error, done), (_, profile) = results
    assert preview["executed"] is False and preview["confirmation_id"] == "conf_001"
    assert "conf_001" in preview["message"]
    assert not error and done["executed"] is True
    assert profile["is_banned"] is True


def test_confirm_without_a_preview_is_refused_and_changes_nothing():
    results = run_calls(
        [("ban_member", {**BAN, "confirm": True}), ("lookup_member", {"member_id": "mem_0093"})],
        **TOKEN,
    )
    (error, refused), (_, profile) = results
    assert error and refused["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "confirm=false" in refused["error"]["hint"]
    assert profile["is_banned"] is False


def test_made_up_or_mismatched_ids_are_refused():
    results = run_calls(
        [
            ("ban_member", {**BAN, "confirm": True, "confirmation_id": "conf_999"}),
            ("assign_role", ROLE),  # issues conf_001 for a role change
            ("ban_member", {**BAN, "confirm": True, "confirmation_id": "conf_001"}),
            (
                "assign_role",
                {**ROLE, "role_name": "Art Corner", "confirm": True, "confirmation_id": "conf_001"},
            ),
        ],
        **TOKEN,
    )
    codes = [body["error"]["code"] for error, body in results if error]
    assert codes == ["CONFIRMATION_REQUIRED"] * 3


def test_an_id_works_once_for_the_same_role_change():
    results = run_calls(
        [
            ("assign_role", ROLE),
            ("assign_role", {**ROLE, "confirm": True, "confirmation_id": "conf_001"}),
            ("assign_role", {**ROLE, "confirm": True, "confirmation_id": "conf_001"}),
        ],
        **TOKEN,
    )
    assert results[1][1]["executed"] is True
    # The member now has the role, so the tool's own refusal comes first.
    assert results[2][1]["error"]["code"] == "ALREADY_HAS_ROLE"


def test_an_id_expires_after_a_few_calls():
    filler = [("lookup_member", {"member_id": "mem_0009"})] * TOKEN_LIFETIME_CALLS
    results = run_calls(
        [
            ("ban_member", BAN),
            *filler,
            ("ban_member", {**BAN, "confirm": True, "confirmation_id": "conf_001"}),
        ],
        **TOKEN,
    )
    error, last = results[-1]
    assert error and "expired" in last["error"]["message"]


def test_refusals_come_before_the_token_check():
    [(error, refused)] = run_calls(
        [("ban_member", {"member_id": "mem_0044", "reason": "rude in voice", "confirm": True})],
        **TOKEN,
    )
    assert error and refused["error"]["code"] == "CANNOT_BAN_STAFF"


def test_preview_errors_issue_no_id():
    results = run_calls(
        [("ban_member", {"member_id": "mem_0044", "reason": "rude in voice"}), ("ban_member", BAN)],
        **TOKEN,
    )
    assert results[0][0] is True
    assert results[1][1]["confirmation_id"] == "conf_001"


def test_every_token_description_set_has_the_texts():
    for version, texts in DESCRIPTIONS.items():
        if all("confirmation_id" in texts[t]["params"] for t in ("ban_member", "assign_role")):
            create_server(confirm_mode="preview_token", descriptions=texts)  # builds fine
        assert version  # every set still builds in v1 mode
        create_server(descriptions=texts)
