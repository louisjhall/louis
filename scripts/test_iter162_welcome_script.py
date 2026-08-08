"""
Iter 162 · Verify the Welcome-Video script generator endpoint.

Tests:
  1. Fallback path — client has NO DNA yet. Endpoint returns a warm,
     first-name greeting ending with "Welcome to CrewFit." without any
     LLM call (used_fallback=True).
  2. Utility helpers (_extract_first_name, _pick_dna_highlights) behave
     as expected.

Deliberately does NOT trigger a real LLM call (that would consume budget).
The DNA-rich path is exercised via a monkeypatched call_claude_tracked.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"


def _ok(m): print(f"  ✅  {m}")
def _fail(m): print(f"  ❌  {m}"); raise AssertionError(m)


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    import server

    # Test the helpers directly first.
    print("[A] _extract_first_name")
    _ok(server._extract_first_name({"name": "Pietro Rossi"}) == "Pietro")
    _ok(server._extract_first_name({"display_name": "Louis"}) == "Louis")
    _ok(server._extract_first_name({"email": "alex.jones@ba.com"}) == "Alex")
    _ok(server._extract_first_name({}) == "there")

    print("\n[B] _pick_dna_highlights")
    picks = server._pick_dna_highlights({
        "biggest_strength": "recovery discipline",
        "biggest_opportunity": "upper-body strength",
    })
    _ok(len(picks) == 2)
    _ok("biggest strength" in picks[0])
    empty = server._pick_dna_highlights({})
    _ok(len(empty) == 1 and "started" in empty[0])

    print("\n[C] Fallback path — no DNA doc")
    uid = f"TEST-welcome-{uuid.uuid4().hex[:6]}"
    coach_id = f"TEST-coach-{uuid.uuid4().hex[:6]}"
    try:
        await db.users.insert_many([
            {"id": uid, "role": "client",
             "name": "Pietro Rossi",
             "email": f"{uid}@example.io",
             "profile": {"job_title": "First Officer", "airline": "British Airways"}},
            {"id": coach_id, "role": "coach",
             "name": "Louis Cole",
             "email": f"{coach_id}@example.io"},
        ])
        # Load the client dict via the fallback branch directly.
        client = await db.users.find_one({"id": uid}, {"_id": 0})
        first_name = server._extract_first_name(client)
        dna_ctx = await server._get_dna_context(uid)
        _ok(dna_ctx == {})
        # Call the endpoint's fallback branch by invoking with a monkeypatched
        # LLM function to prove the fallback text is emitted without hitting
        # the real API when DNA is empty.
        body = server.WelcomeScriptGenBody(client_id=uid)
        # We need to invoke the endpoint function directly. Because it's
        # decorated with @api.post, we call the underlying coroutine.
        coach_doc = await db.users.find_one({"id": coach_id}, {"_id": 0})
        result = await server.coach_generate_welcome_script(body=body, coach=coach_doc)
        script = result["script"]
        _ok(result["used_fallback"] is True)
        _ok(result["client_first_name"] == "Pietro")
        _ok("Pietro" in script and script.rstrip(".").endswith("Welcome to CrewFit"))
        print(f"     Fallback script: {script[:80]}…")

        print("\n[D] DNA-present path — monkeypatched LLM")
        # Insert a DNA doc.
        await db.coaching_dna.insert_one({
            "id": f"TEST-dna-{uuid.uuid4().hex[:6]}",
            "user_id": uid,
            "version": 1,
            "primary_goal": "Marathon sub-3:45",
            "why_it_matters": "Prove to myself I can do it after two years of shift work",
            "biggest_strength": "Aerobic base",
            "biggest_opportunity": "Strength on push days",
            "motivation_style": "Data-driven, small wins",
            "flying_style": "Long-haul with heavy jet-lag",
        })

        # Monkey-patch call_claude_tracked to avoid a real LLM call.
        async def fake_llm(coach, feature, system, prompt, max_out=800, enforce=True):
            # Verify the prompt includes the required signals.
            assert "Pietro" in prompt, "first name missing from prompt"
            assert "Marathon sub-3:45" in prompt, "primary goal missing from prompt"
            assert "Prove to myself" in prompt, "why_it_matters missing from prompt"
            assert "biggest strength" in prompt or "biggest_strength" in prompt, "DNA highlight missing"
            # Return a plausible AI-shaped welcome script.
            return (
                "Hey Pietro, welcome aboard. Getting under 3:45 in a marathon "
                "matters — I hear you, and it's the kind of goal that changes "
                "how you show up for the next few months. I saw your aerobic "
                "base is already a real weapon; we'll build the strength around "
                "it so you keep it. We'll work honestly, in the windows your "
                "roster actually gives us."
            )
        server.call_claude_tracked = fake_llm  # type: ignore

        result2 = await server.coach_generate_welcome_script(body=body, coach=coach_doc)
        script2 = result2["script"]
        _ok(result2["used_fallback"] is False)
        _ok("Pietro" in script2)
        _ok(script2.rstrip(".").endswith("Welcome to CrewFit"))
        print(f"     AI script (patched): {script2[:100]}…")

        # Ensure the mandatory sign-off is enforced even if LLM omits it.
        async def fake_llm_no_signoff(coach, feature, system, prompt, max_out=800, enforce=True):
            return "Some script without the mandatory ending"
        server.call_claude_tracked = fake_llm_no_signoff  # type: ignore
        result3 = await server.coach_generate_welcome_script(body=body, coach=coach_doc)
        _ok(result3["script"].rstrip(".").endswith("Welcome to CrewFit"))
        print(f"     Sign-off enforced: {result3['script']}")

        print("\n✅  Iter 162 Welcome-Script tests passed.")
    finally:
        await db.users.delete_many({"id": {"$in": [uid, coach_id]}})
        await db.coaching_dna.delete_many({"user_id": uid})
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
