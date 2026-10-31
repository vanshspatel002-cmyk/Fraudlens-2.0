import { apiFetch } from '../lib/api-transport';
const TOKEN_KEY = 'fraudlens_customer_token';
export const customerToken = () => typeof window === 'undefined' ? '' : sessionStorage.getItem(TOKEN_KEY) || '';
export function clearCustomerSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem('fraudlens_customer_email');
}
export async function customerFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  const token = customerToken();
  if (token) headers.set('Authorization', 'Bearer ' + token);
  const response = await apiFetch(path, {...options, headers});
  if (token !== customerToken()) throw new Error('Your customer session changed. Open this view again.');
  if (response.status === 401 && !path.endsWith('/login') && !path.endsWith('/register')) {
    if (token === customerToken()) {
      clearCustomerSession();
      window.dispatchEvent(new Event('fraudlens-customer-session-expired'));
    }
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as {message?: string; details?: {field?: string; reason?: string}[]};
    const failure=new Error([data.message, ...(data.details || []).map(d => [d.field,d.reason].filter(Boolean).join(': '))]
      .filter(Boolean).join(' ') || 'The request could not be completed. Please retry.');
    Object.assign(failure,{status:response.status});
    throw failure;
  }
  return response;
}
export async function customerRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = customerToken();
  const result = await (await customerFetch(path, options)).json() as T;
  if (token !== customerToken()) throw new Error('Your customer session changed. Open this view again.');
  return result;
}
export async function customerLogin(mode: 'login' | 'register', values: {email: string; password: string; name?: string}) {
  const data = await customerRequest<{user: string; token: string}>(`/v1/customer/auth/${mode}`, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(values),
  });
  sessionStorage.setItem(TOKEN_KEY, data.token);
  sessionStorage.setItem('fraudlens_customer_email', data.user);
  return data;
}
export async function customerLogout() {
  const token = customerToken();
  try { await customerRequest('/v1/customer/auth/logout', {method:'POST'}); }
  finally { if (token === customerToken()) {clearCustomerSession(); window.dispatchEvent(new Event('fraudlens-customer-session-expired'));} }
}
