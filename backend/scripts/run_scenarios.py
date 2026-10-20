"""Run the separate frozen scenario modules after a certified readiness marker."""
import argparse
import json
from app.scenario_job import run_scenarios

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready-marker',required=True)
    parser.add_argument('--retry-failed',action='store_true')
    args=parser.parse_args()
    print(json.dumps(run_scenarios(args.ready_marker,retry=args.retry_failed)))
