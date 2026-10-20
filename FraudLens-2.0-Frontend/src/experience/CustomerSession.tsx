import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { customerLogin, customerRequest, customerToken } from './customer-api';
import { Logo } from './shared';
import './customer-session.css';

export function CustomerGate({children}: {children: ReactNode}) {
  const [state, setState] = useState<'checking'|'signed-in'|'signed-out'|'unavailable'>('checking');
  const [mode, setMode] = useState<'login'|'register'>('login');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    if (!customerToken()) setState('signed-out');
    else customerRequest('/v1/customer/auth/session').then(() => {if (!cancelled) setState('signed-in');})
      .catch((e: Error) => {if (!cancelled) {setError(e.message); setState(customerToken() ? 'unavailable' : 'signed-out');}});
    const expired = () => {setState('signed-out'); setError('Your customer session ended. Sign in to continue.');};
    window.addEventListener('fraudlens-customer-session-expired', expired);
    return () => {cancelled = true; window.removeEventListener('fraudlens-customer-session-expired', expired);};
  }, [attempt]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      await customerLogin(mode, {email: String(form.get('email') || '').trim(),
        password: String(form.get('password') || ''), name: String(form.get('name') || '').trim()});
      setState('signed-in');
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  if (state === 'signed-in') return <>{children}</>;
  return <main className="customer-access">
    <Logo />
    <section className="customer-access-card">
      {state === 'checking' ? <p role="status">Checking your customer session…</p> : state === 'unavailable' ? <>
        <h1>We could not check your session.</h1><p role="alert">{error}</p>
        <button onClick={() => {setState('checking'); setAttempt(x => x + 1);}}>Retry connection</button>
      </> : <>
        <span className="customer-kicker">YOUR FRAUDLENS ACCOUNT</span>
        <h1>{mode === 'login' ? 'Sign in to your workspace.' : 'Create your customer account.'}</h1>
        <p>Submit claims and underwriting applications, respond to evidence requests, and follow your reviewer’s decision.</p>
        <form onSubmit={submit}>
          {mode === 'register' && <label className="field"><span>Your name</span>
            <input name="name" required minLength={2} maxLength={160} autoComplete="name" /></label>}
          <label className="field"><span>Email address</span>
            <input name="email" type="email" required maxLength={254} autoComplete="username" /></label>
          <label className="field"><span>Password{mode === 'register' ? ' (at least 12 characters)' : ''}</span>
            <input name="password" type="password" required minLength={mode === 'register' ? 12 : 1} maxLength={1024}
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'} /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in as customer' : 'Create account'}</button>
        </form>
        <button className="customer-link" disabled={busy} onClick={() => {setMode(mode === 'login' ? 'register' : 'login'); setError('');}}>
          {mode === 'login' ? 'New here? Create an account' : 'Already registered? Sign in'}
        </button>
      </>}
    </section>
    <a href="/">Back to website</a>
  </main>;
}
