"""Stateless Python 3.12 boundary. JSON files in/out; no database or credentials.

Only supplied frozen inference and combination functions are called. The gas
result, if supplied by the existing job ledger, is passed through unchanged.
"""
import argparse
import contextlib
import io
import json
import runpy
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parent


def daily_json(frame):
    """Lossless float transport; pandas.to_json defaults to rounding at10 digits."""
    import pandas as pd
    records=frame.astype(object).where(pd.notna(frame),None).to_dict(orient='records')
    return json.dumps(records,ensure_ascii=False,allow_nan=False,default=str)


def compute(snapshot, *, issued_at, sensor=True, fire=True):
    sys.path.insert(0, str(HOME / 'vendor'))
    import pandas as pd
    from ml.incident_scenarios.command import score_journal
    from ml.incident_scenarios.daily import raw_to_daily
    from ml.incident_scenarios.evidence import combine_evidence

    root = HOME / 'vendor'
    registry = json.loads((root / 'examples/registry.json').read_text())
    d = snapshot['as_of_date']
    catalogue = pd.DataFrame(snapshot['catalogue'], dtype=str).fillna('')
    journal = pd.DataFrame(snapshot['journal'], dtype=str).fillna('')
    outputs = {}; failures = {}
    for name, enabled in [('sensor_failure', sensor), ('fire', fire)]:
        if not enabled:
            outputs[name] = None; failures[name] = 'MODULE_DISABLED'; continue
        try:
            if name == 'sensor_failure':
                outputs[name] = score_journal(root/'models/incident_sensor_integrated_v2.zip',
                    journal, catalogue, d, coverage=snapshot['coverage'], issued_at=issued_at,
                    replay=False, heads=['sensor_failure'])
            else:
                # Invoke the delivered fire wrapper itself, including its manifest
                # validation and binding, without reimplementing its mathematics.
                with tempfile.TemporaryDirectory(prefix='scenario_fire_') as tmp:
                    tmp = Path(tmp)
                    daily = raw_to_daily(journal, catalogue)
                    daily['d_cutoff_date'] = daily['d_cutoff_date'].map(str)
                    (tmp/'daily.json').write_text(daily_json(daily), encoding='utf8')
                    catalogue.to_csv(tmp/'catalogue.csv', index=False)
                    (tmp/'coverage.json').write_text(json.dumps(snapshot['coverage']))
                    argv = sys.argv
                    try:
                        sys.argv = ['predict_fire_candidate_with_binding.py', '--sdk-root', str(root),
                            '--daily', str(tmp/'daily.json'), '--catalogue', str(tmp/'catalogue.csv'),
                            '--coverage', str(tmp/'coverage.json'), '--as-of', d, '--issued-at', issued_at,
                            '--output', str(tmp/'output.json')]
                        with contextlib.redirect_stdout(io.StringIO()):
                            runpy.run_path(str(root/'predict_fire_candidate_with_binding.py'), run_name='__main__')
                    finally:
                        sys.argv = argv
                    outputs[name] = json.loads((tmp/'output.json').read_text(encoding='utf8'))
        except Exception as exc:
            # Never serialize an exception message containing a source value/path.
            code = str(exc)
            failures[name] = code if code.isupper() and code.replace('_','').isalnum() else type(exc).__name__
            outputs[name] = None
    combined = combine_evidence(snapshot.get('gas'), outputs['sensor_failure'], outputs['fire'],
        registry=registry, catalogue=catalogue, decision_at=issued_at,
        worker_issued_at={'gas': snapshot.get('gas_issued_at')})
    combined['worker_errors'] = failures
    combined['package_release'] = 'COMBINED_EVIDENCE_V1_1'
    # No NaN/Infinity escapes this boundary, including raw worker outputs.
    json.dumps(combined, allow_nan=False)
    return combined


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--issued-at', required=True)
    parser.add_argument('--no-sensor', action='store_true')
    parser.add_argument('--no-fire', action='store_true')
    args = parser.parse_args()
    result = compute(json.loads(Path(args.input).read_text(encoding='utf8')),
        issued_at=args.issued_at, sensor=not args.no_sensor, fire=not args.no_fire)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf8')
