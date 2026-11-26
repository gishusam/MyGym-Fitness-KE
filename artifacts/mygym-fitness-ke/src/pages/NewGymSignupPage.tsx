import { useEffect, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'wouter';
import { Building2, CheckCircle2, LoaderCircle, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';
import { customFetch } from '@workspace/api-client-react';
import './new-gym-signup.css';

type GymSignup = {
  id: string;
  gym_name: string;
  status: string;
  auto_setup_available: boolean;
};

export function NewGymSignupPage() {
  const [, navigate] = useLocation();
  const [gym, setGym] = useState<GymSignup | null>(null);
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    customFetch<GymSignup | null>('/api/platform/signup/me', { responseType: 'json' })
      .then((result) => {
        if (!disposed) {
          setGym(result);
          setError('');
        }
      })
      .catch(() => {
        if (!disposed) setError('Could not check your gym registration. Check the platform connection and your sign-in session.');
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [refresh]);

  // Poll while the platform provisions; an already registered gym resumes
  // automatically on revisiting this page, including after server restarts.
  useEffect(() => {
    if (!gym || gym.status === 'active' || !gym.auto_setup_available) return;
    const id = window.setInterval(() => setRefresh(n => n + 1), 4000);
    return () => window.clearInterval(id);
  }, [gym?.id, gym?.status, gym?.auto_setup_available]);

  useEffect(() => {
    if (gym?.status !== 'active') return;
    document.cookie = `mygym_gym=${encodeURIComponent(gym.id)}; Path=/api; SameSite=Lax`;
    navigate('/setup');
  }, [gym, navigate]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || name.trim().length < 2) return;
    setSaving(true);
    setError('');
    try {
      const registered = await customFetch<GymSignup>('/api/platform/signup/gyms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gym_name: name.trim() }),
        responseType: 'json',
      });
      setGym(registered);
    } catch {
      setError('Unable to register this gym. Please check your account verification and try again.');
    } finally {
      setSaving(false);
    }
  }

  const isActive = gym?.status === 'active';
  const isWorking = Boolean(gym && gym.auto_setup_available && !isActive);
  return <main className="ngs-shell">
    <header className="ngs-header"><Link href="/">MyGym</Link><span><ShieldCheck size={15}/> Secure gym onboarding</span></header>
    <section className="ngs-card">
      <div className="ngs-icon"><Building2 size={25}/></div>
      <span className="ngs-kicker">NEW GYM SETUP</span>
      <h1>Make MyGym<br/>yours.</h1>
      {loading && !gym ? <p><LoaderCircle size={16} className="spin"/> Checking registration…</p> : gym ? <>
        <div className="ngs-confirm">
          {isActive ? <CheckCircle2 size={20}/> : <LoaderCircle size={20} className={isWorking ? 'spin' : ''}/>} 
          <div><b>{gym.gym_name}</b><small>{isActive ? 'Your gym is ready' : isWorking ? 'Preparing your private gym workspace' : 'Gym registration received'}</small></div>
        </div>
        {isWorking ? <p>We’re securely setting up your gym and owner access. This page will continue automatically when it is ready.</p> : isActive
          ? <p>Setup complete! Opening your gym onboarding…</p>
          : <div className="ngs-error" role="status"><AlertCircle size={17}/> Automatic gym setup is temporarily unavailable. Your registration is saved. Please contact the platform administrator; you do not need to register again.</div>}
        <button type="button" className="ngs-primary" disabled={loading || isActive} onClick={() => setRefresh(n => n + 1)}>
          {loading ? 'Checking…' : 'Check setup status'} <ArrowRight size={16}/>
        </button>
      </> : <>
        <p>Enter your gym name to create a separate, private workspace for its members, subscriptions and staff.</p>
        <form onSubmit={submit}>
          <label htmlFor="ngs-gym">Gym name</label>
          <input id="ngs-gym" autoFocus minLength={2} maxLength={120} required
            placeholder="e.g. Riverside Fitness Club" value={name} onChange={e => setName(e.target.value)}/>
          <button className="ngs-primary" disabled={saving || name.trim().length < 2}>
            {saving ? 'Registering…' : 'Create my gym'} <ArrowRight size={16}/>
          </button>
        </form>
      </>}
      {error && <div className="ngs-error" role="alert">{error}</div>}
      <p className="ngs-small">Already manage a gym? <Link href="/dashboard">Go to dashboard</Link></p>
    </section>
  </main>;
}
