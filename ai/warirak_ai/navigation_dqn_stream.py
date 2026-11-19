"""Bounded JSONL forward-pass SOFTWARE fixture; never loads a trained checkpoint."""
import argparse
import json
import sys

from .navigation_dqn import NavigationDQN
from .navigation_wire import decode_json, validate_request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight-stream',action='store_true',required=True)
    parser.add_argument('--seed',type=int,default=73)
    args=parser.parse_args()
    model=NavigationDQN(args.seed,'f'*64)
    session=None
    previous_epoch=previous_record=-1
    previous_at=previous_now=-1
    ids=set()
    for _ in range(32):
        line=sys.stdin.buffer.readline(65537)
        if not line:
            return
        try:
            wrapper=decode_json(line)
            if type(wrapper) is not dict or set(wrapper) != {'request','now_ms'}:
                raise ValueError('Explicit simulation clock and request required')
            request=validate_request(wrapper['request'],now_ms=wrapper['now_ms'])
            if (session is not None and request['session_id'] != session or
                request['request_id'] in ids or request['stream_epoch'] < previous_epoch or
                request['record_sequence'] <= previous_record or request['observation_at_ms'] <= previous_at or
                wrapper['now_ms'] < previous_now):
                raise ValueError('Duplicate/regressing stream identity or clock')
            session=request['session_id']
            ids.add(request['request_id'])
            previous_epoch,previous_record=request['stream_epoch'],request['record_sequence']
            previous_at,previous_now=request['observation_at_ms'],wrapper['now_ms']
            reply=model.preflight_reply(request,now_ms=wrapper['now_ms'])
            print(json.dumps(dict(schema='warirak.navigation-dqn-stream-preflight.v1',
                ok=True,fixture_only=True,trained_model_loaded=False,optimizer_steps=0,
                physical_motor_transport=False,reply=reply),allow_nan=False),flush=True)
        except (ValueError,TypeError,KeyError) as exc:
            print(json.dumps(dict(ok=False,error=str(exc),fixture_only=True,
                trained_model_loaded=False,optimizer_steps=0,physical_motor_transport=False)),flush=True)
            raise SystemExit(2)
    if sys.stdin.buffer.read(1):
        raise SystemExit('Software stream message budget exceeded')


if __name__=='__main__':
    main()
