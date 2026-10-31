import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { afterEach, test } from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/api-transport.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { apiFetch, API_BASE } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
const originalFetch = globalThis.fetch;
const originalTimeout = AbortSignal.timeout;
afterEach(() => { globalThis.fetch = originalFetch; AbortSignal.timeout = originalTimeout; });

test('local requests use the pilot API and retain upload identity and credentials', async () => {
  const body = new FormData();
  body.set('person_name', 'Fictional test applicant');
  let deadline;
  AbortSignal.timeout = milliseconds => { deadline = milliseconds; return new AbortController().signal; };
  globalThis.fetch = async (url, options) => {
    assert.equal(url, API_BASE + '/v1/cases');
    assert.equal(options.body, body);
    assert.equal(options.headers['Idempotency-Key'], 'same-submission-key');
    assert.equal(options.headers.Authorization, 'Bearer test-token');
    return new Response('{}', { status: 201 });
  };
  assert.equal(API_BASE, 'http://127.0.0.1:8001');
  assert.equal((await apiFetch('/v1/cases', {method: 'POST', body,
    headers: {'Idempotency-Key': 'same-submission-key', Authorization: 'Bearer test-token'}})).status, 201);
  assert.equal(deadline, 120000);
});

test('a slow response is distinguished from an unreachable API', async () => {
  AbortSignal.timeout = () => AbortSignal.abort(new DOMException('Timed out', 'TimeoutError'));
  globalThis.fetch = async (_url, options) => { throw options.signal.reason; };
  await assert.rejects(apiFetch('/v1/cases'), /request timed out.*latest saved status/);
  await assert.rejects(apiFetch('/v1/cases', {method: 'POST', body: new FormData()}), /Submission confirmation timed out.*same form/);
});

test('network errors and HTTP errors retain different meanings', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(apiFetch('/v1/cases'), /could not be reached/);
  const response = new Response(JSON.stringify({code: 'DATABASE_UNAVAILABLE'}), {status: 503});
  globalThis.fetch = async () => response;
  assert.equal(await apiFetch('/v1/cases'), response);
});

test('caller cancellation is preserved', async () => {
  const reason = new DOMException('View closed', 'AbortError');
  globalThis.fetch = async (_url, options) => { throw options.signal.reason; };
  await assert.rejects(apiFetch('/v1/cases', {signal: AbortSignal.abort(reason)}), error => error === reason);
});
