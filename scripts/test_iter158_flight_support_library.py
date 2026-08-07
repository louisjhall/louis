"""
Iter 158 — Flight Support library autowiring + enhanced frames endpoint.

Covers:
  A. ensure_flight_support_blocks_in_library() calls
     `create_exercise_request_if_missing` for every unique block name.
  B. Duplicates across protocols are only drafted once.
  C. resolve_flight_support_frames adds `primary_image` and
     `coaching_points` to the response payload.
  D. Coaching points on the exercise doc as a raw string are split into a
     list of bullets by the endpoint (never returned as a string).

Run:
    cd /app/backend && python /app/scripts/test_iter158_flight_support_library.py
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    import server  # noqa: F401  boot deps
    from feature_aviation_support import PROTOCOLS, ensure_flight_support_blocks_in_library
    from feature_flight_support_media import resolve_flight_support_frames
    import feature_v2_resolver as resolver

    # ----- A / B ------------------------------------------------------
    called_names: list[str] = []
    orig_fn = resolver.create_exercise_request_if_missing

    async def fake_create(item, *, user=None, **_kw):
        called_names.append(item.get("name") or item.get("exercise_name"))
        return "req-" + str(len(called_names))

    resolver.create_exercise_request_if_missing = fake_create  # type: ignore

    # Patch db.exercises_v2.find_one so the pre-existence peek returns None.
    import server as srv
    class NoRow:
        async def find_one(self, *_a, **_kw): return None

    class FakeDB:
        exercises_v2 = NoRow()

    orig_db = srv.db
    srv.db = FakeDB()  # type: ignore

    try:
        counters = await ensure_flight_support_blocks_in_library()
    finally:
        resolver.create_exercise_request_if_missing = orig_fn  # type: ignore
        srv.db = orig_db  # type: ignore

    # Every registered protocol should contribute at least one block.
    unique_block_names = set()
    for p in PROTOCOLS.values():
        for b in (p.blocks or []):
            n = (b.get("name") or "").strip()
            if n:
                unique_block_names.add(n)

    assert counters["scanned"] == len(unique_block_names), \
        f"scanned={counters['scanned']} != unique blocks {len(unique_block_names)}"
    assert len(called_names) == len(unique_block_names), \
        f"resolver called {len(called_names)} times, expected {len(unique_block_names)}"
    assert len(set(called_names)) == len(called_names), \
        "resolver was called with duplicate names"
    # Spot-check for the block the user called out.
    assert any("comfortable walk" in n.lower() for n in unique_block_names) or \
        any("walk" in n.lower() for n in unique_block_names), \
        "expected some walk-family block in the protocol library"
    print(f"A+B OK — {counters['scanned']} unique blocks drafted exactly once ({counters['drafted']} drafts, {counters['existing']} existing).")

    # ----- C / D ------------------------------------------------------
    # Build a fake mongo-like DB that returns a known exercise doc.
    class FakeCursor:
        def __init__(self, docs): self._docs = list(docs)
        def __aiter__(self):
            self._i = 0
            return self
        async def __anext__(self):
            if self._i >= len(self._docs):
                raise StopAsyncIteration
            v = self._docs[self._i]
            self._i += 1
            return v

    class FakeColl:
        def __init__(self, ex=None, imgs=None):
            self._ex = ex
            self._imgs = imgs or []
        async def find_one(self, *_a, **_kw): return self._ex
        def find(self, *_a, **_kw): return FakeCursor(self._imgs)
        async def update_one(self, *_a, **_kw):
            return type("R", (), {"modified_count": 1})()

    # Case C — exercise doc has primary_image_id + coaching_points list.
    ex_doc = {
        "id": "ex-1",
        "name": "Comfortable walk",
        "primary_image_id": "img-primary-1",
        "coaching_points": [
            "Relaxed shoulders",
            "Nasal breathing",
            "Land mid-foot",
        ],
    }
    class DB_C:
        def __init__(self):
            self.exercises = FakeColl(ex_doc)
            self.exercises_v2 = FakeColl(None)
            self.exercise_content = FakeColl(None)
            self.exercise_content_images = FakeColl(imgs=[])
            self.media_queue = FakeColl()
        def __getitem__(self, name):
            return getattr(self, name)

    out_c = await resolve_flight_support_frames(DB_C(), "Comfortable walk", prefer="pilot")
    assert out_c["primary_image"] == {
        "image_id": "img-primary-1",
        "url": "/api/exercise-content/images/img-primary-1/stream",
    }, out_c["primary_image"]
    assert out_c["coaching_points"] == ["Relaxed shoulders", "Nasal breathing", "Land mid-foot"]
    print("C OK — frames endpoint returns primary_image + coaching_points list.")

    # Case D — coaching_points as a raw string is split to bullets.
    ex_doc2 = {
        "id": "ex-2",
        "name": "Thoracic rotation",
        "primary_image_id": None,
        "coaching_points": "Half-kneel\n• Hand behind head\n· Rotate open smoothly",
    }
    class DB_D:
        def __init__(self):
            self.exercises = FakeColl(ex_doc2)
            self.exercises_v2 = FakeColl(None)
            self.exercise_content = FakeColl(None)
            self.exercise_content_images = FakeColl(imgs=[])
            self.media_queue = FakeColl()
        def __getitem__(self, name):
            return getattr(self, name)

    out_d = await resolve_flight_support_frames(DB_D(), "Thoracic rotation", prefer="pilot")
    assert isinstance(out_d["coaching_points"], list), "coaching_points must be a list"
    assert out_d["coaching_points"] == [
        "Half-kneel",
        "Hand behind head",
        "Rotate open smoothly",
    ], out_d["coaching_points"]
    print("D OK — string coaching_points normalised to a bullet list.")

    print("\nAll Iter 158 backend contracts verified.")


if __name__ == "__main__":
    asyncio.run(main())
