import json
d = json.load(open('/app/memory/pietro_trace_raw.json'))
prof = d.get('profile') or {}
goal = (d.get('goals_v2') or [{}])[0]
prog = (d.get('programmes_v2') or [{}])[0]
event = (d.get('events') or [{}])[0]
counts = d.get('_counts', {})

# DNA vs V2 usage
dna_fields = [
    ('main_goal', prof.get('main_goal'), 'USED by kickoff — appears as source string in decision_record'),
    ('primary_goal_id', prof.get('primary_goal_id'), 'USED (fallback in kickoff)'),
    ('event_type_pref', prof.get('event_type_pref'), 'USED (fallback in kickoff)'),
    ('training_days_per_week', prof.get('training_days_per_week'), 'LOADED BUT IGNORED — printed in rationale only; P5 does NOT gate frequency on this'),
    ('max_home_minutes', prof.get('max_home_minutes'), 'LOADED BUT IGNORED by P6 — impls default to slot-template duration'),
    ('equipment', prof.get('equipment'), 'LOADED, printed in rationale; equipment_contexts collection is EMPTY so P6 cannot actually match'),
    ('injuries', prof.get('injuries'), 'LOADED, printed only; restrictions collection is EMPTY — no injury->exercise gating'),
    ('home_base', prof.get('home_base'), 'LOADED, printed only'),
    ('airline', prof.get('airline'), 'LOADED, printed only'),
    ('age', prof.get('age'), 'NEVER LOADED by any V2 engine'),
    ('sex', prof.get('sex'), 'NEVER LOADED'),
    ('height_cm', prof.get('height_cm'), 'NEVER LOADED'),
    ('weight_kg', prof.get('weight_kg'), 'NEVER LOADED'),
    ('flying_type', prof.get('flying_type'), 'NEVER LOADED'),
    ('events row', f"{event.get('event_type')} on {event.get('event_date')}" if event else None, 'USED — kickoff anchors programme end to event_date'),
    ('preferred_training_days', prof.get('preferred_training_days'), 'MISSING FIELD in DNA schema'),
    ('sessions_per_week_min', prof.get('sessions_per_week_min'), 'MISSING FIELD in DNA schema'),
    ('sessions_per_week_max', prof.get('sessions_per_week_max'), 'MISSING FIELD in DNA schema'),
    ('assessments answers', 'exists (1 doc)', 'NEVER LOADED into V2 engines'),
    ('restrictions collection', counts.get('restrictions', 0), 'NEVER POPULATED — restriction gating is dead code'),
    ('equipment_contexts collection', counts.get('equipment_contexts', 0), 'NEVER POPULATED — P6 has no per-location context'),
    ('progression_signals collection', counts.get('progression_signals', 0), 'EMPTY — no readiness feed to P5'),
    ('coach_directives collection', counts.get('coach_directives', 0), '0 rows'),
]

# schedule days summary
sd_summary = []
for sd in (d.get('schedule_days') or []):
    derived = sd.get('derived') or {}
    sd_summary.append({
        'date': sd.get('date'),
        'day_type': sd.get('day_type'),
        'home_or_away': sd.get('home_or_away'),
        'duties_count': len(sd.get('duties') or []),
        'burden_score': derived.get('duty_burden_score'),
        'burden_band': derived.get('duty_burden_band'),
        'opportunity': derived.get('training_opportunity'),
        'ceiling': derived.get('recommended_intensity_ceiling'),
        'avail_min': derived.get('available_time_min'),
        'classification': derived.get('classification'),
    })

# assignments vs impls
asg = d.get('workout_assignments') or []
impls = {i['id']: i for i in (d.get('workout_implementations') or [])}
asg_summary = []
for a in asg:
    impl_id = a.get('draft_implementation_id') or a.get('live_implementation_id')
    im = impls.get(impl_id) if impl_id else None
    ex = (im or {}).get('exercises') or []
    asg_summary.append({
        'assignment_id': a.get('id'),
        'date': a.get('date'),
        'status': a.get('status'),
        'kind': a.get('kind'),
        'objective_id': a.get('objective_id'),
        'impl_id': impl_id,
        'impl_exists': bool(im),
        'impl_title': (im or {}).get('title'),
        'impl_focus': (im or {}).get('focus'),
        'impl_duration_min': (im or {}).get('duration_min'),
        'impl_needs_review': (im or {}).get('needs_coach_review'),
        'exercises_count': len(ex),
        'blocks_count': len((im or {}).get('blocks') or []),
        'has_running_content': any(('run' in (e.get('exercise_name_display') or '').lower()) for e in ex),
        'equipment_ctx': ((im or {}).get('equipment_context') or {}).get('equipment'),
    })

# objectives
obj_summary = []
for o in (d.get('training_objectives') or []):
    exposures = [e for e in (d.get('objective_exposures') or []) if e.get('objective_id') == o.get('id')]
    obj_summary.append({
        'id': o.get('id'),
        'kind': o.get('kind'),
        'weekly_target': o.get('weekly_target'),
        'priority': o.get('priority'),
        'phase_id': o.get('phase_id'),
        'exposure_count': len(exposures),
    })

by_layer = {}
for r in (d.get('decision_records') or []):
    by_layer.setdefault(r.get('layer'), []).append({
        'scope_kind': r.get('scope_kind'),
        'scope_id': (r.get('scope_id') or '')[:8],
        'outcome': r.get('outcome'),
        'reason': r.get('reason'),
    })

trace = {
    'client': {'id': d.get('client_id'), 'email': d.get('email'), 'name': d.get('name')},
    'dna_field_audit': [{'field': f, 'value': v, 'v2_usage': u} for f, v, u in dna_fields],
    'goal_resolution': {
        'primary_goal_id_in_profile': prof.get('primary_goal_id'),
        'main_goal_in_profile': prof.get('main_goal'),
        'resolved_v2_taxonomy': goal.get('goal_id_taxonomy'),
        'resolved_source_recorded': next((r.get('reason') for r in (d.get('decision_records') or []) if 'source=' in (r.get('reason') or '')), None),
    },
    'programme': {
        'id': prog.get('id'),
        'timeline_class': prog.get('timeline_class'),
        'start_date': prog.get('start_date'),
        'end_date': prog.get('end_date'),
        'live_plan_version': prog.get('live_plan_version'),
        'draft_plan_version': prog.get('draft_plan_version'),
    },
    'phase_sequence': [{'id': p.get('id'), 'kind': p.get('phase_kind'), 'ordinal': p.get('ordinal'),
                        'start': p.get('planned_start_date'), 'end': p.get('planned_end_date'),
                        'status': p.get('status'), 'purpose': p.get('purpose_summary')}
                       for p in sorted(d.get('programme_phases_v2') or [], key=lambda x: x.get('ordinal') or 0)],
    'objectives': obj_summary,
    'schedule_days': sd_summary,
    'assignments_vs_impls': asg_summary,
    'assignments_missing_impl': [s for s in asg_summary if not s['impl_exists']],
    'assignments_impl_zero_exercises': [s for s in asg_summary if s['impl_exists'] and s['exercises_count'] == 0],
    'implementations_orphan': [i for i in (d.get('workout_implementations') or []) if not any(a.get('draft_implementation_id') == i['id'] or a.get('live_implementation_id') == i['id'] for a in asg)],
    'decision_records_by_layer': {k: v[:8] for k, v in by_layer.items()},
    'counts': counts,
}

with open('/app/memory/PIETRO_V2_GENERATION_TRACE.json', 'w') as f:
    json.dump(trace, f, indent=2, default=str)
print('OK', len(json.dumps(trace)), 'bytes')

# Key findings
print('missing_impl:', len(trace['assignments_missing_impl']))
print('zero_exercise:', len(trace['assignments_impl_zero_exercises']))
print('orphan_impls:', len(trace['implementations_orphan']))
print('goal:', trace['goal_resolution'])
print('phases:', [f"{p['ordinal']}. {p['kind']} ({p['start']}->{p['end']})" for p in trace['phase_sequence']])
# Opportunity distribution
opps = [s['opportunity'] for s in sd_summary if s['opportunity'] is not None]
print('opportunity range:', min(opps), 'to', max(opps), 'across', len(opps), 'days; count=100:', opps.count(100))
# how many days marked layover/turnaround/standby got opp=100
odd = [s for s in sd_summary if s['day_type'] in ('layover_arrival','layover_departure','layover','turnaround') and s['opportunity'] == 100]
print('LAYOVER/TURNAROUND with opp=100:', len(odd))
# impl by focus
from collections import Counter
focus = Counter(s['impl_focus'] for s in asg_summary if s['impl_exists'])
print('impls by focus:', dict(focus))
