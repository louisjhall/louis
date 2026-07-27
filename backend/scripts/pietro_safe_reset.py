"""Pietro roster + draft safe-reset script.

Scoped to a SINGLE client_id. Deletes only:
  - schedule_days (roster payload)
  - roster_jobs, rosters (roster source records)
  - exceptions with kind='roster_change' (roster-derived attention items)

Marks as superseded_by_reset (keeps audit):
  - plan_drafts_v2 docs whose status is NOT 'published'

Preserves untouched:
  - users, workouts, workout_assignments, workout_implementations
  - objective_exposures, training_objectives, programme_phases_v2
  - plan_live_v2 (all versions)
  - decision_records, coach_directives
  - published plan_drafts_v2 (historical audit for existing Live docs)
"""
import asyncio, os, json, datetime as dt
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')

PID = 'c4c7c7dd-4303-4645-af2c-b70212495360'

async def snapshot(db, tag: str) -> dict:
    """Count-based snapshot of Pietro's data."""
    async def cnt(coll, filt):
        return await db[coll].count_documents(filt)

    published_drafts = await db.plan_drafts_v2.count_documents(
        {'client_id': PID, 'status': 'published'})
    superseded_drafts = await db.plan_drafts_v2.count_documents(
        {'client_id': PID, 'status': 'superseded_by_reset'})
    live_docs = await db.plan_live_v2.find(
        {'client_id': PID}, {'_id': 0, 'id': 1, 'active': 1}
    ).to_list(20)

    snap = {
        'tag': tag,
        'timestamp': dt.datetime.utcnow().isoformat() + 'Z',
        'roster': {
            'schedule_days': await cnt('schedule_days', {'client_id': PID}),
            'roster_jobs':   await cnt('roster_jobs',   {'user_id': PID}),
            'rosters':       await cnt('rosters',       {'user_id': PID}),
        },
        'drafts_v2': {
            'total': await cnt('plan_drafts_v2', {'client_id': PID}),
            'published': published_drafts,
            'needs_review': await cnt('plan_drafts_v2',
                {'client_id': PID, 'status': 'needs_review'}),
            'ready_for_review': await cnt('plan_drafts_v2',
                {'client_id': PID, 'status': 'ready_for_review'}),
            'superseded_by_reset': superseded_drafts,
            'other': await cnt('plan_drafts_v2',
                {'client_id': PID, 'status': {'$nin':
                    ['published', 'needs_review', 'ready_for_review',
                     'superseded_by_reset']}}),
        },
        'lives_v2': {
            'total': len(live_docs),
            'active': sum(1 for l in live_docs if l.get('active')),
            'ids': [{'id': l['id'], 'active': l.get('active')} for l in live_docs],
        },
        'exceptions': {
            'total':          await cnt('exceptions', {'client_id': PID}),
            'roster_change':  await cnt('exceptions', {'client_id': PID, 'kind': 'roster_change'}),
        },
        'history_preserved': {
            'workouts':                 await cnt('workouts',                {'user_id':   PID}),
            'workout_assignments':      await cnt('workout_assignments',     {'client_id': PID}),
            'workout_implementations':  await cnt('workout_implementations', {'client_id': PID}),
            'objective_exposures':      await cnt('objective_exposures',     {'client_id': PID}),
            'training_objectives':      await cnt('training_objectives',     {'client_id': PID}),
            'programme_phases_v2':      await cnt('programme_phases_v2',     {'client_id': PID}),
            'decision_records':         await cnt('decision_records',        {'client_id': PID}),
        },
    }
    return snap


async def go():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c['crewfit_v1']

    # ---- 1. Verify Pietro identity BEFORE any mutation
    u = await db.users.find_one({'id': PID},
        {'_id': 0, 'email': 1, 'name': 1, 'coach_id': 1, 'profile': 1})
    if not u:
        print('ABORT: Pietro not found by id')
        return
    assert 'sangermano' in (u.get('email') or '').lower(), \
        f'ABORT: wrong user resolved: {u.get("email")}'
    prof = u.get('profile') or {}
    print(f'Verified: {u["email"]} name={u.get("name")} '
          f'engine_v2={prof.get("v2_flags",{}).get("engine_v2")} '
          f'goal={prof.get("main_goal")}')

    # ---- 2. Pre-reset snapshot
    before = await snapshot(db, 'PRE_RESET')
    print('\n== PRE-RESET SNAPSHOT ==')
    print(json.dumps(before, indent=2))

    # ---- 3. Delete roster data (hard) --------------------------------
    r1 = await db.schedule_days.delete_many({'client_id': PID})
    r2 = await db.roster_jobs.delete_many({'user_id': PID})
    r3 = await db.rosters.delete_many({'user_id': PID})
    print(f'\nRoster deleted: schedule_days={r1.deleted_count} '
          f'roster_jobs={r2.deleted_count} rosters={r3.deleted_count}')

    # ---- 4. Delete roster-derived exceptions -------------------------
    r4 = await db.exceptions.delete_many({'client_id': PID, 'kind': 'roster_change'})
    print(f'Exceptions (kind=roster_change) deleted: {r4.deleted_count}')

    # ---- 5. Soft-mark non-published drafts as superseded --------------
    reset_at = dt.datetime.utcnow().isoformat() + 'Z'
    upd = await db.plan_drafts_v2.update_many(
        {'client_id': PID, 'status': {'$nin': ['published', 'superseded_by_reset']}},
        {'$set': {
            'status': 'superseded_by_reset',
            'superseded_at': reset_at,
            'superseded_reason': 'Roster/draft safe-reset for clean V2 regeneration test',
        }},
    )
    print(f'Non-published drafts marked superseded_by_reset: {upd.modified_count}')

    # ---- 6. Post-reset snapshot -------------------------------------
    after = await snapshot(db, 'POST_RESET')
    print('\n== POST-RESET SNAPSHOT ==')
    print(json.dumps(after, indent=2))

    # ---- 7. Write both to a markdown file -----------------------------
    md = ['# Pietro Pre/Post Roster+Draft Reset State\n']
    md.append(f'**Client ID**: `{PID}`  ')
    md.append(f'**Email**: `{u["email"]}`  ')
    md.append(f'**Reset at**: `{reset_at}`\n')
    md.append('## Before\n')
    md.append('```json\n' + json.dumps(before, indent=2) + '\n```\n')
    md.append('## After\n')
    md.append('```json\n' + json.dumps(after, indent=2) + '\n```\n')
    with open('/app/memory/PIETRO_PRE_ROSTER_RESET_STATE.md', 'w') as f:
        f.write('\n'.join(md))
    print('\nWrote /app/memory/PIETRO_PRE_ROSTER_RESET_STATE.md')


if __name__ == '__main__':
    asyncio.run(go())
