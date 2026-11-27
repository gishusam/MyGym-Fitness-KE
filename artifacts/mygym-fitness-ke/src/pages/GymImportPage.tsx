import { useState, type ChangeEvent } from 'react';
import { Link } from 'wouter';
import { useGetCurrentStaff, useListMembershipPlans, customFetch } from '@workspace/api-client-react';
import { ArrowLeft, ArrowRight, CheckCircle2, Download, FileSpreadsheet, LoaderCircle, UploadCloud, XCircle } from 'lucide-react';
import { StaffFrame } from './operations';

interface ImportRow {
  row: number;
  name: string;
  phone: string;
  plan: string | null;
  startsOn: string | null;
  expiresOn: string | null;
  action: string;
  errors: string[];
}
interface ImportPreview { total: number; ready: number; invalid: number; rows: ImportRow[] }
interface ImportResult { importedMembers: number; importedSubscriptions: number; processedRows: number }
interface Payload { filename: string; content_base64: string }

const TEMPLATE = 'Full Name,Phone,Email,Plan,Start Date,Expiry Date\nJane Example,0712345678,jane@example.com,Peak Access,2026-11-01,2026-11-30\nJohn Example,0722345678,,Off-Peak,2026-11-10,2026-12-09\n';
function errorText(e: unknown): string {
  if (e && typeof e === 'object') {
    const v = e as { data?: { detail?: { error?: string } | string }; message?: string };
    const detail = v.data?.detail;
    if (typeof detail === 'object' && detail?.error) return detail.error;
    if (typeof detail === 'string') return detail;
    if (v.message) return v.message;
  }
  return 'Request failed. Check your session and try again.';
}
function decodeFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Unable to read file'));
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.readAsDataURL(file);
  });
}
export function GymImportPage() {
  const staff = useGetCurrentStaff();
  const plans = useListMembershipPlans();
  const [file, setFile] = useState<Payload | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  async function handleFile(ev: ChangeEvent<HTMLInputElement>) {
    setError(''); setPreview(null); setResult(null); setConfirmed(false); setFile(null);
    const selected = ev.target.files?.[0];
    if (!selected) return;
    if (!/\.(csv|xlsx)$/i.test(selected.name)) { setError('Upload a CSV or Excel (.xlsx) file.'); return; }
    if (selected.size > 2_000_000) { setError('File must be under 2 MB (max 2,000 members).'); return; }
    try { setFile({ filename: selected.name, content_base64: await decodeFile(selected) }); }
    catch { setError('Could not read the selected file.'); }
  }
  async function runPreview() {
    if (!file) return;
    setBusy(true); setError(''); setPreview(null); setConfirmed(false);
    try {
      setPreview(await customFetch<ImportPreview>('/api/setup/import/preview', { method: 'POST', responseType: 'json', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(file) }));
    } catch(e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  async function runCommit() {
    if (!file || !preview || preview.invalid || !confirmed) return;
    setBusy(true); setError('');
    try {
      const done = await customFetch<ImportResult>('/api/setup/import/commit', { method: 'POST', responseType: 'json', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(file) });
      setResult(done); setPreview(null); setConfirmed(false);
    } catch(e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  function downloadTemplate() {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([TEMPLATE], { type:'text/csv;charset=utf-8' }));
    link.download = 'mygym-member-import-template.csv'; link.click();
    URL.revokeObjectURL(link.href);
  }
  if (staff.isLoading) return <p style={{padding:32}}>Checking access…</p>;
  if (staff.error || !staff.data) return <p style={{padding:32}}>Sign in with your gym owner account to continue. <Link href="/sign-in">Sign in</Link></p>;
  if (staff.data.role !== 'owner') return <p style={{padding:32}}>Only gym owners can import membership records. <Link href="/dashboard">Back to dashboard</Link></p>;
  return <StaffFrame active="members">
    <div className="mig-page">
      <Link href="/setup" className="mig-back"><ArrowLeft size={16}/> Back to gym setup</Link>
      <div className="mig-heading"><div><span className="mig-eyebrow">GYM SETUP / DATA MIGRATION</span><h1>Bring your members over.</h1><p>Import your existing members and paid membership periods in one file. Preview every row before saving.</p></div><FileSpreadsheet size={42}/></div>
      <div className="mig-step-grid">
        <article><b>01 · Gym details</b><p>Set your gym's name and operating preferences.</p><Link href="/settings/gym">Gym settings <ArrowRight size={14}/></Link></article>
        <article><b>02 · Membership plans</b><p>Create your plans first so imported records match them.</p><Link href="/membership-plans">Manage plans <ArrowRight size={14}/></Link></article>
        <article className="mig-active"><b>03 · Import existing members</b><p>Upload members together with their current plans and expiry dates.</p></article>
      </div>
      <div className="mig-layout"><section className="mig-card">
        <h2><UploadCloud size={21}/> Upload records</h2>
        <p>Use CSV or Excel (.xlsx), up to 2 MB / 2,000 rows. Include <b>Full Name</b> and <b>Phone</b>. Plan, Start Date, and Expiry Date are optional as a group.</p>
        <button type="button" onClick={downloadTemplate} className="mig-secondary"><Download size={15}/> Download example CSV</button>
        <label className="mig-file"><UploadCloud size={25}/><span>{file?.filename || 'Choose a CSV or Excel spreadsheet'}</span><small>Existing members can be matched by their phone number.</small><input type="file" accept=".csv,.xlsx" onChange={handleFile}/></label>
        <button className="mig-main" disabled={!file||busy} onClick={runPreview}>{busy?<LoaderCircle size={16}/>:<FileSpreadsheet size={16}/>} Validate and preview</button>
        {error && <div className="mig-error" role="alert"><XCircle size={16}/>{error}</div>}
        {result && <div className="mig-success" role="status"><CheckCircle2 size={22}/><div><b>Import complete</b><p>{result.importedMembers} new members and {result.importedSubscriptions} subscription periods saved.</p><Link href="/members">Go to Members <ArrowRight size={14}/></Link></div></div>}
      </section><aside className="mig-card mig-aside"><h2>Plans in this gym</h2><p>Match the plan names in your spreadsheet exactly with those configured here.</p>
        {plans.isLoading?<p>Loading plans…</p>:plans.data?.length?plans.data.map(p=><div className="mig-plan" key={p.id}><strong>{p.name}</strong><span>KES {p.monthlyPriceKes.toLocaleString('en-KE')}/month</span></div>):<p>No active plans found. Create your plans before importing subscriptions.</p>}
        <Link href="/membership-plans" className="mig-secondary">Edit membership plans <ArrowRight size={14}/></Link>
        <div className="mig-note"><b>Historical subscriptions aren't payments.</b><p>Expiry dates are kept as provided. This import does not generate M-Pesa or cash transactions, charge customers or send WhatsApp messages.</p></div>
      </aside></div>
      {preview && <section className="mig-card mig-preview"><h2>Import preview</h2><div className="mig-stats"><div><b>{preview.total}</b><span>Total rows</span></div><div><b>{preview.ready}</b><span>Ready</span></div><div><b>{preview.invalid}</b><span>Need attention</span></div></div>
        {preview.invalid>0 && <p className="mig-warning">Correct the highlighted rows in your spreadsheet and upload it again. Nothing has been imported.</p>}
        <div className="mig-table"><table><thead><tr><th>Row</th><th>Member</th><th>Phone</th><th>Plan</th><th>Subscription period</th><th>Action / errors</th></tr></thead><tbody>{preview.rows.map(row=><tr key={row.row}><td>{row.row}</td><td>{row.name}</td><td>{row.phone}</td><td>{row.plan||'—'}</td><td>{row.startsOn?`${row.startsOn} → ${row.expiresOn}`:'—'}</td><td>{row.errors.length?<span className="mig-bad">{row.errors.join('; ')}</span>:<span className="mig-good">{row.action==='create_member'?'New member':'Existing member'}</span>}</td></tr>)}</tbody></table></div>
        {preview.invalid===0 && <div className="mig-confirm"><label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> I have checked these records and confirm this is the correct gym database.</label><button className="mig-main" disabled={!confirmed||busy} onClick={runCommit}>{busy?'Importing…':'Confirm and import'} <ArrowRight size={16}/></button></div>}
      </section>}
    </div>
  </StaffFrame>;
}
