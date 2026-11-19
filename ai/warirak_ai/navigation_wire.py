"""Strict simulation wire decoding and validation fixtures; no model or transport.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

_BYTES = (Path(__file__).resolve().parents[1] / 'navigation-history-layout.json').read_bytes()
_LAYOUT = json.loads(_BYTES.decode('utf-8-sig'))
LAYOUT_SHA256 = hashlib.sha256(_BYTES).hexdigest()
VECTOR_SIZE = _LAYOUT['vector_size']
VALIDATION_MODEL_SCHEMA = 'warirak.navigation-validation-fixture.v1'
_REQUEST_KEYS = {'schema','source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','encoded_at_ms','valid_until_ms','history_frames','frame_size','vector_size','vector_sha256','vector','allowed_mask','control_enabled','physical_motor_transport'}
_FIELDS = _LAYOUT['field_order']
_INDEX = {name: i for i, name in enumerate(_FIELDS)}
_SIGNED = {'target.bearing','motion.forward','motion.lateral','motion.yaw'}
_NUMERIC = {'frame.age',*[f'range.{i}.value' for i in range(8)],'range.age','target.bearing','target.range','motion.forward','motion.lateral','motion.yaw','motion.margin','pose.age','motion.age','ack.age'}
_PAIRS = [(f'range.{i}.value',f'range.{i}.known') for i in range(8)] + [('target.bearing','target.bearing_known'),('target.range','target.range_known'),('motion.margin','motion.margin_known'),('range.age','range.age_known'),('pose.age','pose.age_known'),('motion.age','motion.age_known'),('ack.age','ack.age_known')]

def _safe(value):
    return type(value) is int and 0 <= value <= 9007199254740991

def _stamp(value):
    return _safe(value) and value > 0

def _id(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}', value) is not None

def _finite(value):
    if type(value) not in (int,float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

def vector_digest(vector):
    if type(vector) is not list or len(vector) != VECTOR_SIZE or any(not _finite(v) or v < -1 or v > 1 for v in vector):
        raise ValueError('Invalid finite vector')
    return hashlib.sha256(struct.pack('<'+'d'*len(vector), *[0.0 if v == 0 else float(v) for v in vector])).hexdigest()

def validate_vector(vector):
    vector_digest(vector)
    size = _LAYOUT['frame_size']
    for f in range(_LAYOUT['frame_count']):
        row = vector[f*size:(f+1)*size]
        get = lambda name: row[_INDEX[name]]
        for name, value in zip(_FIELDS, row):
            if (name not in _SIGNED and value < 0) or (name not in _NUMERIC and value not in (0,1)):
                raise ValueError('Invalid vector domain or binary flag')
        if get('frame.present') == 0:
            if any(v != 0 for v in row):
                raise ValueError('Padding frame contains data')
            continue
        for prefix, values in [('authority',_LAYOUT['authority_order']),('mission',_LAYOUT['mission_order']),('ack',_LAYOUT['ack_order']),('previous_request',_LAYOUT['previous_request_order'])]:
            if sum(get(prefix+'.'+v) for v in values) != 1:
                raise ValueError('Invalid categorical one-hot group')
        if any(get(k) == 0 and get(v) != 0 for v,k in _PAIRS):
            raise ValueError('Unknown value is not canonical zero')
        if get('motion.known') == 0 and any(get(n) != 0 for n in ['motion.forward','motion.lateral','motion.yaw','motion.margin_known','pose.new_at_observation','motion.new_at_observation','motion.range_synchronized']):
            raise ValueError('Motion data without measured-motion evidence')
    return vector

def validate_request(request, *, now_ms=None):
    r = request
    if type(r) is not dict or set(r) != _REQUEST_KEYS:
        raise ValueError('Unexpected wire request keys')
    if (r['schema'] != 'warirak.navigation-inference-request.v1' or r['source'] != 'simulation' or r['plant_environment'] != _LAYOUT['plant_environment'] or r['encoder_schema'] != _LAYOUT['encoder_schema'] or r['layout_sha256'] != LAYOUT_SHA256 or r['control_enabled'] is not False or r['physical_motor_transport'] is not False or not _id(r['session_id']) or not _id(r['request_id']) or not _safe(r['stream_epoch']) or not _safe(r['record_sequence']) or not all(_stamp(r[k]) for k in ['observation_at_ms','encoded_at_ms','valid_until_ms'])):
        raise ValueError('Invalid simulation inference request')
    if r['encoded_at_ms'] < r['observation_at_ms'] or r['valid_until_ms'] != r['observation_at_ms']+_LAYOUT['maximum_age_ms'] or r['encoded_at_ms'] >= r['valid_until_ms']:
        raise ValueError('Invalid original request time window')
    if (type(r['history_frames']) is not int or r['history_frames'] != _LAYOUT['frame_count'] or type(r['frame_size']) is not int or r['frame_size'] != _LAYOUT['frame_size'] or type(r['vector_size']) is not int or r['vector_size'] != VECTOR_SIZE or type(r['allowed_mask']) is not list or len(r['allowed_mask']) != 7 or any(type(v) is not bool for v in r['allowed_mask']) or not any(r['allowed_mask'])):
        raise ValueError('Invalid vector shape or original action mask')
    validate_vector(r['vector'])
    if vector_digest(r['vector']) != r['vector_sha256']:
        raise ValueError('Vector digest mismatch')
    if now_ms is not None and (not _stamp(now_ms) or now_ms < r['encoded_at_ms'] or now_ms >= r['valid_until_ms']):
        raise ValueError('Inference request expired or clock regressed')
    return r

def masked_argmax(q_values, mask):
    if type(q_values) is not list or len(q_values) != 7 or any(not _finite(v) for v in q_values) or type(mask) is not list or len(mask) != 7 or any(type(v) is not bool for v in mask) or not any(mask):
        raise ValueError('Invalid finite Q values or action mask')
    allowed = [i for i, ok in enumerate(mask) if ok]
    return max(allowed, key=lambda i: q_values[i])

def validation_fixture_reply(request, q_values, *, now_ms):
    r = validate_request(request, now_ms=now_ms)
    result = {k:r[k] for k in ['source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','valid_until_ms','vector_sha256','control_enabled','physical_motor_transport']}
    result.update(schema='warirak.navigation-inference-reply.v1', model_schema=VALIDATION_MODEL_SCHEMA, action=masked_argmax(q_values, r['allowed_mask']))
    return result

def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result

def _constant(value):
    raise ValueError('Nonfinite JSON constant: '+value)

def decode_json(data):
    if not isinstance(data, (str,bytes)) or len(data if isinstance(data,bytes) else data.encode('utf-8')) > 65536:
        raise ValueError('Bounded JSON input required')
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)

def main():
    parser = argparse.ArgumentParser(description='Validation fixture only: no trained model, training or actuator')
    parser.add_argument('--fixture-batch', action='store_true', required=True)
    parser.parse_args()
    wrapper = decode_json(sys.stdin.buffer.read(65537))
    if type(wrapper) is not dict or set(wrapper) != {'cases'} or type(wrapper['cases']) is not list or not 1 <= len(wrapper['cases']) <= 16:
        raise ValueError('Bounded fixture batch required')
    results = []
    for c in wrapper['cases']:
        try:
            if type(c) is not dict or set(c) != {'request','q_values','now_ms'}:
                raise ValueError('Unexpected fixture keys')
            request = validate_request(c['request'], now_ms=c['now_ms'])
            reply = validation_fixture_reply(request, c['q_values'], now_ms=c['now_ms'])
            results.append({'ok':True,'reply':reply,'echo_vector':request['vector'],'vector_sha256':vector_digest(request['vector'])})
        except (ValueError,TypeError,KeyError) as exc:
            results.append({'ok':False,'error':str(exc)})
    print(json.dumps({'schema':'warirak.navigation-wire-validation.v1','fixture_only':True,'trained_model_loaded':False,'results':results}, ensure_ascii=True, allow_nan=False))

if __name__ == '__main__':
    main()
