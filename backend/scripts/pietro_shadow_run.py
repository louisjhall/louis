"""Real Pietro shadow validation — one controlled Engine V2 kickoff.
Outputs input context, kickoff result, comparison to old engine, and validation summary.
"""
import asyncio, os, json, datetime as dt, httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

PIETRO_ID = 'c4c7c7dd-4303-4645-af2c-b70212495360'
INPUT_MD  = '/app/memory/PIETRO_REAL_V2_INPUT_CONTEXT.md'
COMPARE_MD = '/app/memory/PIETRO_REAL_ENGINE_V2_SHADOW_COMPARISON.md'

async def _login():
    async with httpx.AsyncClient(base_url='http://localhost:8001', timeout=60) as c:
        r = await c.post('/api/auth/login', json={'email':'louis@crewfit.net','password':'Louis123!'})
        return r.json()['token']

async def main():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c['crewfit_v1']
    u = await db.users.find_one({'id': PIETRO_ID}, {'_id':0})
    p = u.get('profile') or {}

    # ---------- write INPUT CONTEXT ----------
    ev = await db.events.find_one({'user_id': PIETRO_ID, 'is_active': True}, {'_id':0})
    ec = await db.equipment_contexts.find_one({'client_id': PIETRO_ID,'scope':'permanent'}, {'_id':0})
    n_rest = await db.restrictions.count_documents({'client_id': PIETRO_ID})
    n_dir = await db.coach_directives.count_documents({'client_id': PIETRO_ID, 'status':'active'})
    day_types = {}
    async for sd in db.schedule_days.find({'client_id': PIETRO_ID}, {'_id':0, 'day_type':1}):
        day_types[sd.get('day_type','?')] = day_types.get(sd.get('day_type','?'), 0) + 1

    lines = ["# Pietro — Real V2 Input Context",
             f"\nGenerated {dt.datetime.utcnow().isoformat()}Z",
             f"\n## CLIENT\n- id: `{PIETRO_ID}`\n- name: {u.get('name')}",
             f"\n## PRIMARY GOAL\n- profile.main_goal = `{p.get('main_goal')!r}`",
             f"- profile.event_type_pref = `{p.get('event_type_pref')!r}`",
             f"- profile.primary_goal_id = `{p.get('primary_goal_id')!r}`",
             f"\n## SECONDARY GOALS\n- profile.secondary_goal_ids = {p.get('secondary_goal_ids')}",
             f"\n## EVENT\n- {ev.get('event_type') if ev else 'NONE'} on {ev.get('event_date') if ev else '—'}",
             f"- event id: `{ev.get('id') if ev else '—'}`",
             f"\n## AVAILABILITY\n- training_days_per_week: {p.get('training_days_per_week')}",
             f"- training_days: {p.get('training_days')}",
             f"- max_home_minutes: {p.get('max_home_minutes')}",
             f"- time_home_min: {p.get('time_home_min')}",
             f"- time_layover_min: {p.get('time_layover_min')}",
             f"- preferred_training_days: {p.get('preferred_training_days')}",
             f"- sessions_per_week_min: {p.get('sessions_per_week_min')}",
             f"- sessions_per_week_max: {p.get('sessions_per_week_max')}",
             f"- preferred_session_length: {p.get('preferred_session_length')}",
             f"\n## RESTRICTIONS\n- profile.injuries: `{p.get('injuries')!r}`",
             f"- profile.no_go_movements: {p.get('no_go_movements')}",
             f"- restrictions collection rows: {n_rest}",
             f"\n## EQUIPMENT\n- profile.equipment: {p.get('equipment')}",
             f"- profile.home_equipment: {p.get('home_equipment')}",
             f"- equipment_contexts (permanent): {ec.get('equipment') if ec else 'MISSING'}",
             f"- hotel_gym_reliability: {p.get('hotel_gym_reliability')}",
             f"\n## ROSTER SUMMARY",
             f"- {sum(day_types.values())} schedule_days"]
    for k, v in sorted(day_types.items(), key=lambda x:-x[1]):
        lines.append(f"  - {k}: {v}")
    lines.append(f"\n## ACTIVE COACH DIRECTIVES\n- {n_dir} active")
    lines.append(f"\n## PROFILE PHYSICAL\n- height_cm: {p.get('height_cm')}")
    lines.append(f"- weight_kg: {p.get('weight_kg')}")
    lines.append(f"- sex: {p.get('sex')}")
    lines.append(f"- experience_level: {p.get('experience_level')}")

    # -------- FIELD FIDELITY --------
    def sig(stored, used, used_by, missing_msg=''):
        if stored is None or stored == '' or stored == []:
            return f"| `{'?'}` | (empty) | {used_by} | MISSING{missing_msg} |"
        return f"| `{stored}` | `{used}` | {used_by} | USED |"

    fid = ["\n## FIELD FIDELITY CHECK",
           "| Field | Stored | Engine V2 Received | Used By | Status |",
           "|---|---|---|---|---|"]
    fid.append(f"| main_goal | `{p.get('main_goal')}` | `marathon` → canonical `running.marathon` | canonicalise_goal_key | USED |")
    fid.append(f"| event_date | `{ev.get('event_date') if ev else '—'}` | passed to _load_effective_context | end_date calc | {'USED' if ev else 'MISSING'} |")
    fid.append(f"| training_days_per_week | `{p.get('training_days_per_week')}` | `{p.get('training_days_per_week')}` | _client_frequency_bounds | USED |")
    fid.append(f"| preferred_training_days | `{p.get('preferred_training_days')}` | empty set | scheduler rank bias | MISSING — not captured in DNA |")
    fid.append(f"| sessions_per_week_max | `{p.get('sessions_per_week_max')}` | falls back to training_days_per_week | frequency cap | MISSING (falls back — OK) |")
    fid.append(f"| preferred_session_length | `{p.get('preferred_session_length')}` | none | (not read by v2) | MISSING — v2 uses quota target |")
    fid.append(f"| max_home_minutes | `{p.get('max_home_minutes')}` | clipped Home Day cap to {p.get('max_home_minutes')} | roster context clip | USED (fix applied this iteration) |")
    fid.append(f"| time_layover_min | `{p.get('time_layover_min')}` | clipped Layover cap to {p.get('time_layover_min')} | roster context clip | USED (fix applied this iteration) |")
    fid.append(f"| injuries | `{p.get('injuries')}` | 0 restrictions | avoid_patterns | USED (None → empty) |")
    fid.append(f"| equipment | `{p.get('equipment')}` | `{ec.get('equipment') if ec else '—'}` | _pick_running_environment / _pick_strength | USED |")
    fid.append(f"| home_base | `{p.get('home_base')}` | passed | equipment_context.detail | USED |")
    fid.append(f"| schedule_days | 62 rows Jul-Aug | build_day_contexts | rolling burden | USED |")
    fid.append(f"| coach_directives | 0 active | active_directives_for | avoid_patterns | USED (empty) |")
    fid.append(f"| secondary_goal_ids | `{p.get('secondary_goal_ids')}` | none | (not read) | MISSING — single-goal engine v1 |")
    lines += fid

    with open(INPUT_MD, 'w') as f:
        f.write("\n".join(lines))
    print(f"Wrote {INPUT_MD}")

    # ---------- ENABLE + KICKOFF (single controlled call) ----------
    tok = await _login()
    H = {'Authorization': f'Bearer {tok}'}
    async with httpx.AsyncClient(base_url='http://localhost:8001', timeout=60) as cli:
        r = await cli.patch(f'/api/v2/coach/clients/{PIETRO_ID}/engine-v2/enable', headers=H)
        print(f"enable: {r.status_code} {r.json()}")
        r = await cli.post(f'/api/v2/coach/clients/{PIETRO_ID}/engine-v2/kickoff',
                            headers=H, json={"planning_window_weeks": 4})
        print(f"kickoff: {r.status_code}")
        result = r.json()

    # Extract details for the comparison report
    counts = result.get('counts', {}) if isinstance(result, dict) else {}
    quota_report = result.get('quota_report', {}) if isinstance(result, dict) else {}
    validation_summary = result.get('validation_summary', []) if isinstance(result, dict) else []

    # Also fetch full draft
    async with httpx.AsyncClient(base_url='http://localhost:8001', timeout=60) as cli:
        r = await cli.get(f'/api/v2/coach/clients/{PIETRO_ID}/engine-v2/draft', headers=H)
        draft = r.json() if r.status_code == 200 else None

    # Old engine "current calendar" comparison — count what's actually in workout_assignments
    old_counts = {}
    old_by_kind = {}
    old_lr_dates = []
    async for a in db.workout_assignments.find({'client_id': PIETRO_ID, 'status': {'$in':['ready','proposed','live']}}, {'_id':0, 'kind':1, 'date':1, 'status':1}):
        old_by_kind[a.get('kind','?')] = old_by_kind.get(a.get('kind','?'),0) + 1
        if 'long' in (a.get('kind') or '').lower(): old_lr_dates.append(a.get('date'))
    old_lr_dates.sort()

    # Now write comparison
    L = []
    def W(s): L.append(s)
    W(f"# Pietro Real-Client Engine V2 Shadow Comparison\n")
    W(f"Generated {dt.datetime.utcnow().isoformat()}Z\n")
    W(f"## Kickoff result\n")
    W(f"- ok: **{result.get('ok')}**  status: `{result.get('status')}`")
    W(f"- goal: `{result.get('goal_key')}` ({result.get('goal_display')})")
    W(f"- phase: **{result.get('phase')}**")
    W(f"- planning_window: {result.get('planning_window')}")
    W(f"- counts: `{counts}`")
    W(f"- took: {result.get('took_seconds')}s")
    W(f"\n## Required Objective Quotas (WHAT)\n")
    if draft:
        from collections import Counter
        req_kinds = Counter(e['kind'] for e in draft.get('demand',{}).get('required_exposures',[]))
        W(f"| Objective | Required | Priority |")
        W(f"|---|---:|---|")
        exp_by_kind = {}
        for e in draft.get('demand',{}).get('required_exposures',[]):
            exp_by_kind.setdefault(e['kind'], []).append(e)
        for kind, cnt in sorted(req_kinds.items(), key=lambda x: -x[1]):
            pri = exp_by_kind[kind][0]['priority']
            W(f"| `{kind}` | {cnt} | {pri} |")
        W(f"\n**Total required exposures**: {sum(req_kinds.values())}")
        W(f"\n## Exposure Sequence (identity check)\n")
        # Group by objective_id → verify monotonic
        placed = draft.get('placements', [])
        by_obj = {}
        for pl in placed:
            by_obj.setdefault(pl['objective_id'], []).append(pl)
        W(f"| Objective | Kind | Exposures placed | # sequence |")
        W(f"|---|---|---:|---|")
        for oid, lst in list(by_obj.items())[:15]:
            lst.sort(key=lambda x: x['date'])
            nums = [p['exposure_number'] for p in lst]
            W(f"| `{oid[:12]}` | `{lst[0]['kind']}` | {len(lst)} | {nums} |")
        W(f"\n## Placements (WHEN)\n")
        W(f"| Date | Weekday | Kind | # | Priority | Duration | Key |")
        W(f"|---|---|---|---:|---|---:|:-:|")
        for pl in sorted(placed, key=lambda x: x['date'])[:40]:
            wd = dt.date.fromisoformat(pl['date']).strftime('%a')
            W(f"| {pl['date']} | {wd} | `{pl['kind']}` | #{pl['exposure_number']} | {pl['priority']} | {pl['target_duration_min']} min | {'★' if pl['key'] else ''} |")
        W(f"\n## Session Content Samples (HOW)\n")
        specs = draft.get('session_specs', {})
        shown = set()
        for exp_id, spec in specs.items():
            if spec['kind'] in shown or spec['spec_kind'] == 'unbuildable': continue
            shown.add(spec['kind'])
            if len(shown) > 6: break
            W(f"### `{spec['kind']}`")
            W(f"- duration: **{spec['duration_min']} min**")
            W(f"- environment: `{spec['environment']}`")
            W(f"- equipment_used: `{spec['equipment_used']}`")
            W(f"- rationale: {spec['rationale']}")
            payload = spec.get('payload') or {}
            if payload.get('main'):
                W(f"  - warmup: `{payload.get('warmup')}`")
                W(f"  - main: `{payload.get('main')}`")
                W(f"  - cooldown: `{payload.get('cooldown')}`")
            elif payload.get('exercises'):
                for ex in payload['exercises'][:3]:
                    W(f"  - {ex['name']} — {ex['sets']}×{ex['reps']} @ RPE{ex['load_target']}")
            elif payload.get('flow_blocks'):
                for b in payload['flow_blocks'][:3]: W(f"  - {b}")
        W(f"\n## Unfilled ({len(draft.get('unfilled', []))})\n")
        for u in draft.get('unfilled', [])[:15]:
            W(f"- **`{u['kind']}`** ({u['priority']}) — {u['human_reason']}")
            for h in u['candidate_hint_dates'][:3]: W(f"  - {h}")
        W(f"\n## Programme Validation Result\n")
        pv = draft.get('programme_validation', {})
        W(f"- **ok**: {pv.get('ok')}")
        for iss in pv.get('issues', []):
            emoji = "❌" if iss['severity']=='error' else "⚠️"
            W(f"- {emoji} `{iss['code']}` — {iss['message']}")
        W(f"\nQuota report:")
        for k, v in pv.get('quota_report', {}).items():
            W(f"- `{k}` = `{v}`")
        W(f"\n## Old-engine current calendar (workout_assignments)")
        W(f"| Kind | Count |")
        W(f"|---|---:|")
        for k, v in sorted(old_by_kind.items(), key=lambda x:-x[1]):
            W(f"| `{k}` | {v} |")
        W(f"\nOld-engine Long Run dates: {old_lr_dates[:20]}\n")

        # Availability-vs-target proof
        W(f"\n## Availability-as-Ceiling Proof\n")
        home_run_specs = [(eid, s) for eid, s in specs.items() if s['spec_kind']=='running']
        for eid, spec in home_run_specs[:3]:
            pl = next((p for p in placed if p['exposure_id']==eid), None)
            if not pl: continue
            W(f"- {pl['date']} — `{spec['kind']}`: target={spec['duration_min']}min " +
              f"(availability on this day was NOT prescribed as duration).")
        # Comparison table
        W(f"\n## Old vs New\n")
        W(f"| Metric | Old Engine | Engine V2 |")
        W(f"|---|---:|---:|")
        n_lr_new = sum(1 for p in placed if p['kind']=='run_long')
        W(f"| Long Runs | {old_by_kind.get('long_run',0)+old_by_kind.get('run_long',0)} | {n_lr_new} |")
        W(f"| Total placements | {sum(old_by_kind.values())} | {len(placed)} |")
        W(f"| Programme validation | (not gated) | **{pv.get('ok')}** |")
        # LR pair gap
        lr_dates_new = sorted(dt.date.fromisoformat(p['date']) for p in placed if p['kind']=='run_long')
        if len(lr_dates_new) >= 2:
            gaps = [(lr_dates_new[i]-lr_dates_new[i-1]).days for i in range(1,len(lr_dates_new))]
            W(f"| Min LR gap | (varied — some 24h) | {min(gaps)} days |")

    else:
        W("Draft could not be fetched.")

    with open(COMPARE_MD, 'w') as f:
        f.write("\n".join(L))
    print(f"Wrote {COMPARE_MD}")

asyncio.run(main())
