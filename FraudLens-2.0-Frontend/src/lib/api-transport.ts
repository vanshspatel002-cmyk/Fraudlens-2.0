// Keep browser requests and the server's connect-src policy on the same origin.
export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const upload = options.body instanceof FormData;
  const timeout = AbortSignal.timeout(upload ? 120000 : 45000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    return await fetch(API_BASE + path, { ...options, signal });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (timeout.aborted) {
      throw new Error(upload
        ? 'Submission confirmation timed out. Your entered information is preserved. Check your dashboard before retrying the same form.'
        : 'The request timed out. Refresh to check the latest saved status before trying again.');
    }
    throw new Error('The FraudLens API could not be reached. Check your connection and refresh to try again.');
  }
}
