import assert from 'node:assert/strict';
import test from 'node:test';

import { detectSourceType, sourceTypeMismatch } from '../lib/source-detect.ts';

test('detects GitHub repository URLs separately from generic web pages', () => {
  assert.equal(detectSourceType('https://github.com/koala73/worldmonitor'), 'github_repo');
  assert.equal(detectSourceType('https://github.com/koala73/worldmonitor/tree/main'), 'web_url');
  assert.equal(detectSourceType('https://example.com/docs'), 'web_url');
});

test('detects local Windows and POSIX paths', () => {
  assert.equal(detectSourceType('E:\\projects\\worldmonitor'), 'local_directory');
  assert.equal(detectSourceType('\\\\server\\share\\project'), 'local_directory');
  assert.equal(detectSourceType('/opt/projects/worldmonitor'), 'local_directory');
  assert.equal(detectSourceType('relative/path'), null);
});

test('reports actionable type mismatches in Chinese', () => {
  assert.match(sourceTypeMismatch('local_directory', 'https://github.com/koala73/worldmonitor') ?? '', /GitHub 仓库/);
  assert.match(sourceTypeMismatch('github_repo', 'E:\\projects\\worldmonitor') ?? '', /本地路径/);
  assert.equal(sourceTypeMismatch('github_repo', 'https://github.com/koala73/worldmonitor'), null);
  assert.equal(sourceTypeMismatch('local_directory', 'E:\\projects\\worldmonitor'), null);
});
