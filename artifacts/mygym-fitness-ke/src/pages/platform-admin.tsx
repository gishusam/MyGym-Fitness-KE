import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useAuth, useClerk } from '@clerk/react';
import { Activity, ArrowLeft, ArrowRight, Building2, CheckCircle2, ChevronRight, Clock3, Database, Dumbbell, LogOut, Menu, Plus, RefreshCcw, Search, ShieldCheck, X, AlertCircle } from 'lucide-react';
import { Link } from 'wouter';
import './platform-admin.css';

type Gym = {
  id: string;
  name: string;
  slug: string;
  status: string;
  ownerClerkUserId: string | null;
  environmentKind: string;
  databaseLinked: boolean;
};
type Audit = { id: string; event: string; actorClerkUserId: string; occurredAt: string };
type ApiError = Error & { status?: number };
const LABELS: Record<string,string> = {
  pending_provisioning: 'Pending setup', provisioning: 'Provisioning',
  provision_failed: 'Setup failed', awaiting_owner: 'Awaiting owner',
  linked: 'Linked · activation pending', active: 'Active', suspended: 'Suspended', archived: 'Archived',
};

export function PlatformAdminPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { signOut } = useClerk();
  const [gyms, setGyms] = useState<Gym[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [denied, setDenied] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [creationMode, setCreationMode] = useState<'new' | 'existing'>('new');
  const [gymName, setGymName] = useState('');
  const [slug, setSlug] = useState('');
  const [ownerId, setOwnerId] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [mobileMenu, setMobileMenu] = useState(false);

  async function api<T>(path: string, options?: RequestInit): Promise<T> {
    const token = await getToken();
    if (!token) throw new Error('Sign in to access the platform console.');
    const response = await fetch(path, {
      ...options,
      cache: 'no-store',
      headers: {
        'Authorization': `Bearer ${token}`,
        ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
        ...options?.headers,
      },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as {detail?: {error?:string} | string; error?:string} | null;
      const message = typeof payload?.detail === 'string' ? payload.detail :
        (typeof payload?.detail === 'object' ? payload.detail?.error : undefined) || payload?.error ||
        `Request failed (${response.status})`;
      const failure = new Error(message) as ApiError;
      failure.status = response.status;
      throw failure;
    }
    return response.json() as Promise<T>;
  }

  async function load() {
    setLoading(true);
    setError('');
    try {
      setGyms(await api<Gym[]>('/api/platform/gyms'));
      setDenied(false);
    } catch (e) {
      if ((e as ApiError).status === 403) setDenied(true);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isLoaded && isSignedIn) void load();
    else if (isLoaded) setLoading(false);
  }, [isLoaded, isSignedIn, getToken]);

  useEffect(() => {
    if (!chosen) { setAudit([]); return; }
    let cancelled = false;
    void api<Audit[]>(`/api/platform/gyms/${encodeURIComponent(chosen)}/audit`)
      .then(data => { if (!cancelled) setAudit(data); })
      .catch(() => { if (!cancelled) setAudit([]); });
    return () => { cancelled = true; };
  }, [chosen, getToken]);

  const selected = gyms.find(g => g.id === chosen) || null;
  const filtered = useMemo(() => gyms.filter(g => `${g.name} ${g.slug} ${g.status}`.toLowerCase().includes(search.toLowerCase())), [gyms, search]);
  const active = gyms.filter(g => g.status === 'active').length;
  const pending = gyms.filter(g => ['pending_provisioning', 'provisioning', 'awaiting_owner'].includes(g.status)).length;
  const failed = gyms.filter(g => g.status === 'provision_failed').length;
  const linked = gyms.filter(g => g.databaseLinked).length;
  const demoCount = gyms.filter(g => g.environmentKind === 'demo').length;

  async function createGym(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(''); setFeedback('');
    try {
      const created = await api<Gym>('/api/platform/gyms', {method:'POST', body:JSON.stringify({name:gymName.trim(), slug:slug.trim(), owner_clerk_user_id:ownerId.trim() || null})});
      await load(); setChosen(created.id); setShowCreate(false); setGymName(''); setSlug(''); setOwnerId('');
      setFeedback(`${created.name} registered. Database provisioning is still required.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function requestProvisioning(gym: Gym) {
    if (!window.confirm(`Request provisioning for ${gym.name}? This logs an operator request; it does not create a database automatically.`)) return;
    setBusy(true); setFeedback(''); setError('');
    try {
      await api(`/api/platform/gyms/${encodeURIComponent(gym.id)}/provisioning-request`, {method:'POST'});
      setFeedback('Provisioning request recorded. Run the operator provisioning command to create the gym database.');
      await load();
      setAudit(await api<Audit[]>(`/api/platform/gyms/${encodeURIComponent(gym.id)}/audit`));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function verifyAndActivate(gym: Gym) {
    if (!window.confirm(`Verify the linked database and activate ${gym.name}? This only updates the platform registry; it does not change gym members or staff.`)) return;
    setBusy(true); setError(''); setFeedback('');
    try {
      await api<Gym>(`/api/platform/gyms/${encodeURIComponent(gym.id)}/verify-activate`, {method: 'POST'});
      setFeedback(`${gym.name} verified and activated. Existing gym records were not modified.`);
      await load();
      setAudit(await api<Audit[]>(`/api/platform/gyms/${encodeURIComponent(gym.id)}/audit`));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  if (!isLoaded || (isSignedIn && loading && gyms.length === 0)) return <div className="pa-state"><Activity className="pa-spin" /> Loading platform console…</div>;
  if (!isSignedIn) return <div className="pa-state"><ShieldCheck /><h2>Sign in required</h2><Link href="/sign-in">Sign in to MyGym <ArrowRight size={16}/></Link></div>;
  if (denied) return <div className="pa-state"><ShieldCheck /><h2>Platform access restricted</h2><p>{error}</p><p>Only explicitly authorized platform administrators can access gym records.</p><Link href="/dashboard">Return to MyGym</Link></div>;

  return <div className="pa-app">
    <aside className={`pa-sidebar ${mobileMenu ? 'pa-visible' : ''}`}>
      <div className="pa-brand"><span className="pa-brand-icon"><Dumbbell size={20}/></span><span><b>MyGym</b><small>PLATFORM ADMIN</small></span><button className="pa-mobile-close" onClick={()=>setMobileMenu(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <div className="pa-nav-label">WORKSPACE</div>
      <button className="pa-nav-active" onClick={()=>{setChosen(null);setMobileMenu(false)}}><Building2 size={18}/> Gyms</button>
      <div className="pa-sidebar-note"><ShieldCheck size={20}/><b>Platform-level access</b><p>Manage gym accounts without accessing private member or payment data.</p></div>
      <div className="pa-sidebar-bottom"><Link href="/dashboard"><ArrowLeft size={15}/> Gym workspace</Link><button onClick={()=>signOut({redirectUrl:'/'})}><LogOut size={15}/> Sign out</button></div>
    </aside>
    {mobileMenu && <button className="pa-scrim" onClick={()=>setMobileMenu(false)} aria-label="Close menu"/>}
    <main className="pa-main">
      <header className="pa-topbar"><button className="pa-mobile-open" onClick={()=>setMobileMenu(true)} aria-label="Open navigation"><Menu size={20}/></button><div><span>Platform</span><ChevronRight size={14}/><b>{selected ? selected.name : 'Gym management'}</b></div><span className="pa-admin-pill"><ShieldCheck size={14}/> Super Admin</span></header>
      <div className="pa-content">
        <div className="pa-heading"><div><span className="pa-eyebrow">MYGYM CONTROL CENTER</span><h1>{selected ? selected.name : 'Your gyms, in one place.'}</h1><p>{selected ? 'Gym configuration and platform-level operational status.' : 'Manage onboarding and keep track of every gym using your platform.'}</p></div><div className="pa-actions">{selected && <button className="pa-secondary" onClick={()=>setChosen(null)}><ArrowLeft size={16}/> All gyms</button>}<button className="pa-secondary" onClick={()=>void load()} disabled={loading}><RefreshCcw size={16}/> Refresh</button>{!selected && <button className="pa-primary" onClick={()=>setShowCreate(true)}><Plus size={16}/> Create gym</button>}</div></div>
        {error && <div className="pa-alert" role="alert"><AlertCircle size={18}/>{error}<button onClick={()=>setError('')} aria-label="Dismiss"><X size={15}/></button></div>}
        {feedback && <div className="pa-success" role="status"><CheckCircle2 size={17}/>{feedback}</div>}
        {!selected ? <>
          <div className="pa-kpis"><div className="pa-kpi"><span><Building2 size={19}/></span><small>Total gyms</small><strong>{gyms.length}</strong><p>{linked} linked environments · {demoCount} demo</p><p>Registered on MyGym</p></div><div className="pa-kpi"><span><CheckCircle2 size={19}/></span><small>Active gyms</small><strong>{active}</strong><p>Activated accounts</p></div><div className="pa-kpi"><span><Clock3 size={19}/></span><small>Onboarding</small><strong>{pending}</strong><p>Awaiting completion</p></div><div className="pa-kpi"><span><AlertCircle size={19}/></span><small>Failed setups</small><strong>{failed}</strong><p>Require intervention</p></div></div>
          <section className="pa-panel"><div className="pa-panel-heading"><div><span className="pa-eyebrow">TENANT DIRECTORY</span><h2>All gyms</h2><p>Records from the platform registry — no example or fabricated data.</p></div><div className="pa-search"><Search size={17}/><input aria-label="Search gyms" placeholder="Search gyms…" value={search} onChange={e=>setSearch(e.target.value)}/></div></div>
            {filtered.length ? <div className="pa-table-scroll"><table className="pa-table"><thead><tr><th>Gym</th><th>Owner</th><th>Status</th><th>Action</th></tr></thead><tbody>{filtered.map(g=><tr key={g.id}><td><div className="pa-gym-cell"><span>{g.name.charAt(0).toUpperCase()}</span><div><b>{g.name}</b><small>{g.slug} · {g.environmentKind === 'demo' ? 'Demo' : g.environmentKind === 'development' ? 'Development' : 'Customer'} {g.databaseLinked ? '· Linked' : ''}</small></div></div></td><td>{g.ownerClerkUserId ? 'Assigned' : 'Not assigned'}</td><td><span className={`pa-status pa-${g.status}`}>{LABELS[g.status] || g.status}</span></td><td><button className="pa-open" onClick={()=>setChosen(g.id)}>View gym <ArrowRight size={15}/></button></td></tr>)}</tbody></table></div> : <div className="pa-empty"><Building2 size={26}/><b>{gyms.length ? 'No matching gyms' : 'No gyms registered yet'}</b><p>{gyms.length ? 'Try another search.' : 'Add your first gym to begin platform onboarding.'}</p></div>}</section>
        </> : <div className="pa-detail-layout"><div className="pa-panel"><div className="pa-panel-heading"><div><span className="pa-eyebrow">GYM PROFILE</span><h2>{selected.name}</h2><p>Registered tenant · {selected.slug}</p></div><span className={`pa-status pa-${selected.status}`}>{LABELS[selected.status] || selected.status}</span></div><div className="pa-info-row"><span>Gym identifier</span><code>{selected.id}</code></div><div className="pa-info-row"><span>Owner Clerk ID</span><b>{selected.ownerClerkUserId || 'Not assigned'}</b></div><div className="pa-info-row"><span>Environment</span><b>{selected.environmentKind === 'demo' ? 'Demo' : selected.environmentKind === 'development' ? 'Development' : 'Customer'} · {selected.databaseLinked ? 'Database linked' : 'No database linked'}</b></div><div className="pa-info-row"><span>Provisioning</span><b>{LABELS[selected.status] || selected.status}</b></div><div className="pa-detail-actions">{selected.databaseLinked && ['linked','active'].includes(selected.status) && <button className="pa-primary" disabled={busy} onClick={()=>void verifyAndActivate(selected)}><CheckCircle2 size={17}/> {selected.status === 'active' ? 'Reverify gym' : 'Verify & Activate'}</button>}{['pending_provisioning','provision_failed'].includes(selected.status) && <button className="pa-primary" disabled={busy} onClick={()=>void requestProvisioning(selected)}><Database size={17}/> Request provisioning</button>}</div></div><div className="pa-panel pa-support"><div className="pa-panel-heading"><div><span className="pa-eyebrow">SUPPORT & AUDIT</span><h2>Platform activity</h2></div></div>{audit.length ? audit.map(a=><div className="pa-audit-row" key={a.id}><Activity size={16}/><span><b>{a.event.replaceAll('_',' ')}</b><small>{new Date(a.occurredAt).toLocaleString('en-KE')}</small></span></div>) : <p className="pa-muted">No recent platform events for this gym.</p>}<div className="pa-support-note"><ShieldCheck size={19}/><div><b>View as Gym — coming next</b><p>Support access will require explicit authorization, time limits and full auditing. No owner impersonation is enabled.</p></div></div></div></div>}
      </div>
    </main>
    {showCreate && <div className="pa-modal-overlay" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)setShowCreate(false)}}><div className="pa-modal" role="dialog" aria-modal="true" aria-labelledby="pa-add-title"><div className="pa-modal-head"><h2 id="pa-add-title">Add gym</h2><button type="button" onClick={()=>setShowCreate(false)} aria-label="Close"><X size={20}/></button></div><p>Manage all gyms from this console. Existing databases must be verified by an operator before they appear as linked.</p>
      <div className="pa-add-choice" role="group" aria-label="Gym onboarding method"><button type="button" className={creationMode === 'new' ? 'selected' : ''} onClick={()=>setCreationMode('new')}>Create new gym</button><button type="button" className={creationMode === 'existing' ? 'selected' : ''} onClick={()=>setCreationMode('existing')}>Link existing gym</button></div>
      {creationMode === 'existing' ? <div className="pa-existing-notice"><ShieldCheck size={19}/><div><b>Connect an existing environment</b><p>To import MyGym Fitness KE and DemoFit Studio, run the verified local linking command provided with Milestone 9C.1. This prevents users from submitting database credentials in a browser. Refresh this page after linking.</p><button type="button" className="pa-secondary" onClick={()=>{setShowCreate(false); void load()}}>Back to all gyms</button></div></div> : <form onSubmit={e=>void createGym(e)}><label>Gym name<input required minLength={2} maxLength={120} value={gymName} onChange={e=>{setGymName(e.target.value);setSlug(e.target.value.toLowerCase().trim().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''))}} placeholder="e.g. Riverside Fitness"/></label><label>Unique gym slug<input required minLength={3} maxLength={64} pattern="[a-z0-9]+(-[a-z0-9]+)*" value={slug} onChange={e=>setSlug(e.target.value)} placeholder="riverside-fitness"/></label><label>Owner Clerk user ID (optional)<input value={ownerId} onChange={e=>setOwnerId(e.target.value)} placeholder="Leave blank until owner onboarding"/></label><div className="pa-modal-actions"><button type="button" className="pa-secondary" onClick={()=>setShowCreate(false)}>Cancel</button><button type="submit" className="pa-primary" disabled={busy}>{busy ? 'Registering…' : 'Register gym'} <ArrowRight size={15}/></button></div></form>}</div></div>}
  </div>;
}
