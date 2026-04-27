#!/usr/bin/env python3
"""SkillSentry step validator - enforces compliance after each step"""
import json, sys, os

def validate(session_dir, step):
    with open(f"{session_dir}/session.json") as f:
        s = json.load(f)
    
    errors = []
    warnings = []
    
    field_map = {
        'step-0': ['skill', 'mode', 'skill_type', 'skill_hash'],
        'step-0.5': ['requirements'],
        'step-2': ['lint'],
        'step-3': ['trigger'],
        'step-4': ['cases'],
        'step-4.5': ['sync.push_cases'],
        'step-5': ['executor'],
        'step-6': ['grader', 'verdict'],
        'step-6.5': ['sync.push_results'],
        'step-7': [],
        'step-7.5': ['sync.push_run'],
    }
    
    for field in field_map.get(step, []):
        if '.' in field:
            parts = field.split('.')
            val = s
            for p in parts:
                val = val.get(p, {}) if isinstance(val, dict) else None
        else:
            val = s.get(field)
        
        if val is None or val == {}:
            errors.append(f"session.json.{field} is empty after {step}")
    
    # Pre-report gate check
    if step == 'step-7':
        sync = s.get('sync', {})
        if sync.get('push_cases') is None:
            errors.append("⛔ BLOCKED: sync.push_cases is null (Step 4.5 skipped)")
        if sync.get('push_results') is None:
            errors.append("⛔ BLOCKED: sync.push_results is null (Step 6.5 skipped)")
    
    # Transcript count check
    if step == 'step-5':
        mode_runs = {'smoke': 1, 'quick': 2, 'standard': 3, 'full': 3}
        expected_runs = mode_runs.get(s.get('mode', 'full'), 3)
        total = s.get('cases', {}).get('total', 30)
        expected = total * expected_runs
        actual = s.get('executor', {}).get('success', 0)
        if actual < expected:
            warnings.append(f"Expected {expected} transcripts, got {actual}")
    
    # Milestone audit: check card was sent with interactive format
    milestone_steps = ['step-0', 'step-0.5', 'step-2', 'step-3', 'step-4', 'step-4.5', 'step-5', 'step-6', 'step-6.5', 'step-7', 'step-7.5']
    if step in milestone_steps:
        milestones = s.get('milestones', {})
        m = milestones.get(step)
        if m is None:
            errors.append(f"milestones.{step} not recorded (card not sent or milestone not written)")
        elif m.get('msg_type') != 'interactive':
            errors.append(f"milestones.{step}.msg_type = '{m.get('msg_type')}' (must be 'interactive')")
    
    # Final completeness check
    if step == 'step-7.5':
        sync = s.get('sync', {})
        for k in ['pull', 'push_cases', 'push_results', 'push_run']:
            if sync.get(k) is None:
                errors.append(f"sync.{k} is null at final step")
        # Check all milestones exist
        milestones = s.get('milestones', {})
        missing_ms = [st for st in milestone_steps if st not in milestones]
        if missing_ms:
            warnings.append(f"Missing milestones: {', '.join(missing_ms)}")
    
    if errors:
        print(f"❌ FAIL after {step}:")
        for e in errors:
            print(f"  {e}")
        return False
    elif warnings:
        print(f"⚠️ PASS with warnings after {step}:")
        for w in warnings:
            print(f"  {w}")
        return True
    else:
        print(f"✅ PASS after {step}")
        return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 validate_step.py <session_dir> <step>")
        sys.exit(1)
    ok = validate(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
