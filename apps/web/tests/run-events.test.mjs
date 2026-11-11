import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSseFrame, mergeRunEvents, runEventStreamUrl, streamTerminalState } from '../lib/run-events.ts';

test('same origin event URLs work with the relative API prefix', () => {
  assert.equal(runEventStreamUrl('project 1', 'run/2', 7, 'http://localhost:3000'),
    'http://localhost:3000/api/projects/project%201/runs/run%2F2/events/stream?after_sequence=7');
});

test('SSE parses CRLF and multiline JSON and ignores heartbeats', () => {
  assert.equal(parseSseFrame(': keepalive'), null);
  assert.deepEqual(parseSseFrame('id: 4\r\nevent: node_completed\r\ndata: {"sequence":4,\r\ndata: "node_name":"analyze_sources"}'),
    { id: '4', event: 'node_completed', data: { sequence: 4, node_name: 'analyze_sources' } });
});

test('malformed SSE does not kill the subscription', () => {
  assert.equal(parseSseFrame('event: node_completed\ndata: {broken'), null);
  assert.equal(parseSseFrame('event: node_completed\ndata: null'), null);
});

test('reconnect replay deduplicates events and retains latest sequence order', () => {
  const event = (sequence) => ({ id: String(sequence), event: 'node_completed', data: { sequence } });
  assert.deepEqual(mergeRunEvents([event(2)], [event(1), event(2), event(3)]).map(e => e.data.sequence), [1,2,3]);
});

test('replaying a failed attempt does not stop reconnect for a current retry', () => {
  assert.equal(['run_started', 'run_failed', 'run_retry_queued', 'run_started', 'node_completed']
    .reduce(streamTerminalState, false), false);
  assert.equal(['run_completed', 'run_resume_queued', 'run_started']
    .reduce(streamTerminalState, false), false);
  assert.equal(['run_failed', 'run_retry_queued', 'run_completed']
    .reduce(streamTerminalState, false), true);
});
