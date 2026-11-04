import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'wouter';
import { BrowserMultiFormatReader } from '@zxing/browser';
import { QRCodeSVG } from 'qrcode.react';
import {
  ArrowLeft, ArrowRight, Check, ChevronLeft, ChevronRight, CircleAlert, Clock3,
  CreditCard, Dumbbell, LoaderCircle, Pencil, Plus, QrCode, RefreshCw, Search,
  ShieldCheck, UserRound, UsersRound, Wallet, X,
} from 'lucide-react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  getGetMemberDetailQueryKey, getListCheckInsQueryKey, getListMembersQueryKey,
  getListMembershipPlansQueryKey, getListPaymentsQueryKey, getListSubscriptionsQueryKey,
  useConfirmCheckIn, useCreateMember, useCreateMembershipPlan, useCreateSubscription,
  useGetCurrentStaff, useGetMemberDetail, useListCheckIns, useListMembers,
  useListMembershipPlans, useListPayments, useListSubscriptions, useLookupAttendance,
  useOverrideCheckIn, useRecordPayment, useRotateMemberQr, useUpdateMember,
  useUpdateMembershipPlan, useVoidPayment, customFetch,
} from '@workspace/api-client-react';
import type { AttendanceReview, MembershipPlan, MembershipPlanInput, PaymentMethod } from '@workspace/api-client-react';

type Kind = 'members' | 'membership-plans' | 'subscriptions' | 'payments' | 'attendance';
const money = (value: number) => `KES ${new Intl.NumberFormat('en-KE').format(value)}`;
const date = (value?: string | null) => value ? new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeZone: 'Africa/Nairobi' }).format(new Date(value)) : '—';
const time = (value?: string | null) => value ? new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Africa/Nairobi' }).format(new Date(value)) : '—';
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const todayInNairobi = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={`op-notice ${error ? 'is-error' : ''}`} role={error ? 'alert' : 'status'} data-testid={error ? 'status-operation-error' : 'status-operation-note'}>{error ? <CircleAlert size={17} /> : <ShieldCheck size={17} />}{children}</div>;
}
function serverError(error: unknown, fallback: string) {
  if (error && typeof error === 'object' && 'data' in error) {
    const body = (error as { data?: unknown }).data;
    if (body && typeof body === 'object' && 'error' in body && typeof body.error === 'string') return body.error;
  }
  return fallback;
}
function LoadingRows() { return <div className="op-skeletons" aria-label="Loading records">{[1, 2, 3].map((n) => <div className="op-skeleton" key={n} />)}</div>; }
function Status({ value }: { value: string }) { return <span className={`op-status status-${value}`}>{value.replaceAll('_', ' ')}</span>; }
function Heading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail: string; action?: ReactNode }) {
  return <header className="op-heading"><div><div className="op-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{detail}</p></div>{action}</header>;
}
function StaffFrame({ children, active }: { children: ReactNode; active: Kind }) {
  const staff = useGetCurrentStaff();
  const nav: [Kind, string, typeof UsersRound][] = [['members', 'Members', UsersRound], ['membership-plans', 'Plans', Dumbbell], ['subscriptions', 'Subscriptions', CreditCard], ['payments', 'Payments', Wallet], ['attendance', 'Attendance', QrCode]];
  if (staff.isLoading) return <div className="op-loading"><LoadingRows /></div>;
  if (staff.error || !staff.data) return <div className="op-loading"><Notice error>Staff access could not be confirmed. Refresh this page or sign in again.</Notice></div>;
  return <div className="op-workspace">
    <aside className="op-rail"><Link href="/dashboard" className="op-brand"><span className="op-brand-mark"><Dumbbell size={18} /></span><span><b>MyGym</b><small>FITNESS KE</small></span></Link>
      <div className="op-rail-caption">GYM OPERATIONS</div><nav>{nav.map(([key, label, Icon]) => <Link key={key} href={`/${key}`} className={`op-nav ${active === key ? 'current' : ''}`} data-testid={`link-${key}`}><Icon size={17} />{label}</Link>)}</nav>
      <div className="op-rail-bottom"><span className="op-avatar">{staff.data.name.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase()}</span><span><b>{staff.data.name}</b><small>{staff.data.role}</small></span><Link href="/settings/gym" aria-label="Gym settings" className="op-settings" data-testid="link-operation-settings">Settings</Link></div>
    </aside>
    <main className="op-main"><div className="op-topline"><Link href="/dashboard" data-testid="link-back-overview"><ArrowLeft size={15} /> Overview</Link><span><i /> {staff.data.role} workspace</span></div><div className="op-content">{children}</div></main>
  </div>;
}

export function MembersPage() { return <StaffFrame active="members"><Members /></StaffFrame>; }
function Members() {
  const client = useQueryClient();
  const [search, setSearch] = useState(''), [page, setPage] = useState(1), [mode, setMode] = useState<'new' | 'edit' | 'profile' | null>(null), [selected, setSelected] = useState('');
  const query = useListMembers({ search: search || undefined, page, pageSize: 10 });
  const profile = useGetMemberDetail(selected, { query: { queryKey: getGetMemberDetailQueryKey(selected), enabled: !!selected } });
  const create = useCreateMember(), update = useUpdateMember(), rotate = useRotateMemberQr();
  const wizardPlans = useListMembershipPlans();
  const wizardSubscription = useCreateSubscription();
  const [wizardStep, setWizardStep] = useState(0);
  const [wizardPlanId, setWizardPlanId] = useState('');
  const [wizardStart, setWizardStart] = useState(todayInNairobi);
  const [wizardSaving, setWizardSaving] = useState(false);
  const [name, setName] = useState(''), [phone, setPhone] = useState(''), [email, setEmail] = useState(''), [formError, setFormError] = useState(''), [success, setSuccess] = useState('');
  const [assessmentOpen, setAssessmentOpen] = useState(false);
  const [measurements, setMeasurements] = useState({weightKg:'',heightCm:'',bodyFatPercent:'',musclePercent:'',visceralFatLevel:''});
  const resetForm = () => { setName(''); setPhone(''); setEmail(''); setFormError(''); setAssessmentOpen(false); setMeasurements({weightKg:'',heightCm:'',bodyFatPercent:'',musclePercent:'',visceralFatLevel:''}); };
  const resetWizard = () => {setWizardStep(0);setWizardPlanId('');setWizardStart(todayInNairobi());};
  const parsedWeight = Number(measurements.weightKg);
  const parsedHeight = Number(measurements.heightCm);
  const previewBmi = measurements.weightKg && measurements.heightCm && parsedWeight > 0 && parsedHeight > 0
    ? (parsedWeight / ((parsedHeight / 100) ** 2)).toFixed(1) : '—';

  function openEdit(id: string) {
    setSelected(id); const row = query.data?.items.find((item) => item.id === id);
    if (row) { setName(row.fullName); setPhone(row.phone); setEmail(row.email || ''); setMode('edit'); }
  }
  function validatePersonal() {
    if(name.trim().length<2){setFormError('Enter a name with at least 2 characters.');return false;}
    if(!/^(?:\+?254|0)(?:7|1)\d{8}$/.test(phone.trim().replace(/[\s()-]/g,''))){setFormError('Enter a valid Kenyan mobile number.');return false;}
    if(email.trim()&&!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())){setFormError('Enter a valid email address.');return false;}
    return true;
  }
  async function submitWizard(event: FormEvent) {
    event.preventDefault();
    if(wizardSaving)return;
    setFormError('');
    if(!validatePersonal()){setWizardStep(0);return;}
    if(wizardPlanId&&!wizardStart){setFormError('Select a membership start date.');return;}
    const fields = Object.entries(measurements).filter(([,v])=>v.trim()!=='');
    const values = Object.fromEntries(fields.map(([k,v])=>[k,Number(v)]));
    const memberData = {fullName:name.trim(),phone:phone.trim(),email:email.trim()||null,initialAssessment:fields.length?(values as {weightKg?:number;heightCm?:number;bodyFatPercent?:number;musclePercent?:number;visceralFatLevel?:number}):null};
    setWizardSaving(true);
    let createdId:string|undefined;
    try {
      const created=await create.mutateAsync({data:memberData});
      createdId=created.id;
      if(wizardPlanId){
        try {await wizardSubscription.mutateAsync({memberId:created.id,data:{planId:wizardPlanId,startsOn:wizardStart}});}
        catch(error){setSuccess(`Member registered, but the membership could not be assigned. Open Subscriptions to assign it manually. ${serverError(error,'')}`);setMode(null);resetForm();resetWizard();return;}
      }
      setSuccess(wizardPlanId?'Member registered and membership assigned.':'Member registered.');
      setMode(null);resetForm();resetWizard();
    } catch(error) {
      if(!createdId)setFormError(serverError(error,'Member could not be registered. Please check the details.'));
    } finally {
      await client.invalidateQueries({queryKey:getListMembersQueryKey()});
      await client.invalidateQueries({queryKey:getListSubscriptionsQueryKey()});
      setWizardSaving(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setFormError(''); setSuccess('');
    const normalizedPhone = phone.trim().replace(/[\s()-]/g, '');
    if (name.trim().length < 2) { setFormError('Enter a name with at least 2 characters.'); return; }
    if (!/^(?:\+?254|0)(?:7|1)\d{8}$/.test(normalizedPhone)) { setFormError('Enter a valid Kenyan mobile number.'); return; }
    const fields = Object.entries(measurements).filter(([, value]) => value.trim() !== '');
    const assessment = Object.fromEntries(fields.map(([key, value]) => [key, Number(value)]));
    const data = mode === 'new' ? {
      fullName: name.trim(), phone: phone.trim(), email: email.trim() || null,
      initialAssessment: fields.length ? (assessment as {weightKg?:number;heightCm?:number;bodyFatPercent?:number;musclePercent?:number;visceralFatLevel?:number}) : null,
    } : { fullName: name.trim(), phone: phone.trim(), email: email.trim() || null };

    const opts = { onSuccess: async () => { await client.invalidateQueries({ queryKey: getListMembersQueryKey() }); if (selected) await client.invalidateQueries({ queryKey: getGetMemberDetailQueryKey(selected) }); setMode(null); resetForm(); setSuccess(mode === 'edit' ? 'Member details updated.' : 'Member registered.'); }, onError: (error: unknown) => setFormError(serverError(error, 'Could not save this member. Check the details and try again.')) };
    if (mode === 'edit') update.mutate({ memberId: selected, data }, opts); else create.mutate({ data }, opts);
  }
  return <>
    <Heading eyebrow="MEMBER DIRECTORY" title="Members" detail="Find people quickly, keep their details accurate, and manage their access card."
      action={<button className="op-button op-primary" onClick={() => { resetForm(); resetWizard(); setSelected(''); setMode('new'); }} data-testid="button-register-member"><Plus size={16} /> Register member</button>} />
    {success && <Notice>{success}</Notice>}
    <section className="op-panel"><div className="op-toolbar"><label className="op-search"><Search size={17} /><input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search name, number or phone" data-testid="input-member-search" /></label><span className="op-count" data-testid="text-member-total">{query.data?.total ?? '—'} members</span></div>
    {query.isLoading ? <LoadingRows /> : query.error ? <Notice error>Member records could not be loaded. <button onClick={() => query.refetch()} data-testid="button-retry-members">Try again</button></Notice> : !query.data?.items.length ? <div className="op-empty"><UsersRound size={25} /><b>{search ? 'No matching members' : 'Your member list starts here'}</b><p>{search ? 'Try another name, member number or phone.' : 'Register a member to create their profile and QR access card.'}</p></div> :
      <div className="op-table-wrap"><table className="op-table"><thead><tr><th>Member</th><th>Phone</th><th>Registered</th><th>Status</th><th /></tr></thead><tbody>{query.data.items.map((m) => <tr key={m.id} data-testid={`row-member-${m.id}`}><td><button className="op-person" onClick={() => { setSelected(m.id); setMode('profile'); }} data-testid={`button-profile-${m.id}`}><span className="op-initials">{m.initials}</span><span><b>{m.fullName}</b><small>{m.memberNumber}</small></span></button></td><td>{m.phone}</td><td>{date(m.registeredAt)}</td><td><Status value={m.status} /></td><td className="op-row-actions"><button className="op-icon-button" aria-label={`Edit ${m.fullName}`} onClick={() => openEdit(m.id)} data-testid={`button-edit-member-${m.id}`}><Pencil size={15} /></button><button className="op-text-button" onClick={() => { setSelected(m.id); setMode('profile'); }} data-testid={`button-view-member-${m.id}`}>View <ArrowRight size={14} /></button></td></tr>)}</tbody></table></div>}
    <div className="op-pagination"><span>Page {page} of {Math.max(1, Math.ceil((query.data?.total || 0) / 10))}</span><div><button disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="button-members-previous"><ChevronLeft size={16} /> Previous</button><button disabled={page >= Math.ceil((query.data?.total || 0) / 10)} onClick={() => setPage(page + 1)} data-testid="button-members-next">Next <ChevronRight size={16} /></button></div></div></section>
    {mode === 'edit' && <div className="op-overlay"><section className="op-dialog op-edit-member-dialog"><button className="op-close" onClick={() => setMode(null)} aria-label="Close" data-testid="button-close-member-form"><X size={18}/></button><div className="op-modal-kicker">MEMBER DETAILS</div><h2>Edit member</h2><p>Update the member’s contact information.</p><form className="op-form" onSubmit={submit}><label>Full name<input value={name} onChange={e=>setName(e.target.value)} required minLength={2} maxLength={160}/></label><label>Phone number<input value={phone} onChange={e=>setPhone(e.target.value)} required minLength={9} maxLength={20}/></label><label>Email <span className="op-optional">Optional</span><input type="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>{formError && <Notice error>{formError}</Notice>}<div className="op-form-actions"><button type="button" className="op-button op-light" onClick={()=>setMode(null)}>Cancel</button><button className="op-button op-primary" disabled={update.isPending}>Save changes</button></div></form><MemberSubscriptionEditor memberId={selected}/></section></div>}
    {mode === 'new' && <div className="op-overlay op-wizard-overlay">
      <section className="op-dialog op-registration-wizard" role="dialog" aria-modal="true" aria-labelledby="op-registration-title">
        <div className="op-wizard-heading"><UserRound size={22}/><h2 id="op-registration-title">Register a new gym member</h2><button type="button" className="op-wizard-close" aria-label="Close registration" onClick={()=>setMode(null)}><X size={19}/></button></div>
        <nav className="op-wizard-steps" aria-label="Registration steps">{(['Personal details','Fitness assessment','Membership'] as const).map((label,i)=><button key={label} type="button" className={`op-wizard-step ${wizardStep===i?'is-current':''} ${wizardStep>i?'is-past':''}`} onClick={()=>{if(i===0 || wizardStep!==0 || validatePersonal()) {setFormError('');setWizardStep(i);}}} aria-current={wizardStep===i?'step':undefined}><span>{i+1}. {label}</span><i/></button>)}</nav>
        <form className="op-wizard-form" onSubmit={submitWizard}>
          {wizardStep===0 && <div className="op-wizard-personal">
            <label>Full name<input type="text" value={name} onChange={e=>setName(e.target.value)} required minLength={2} maxLength={160} placeholder="Full name" data-testid="input-member-name"/></label>
            <label>Phone number<input type="tel" value={phone} onChange={e=>setPhone(e.target.value)} required placeholder="07XX XXX XXX" data-testid="input-member-phone"/></label>
            <label>Email <span className="op-wizard-optional">Optional</span><input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com" data-testid="input-member-email"/></label>
          </div>}
          {wizardStep===1 && <div className="op-wizard-metrics">
            {([['weightKg','Weight','kg'],['heightCm','Height','cm'],['bodyFatPercent','Body fat','%'],['musclePercent','Muscle','%'],['visceralFatLevel','Visceral fat','level']] as const).map(([key,label,unit])=><label key={key}>{label}<input type="number" min={key==='weightKg'||key==='heightCm'?'0.01':'0'} max={key==='weightKg'?'500':key==='heightCm'?'300':'100'} step="any" inputMode="decimal" placeholder={unit} value={measurements[key]} onChange={e=>setMeasurements(prev=>({...prev,[key]:e.target.value}))} data-testid={`input-fitness-${key}`}/></label>)}
            <div className="op-wizard-bmi" aria-live="polite"><span>BMI</span><strong>{previewBmi==='—'?'Auto-calculated':previewBmi}</strong></div>
          </div>}
          {wizardStep===2 && <div className="op-wizard-membership">
            <label>Membership plan <span className="op-wizard-optional">Optional</span><select value={wizardPlanId} onChange={e=>setWizardPlanId(e.target.value)} data-testid="select-registration-plan"><option value="">Assign a plan later</option>{wizardPlans.data?.filter(plan=>plan.isActive).map(plan=><option key={plan.id} value={plan.id}>{plan.name} — {money(plan.monthlyPriceKes)}</option>)}</select></label>
            {wizardPlanId && <label>Membership starts on<input type="date" value={wizardStart} onChange={e=>setWizardStart(e.target.value)} required data-testid="input-registration-start"/></label>}
            <p className="op-wizard-hint">{wizardPlanId?'A one-month subscription will be created after the member is registered.':'You can register now and assign a membership from Subscriptions later.'}</p>
          </div>}
          {formError && <div className="op-wizard-error" role="alert">{formError}</div>}
          <div className="op-wizard-footer"><span>{wizardStep===1?'Optional during registration; recorded as the initial assessment':wizardStep===2?'Payment is recorded separately in Payments.':'Member registration'}</span><div className="op-wizard-buttons">{wizardStep>0 && <button type="button" className="op-wizard-back" disabled={wizardSaving} onClick={()=>{setFormError('');setWizardStep(wizardStep-1)}}>Back</button>}{wizardStep<2?<button type="button" className="op-wizard-next" onClick={()=>{if(wizardStep===0&&!validatePersonal()) return;setFormError('');setWizardStep(wizardStep+1)}}>Next step <ArrowRight size={18}/></button>:<button type="submit" className="op-wizard-next" disabled={wizardSaving||create.isPending||wizardSubscription.isPending} data-testid="button-save-member">{wizardSaving?'Registering…':'Register member'} <ArrowRight size={18}/></button>}</div></div>
        </form>
      </section>
    </div>}
    {mode === 'profile' && <div className="op-overlay"><section className="op-dialog op-profile-dialog"><button className="op-close" onClick={() => setMode(null)} aria-label="Close profile" data-testid="button-close-member-profile"><X size={18} /></button>{profile.isLoading ? <LoadingRows /> : profile.error || !profile.data ? <Notice error>Member profile unavailable. Close and try again.</Notice> : <><div className="op-modal-kicker">MEMBER PROFILE</div><h2>{profile.data.fullName}</h2><p>{profile.data.memberNumber} · Registered {date(profile.data.registeredAt)}</p><div className="op-profile-grid"><div className="op-profile-details"><div><small>Phone</small><b>{profile.data.phone}</b></div><div><small>Email</small><b>{profile.data.email || 'Not provided'}</b></div><div><small>Membership status</small><Status value={profile.data.status} /></div>{profile.data.latestAssessment && <div className="op-latest-assessment"><small>Initial/latest fitness assessment</small><b>{profile.data.latestAssessment.weightKg ?? '—'} kg · BMI {profile.data.latestAssessment.bmi ?? '—'}</b><small>Height: {profile.data.latestAssessment.heightCm ?? '—'} cm · Body fat: {profile.data.latestAssessment.bodyFatPercent ?? '—'}% · Muscle: {profile.data.latestAssessment.musclePercent ?? '—'}% · Visceral fat: {profile.data.latestAssessment.visceralFatLevel ?? '—'}</small></div>}<button className="op-button op-light" onClick={() => openEdit(profile.data!.id)} data-testid="button-edit-profile">Edit member</button></div><div className="op-qr-card"><QRCodeSVG value={profile.data.qrToken} size={148} level="M" data-testid="qr-member-token" /><b>Member access card</b><small>Keep this code private.</small><button className="op-text-button" onClick={() => { if (window.confirm('Rotate this QR card? The current code will stop working.')) rotate.mutate({ memberId: profile.data!.id }, { onSuccess: async () => { await client.invalidateQueries({ queryKey: getGetMemberDetailQueryKey(profile.data!.id) }); setSuccess('QR access card rotated.'); }, onError: (error: unknown) => setFormError(serverError(error, 'QR card could not be rotated.')) }); }} disabled={rotate.isPending} data-testid="button-rotate-qr"><RefreshCw size={14} /> {rotate.isPending ? 'Rotating…' : 'Rotate QR card'}</button>{formError && <span className="op-error-inline">{formError}</span>}</div></div><MemberFitnessPanel memberId={selected}/></>}</section></div>}
  </>;
}

// MYGYM_TASK5_ASSESSMENTS_V1
interface AssessmentItem {
  id: string;
  recordedAt: string;
  weightKg: number | null;
  heightCm: number | null;
  bmi: number | null;
  bodyFatPercent: number | null;
  musclePercent: number | null;
  visceralFatLevel: number | null;
}
type AssessmentFields = 'weightKg'|'heightCm'|'bodyFatPercent'|'musclePercent'|'visceralFatLevel';
const assessmentFields: {key:AssessmentFields;label:string;unit:string}[] = [
  {key:'weightKg',label:'Weight',unit:'kg'}, {key:'heightCm',label:'Height',unit:'cm'},
  {key:'bodyFatPercent',label:'Body fat',unit:'%'}, {key:'musclePercent',label:'Muscle',unit:'%'},
  {key:'visceralFatLevel',label:'Visceral fat',unit:'level'},
];
const freshMeasurements = () => ({weightKg:'',heightCm:'',bodyFatPercent:'',musclePercent:'',visceralFatLevel:''});
function MemberFitnessPanel({memberId}:{memberId:string}) {
  const client = useQueryClient();
  const [adding,setAdding] = useState(false);
  const [values,setValues] = useState(freshMeasurements);
  const [message,setMessage] = useState('');
  const endpoint=`/api/members/${encodeURIComponent(memberId)}/fitness-assessments`;
  const query=useQuery({
    queryKey:['fitness-assessments',memberId],
    queryFn:()=>customFetch<{items:AssessmentItem[]}>(endpoint,{responseType:'json'}),
  });
  const create=useMutation({
    mutationFn:(data:Partial<Record<AssessmentFields,number>>)=>customFetch<AssessmentItem>(endpoint,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),responseType:'json',
    }),
    onSuccess:async()=>{
      setAdding(false);setValues(freshMeasurements());setMessage('Fitness assessment saved.');
      await client.invalidateQueries({queryKey:['fitness-assessments',memberId]});
      await client.invalidateQueries({queryKey:getGetMemberDetailQueryKey(memberId)});
    },
    onError:(err:unknown)=>setMessage(serverError(err,'Could not save assessment. Please retry.')),
  });
  const readings=query.data?.items??[];
  const latest=readings[0];
  const oldest=readings[readings.length-1];
  const fmt=(v:number|null|undefined,unit='')=>v==null?'—':`${Number(v.toFixed(1))}${unit ? ' '+unit : ''}`;
  const points=readings.slice().reverse().filter(r=>r.weightKg!=null);
  const weights=points.map(r=>r.weightKg!);
  const min=weights.length?Math.min(...weights):0, max=weights.length?Math.max(...weights):1;
  const plotPoints=points.map((r,i)=>`${16+(points.length===1?0:i/(points.length-1)*500)},${108-(r.weightKg!-min)/(max-min||1)*84}`).join(' ');
  const w=Number(values.weightKg),h=Number(values.heightCm);
  const bmi=values.weightKg&&values.heightCm&&w>0&&h>0?(w/((h/100)**2)).toFixed(1):'—';
  function submit(e:FormEvent){
    e.preventDefault();setMessage('');
    const entries=Object.entries(values).filter(([,v])=>v.trim()!=='');
    if(!entries.length){setMessage('Enter at least one measurement.');return;}
    const data=Object.fromEntries(entries.map(([k,v])=>[k,Number(v)]));
    for(const [k,v] of entries){const n=Number(v);const maxVal=k==='heightCm'?300:k==='weightKg'?500:100;
      if(!Number.isFinite(n)||n<(k==='weightKg'||k==='heightCm'?0.001:0)||n>maxVal){setMessage('Check the entered measurement ranges.');return;}}
    create.mutate(data);
  }
  return <section className="op-fitness-section" data-testid="member-fitness-history">
    <div className="op-fitness-heading"><div><h3>Fitness progress</h3><p>Measurements and reassessments</p></div>
      <button type="button" className="op-button op-light" onClick={()=>{setAdding(v=>!v);setMessage('');}}>{adding?'Cancel':'Record assessment'}</button></div>
    {message&&<p className="op-fitness-message" role="status">{message}</p>}
    {adding&&<form className="op-fitness-form" onSubmit={submit}>
      <div className="op-fitness-fields">{assessmentFields.map(f=><label key={f.key}>{f.label} ({f.unit})
        <input type="number" step="any" min={f.key==='weightKg'||f.key==='heightCm'?'0.01':'0'}
          max={f.key==='weightKg'?'500':f.key==='heightCm'?'300':'100'} placeholder="Optional"
          value={values[f.key]} onChange={e=>setValues(p=>({...p,[f.key]:e.target.value}))}/>
      </label>)}<div className="op-fitness-bmi"><span>BMI</span><strong>{bmi}</strong><small>Auto-calculated</small></div></div>
      <div className="op-form-actions"><button type="submit" className="op-button op-primary" disabled={create.isPending}>{create.isPending?'Saving…':'Save assessment'}</button></div>
    </form>}
    {query.isLoading?<LoadingRows/>:query.isError?<p className="op-fitness-message">Could not load fitness history. <button type="button" onClick={()=>query.refetch()}>Retry</button></p>:
      !latest?<p className="op-muted">No fitness assessments yet. Record the first measurements above.</p>:<>
        <div className="op-fitness-kpis">{assessmentFields.map(f=><div key={f.key}><small>{f.label}</small><b>{fmt(latest[f.key],f.unit)}</b></div>)}<div><small>BMI</small><b>{fmt(latest.bmi)}</b></div></div>
        {latest.weightKg!=null&&oldest?.weightKg!=null&&readings.length>1&&<p className="op-fitness-delta">Weight change since first assessment: <strong>{fmt(latest.weightKg-oldest.weightKg,'kg')}</strong></p>}
        {points.length>1&&<div className="op-fitness-chart"><span>Weight trend (kg)</span><svg viewBox="0 0 532 124" role="img" aria-label="Weight progression over recorded assessments" preserveAspectRatio="none"><polyline points={plotPoints} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg></div>}
        <div className="op-fitness-history"><h4>Assessment history</h4><div className="op-fitness-entries">{readings.map(r=><div key={r.id}><time>{date(r.recordedAt)}</time><span>{fmt(r.weightKg,'kg')} · BMI {fmt(r.bmi)} · Body fat {fmt(r.bodyFatPercent,'%')}</span></div>)}</div></div>
      </>}
  </section>;
}

// MYGYM_EDIT_MEMBER_SUBSCRIPTIONS_V1
// Existing subscriptions are immutable. A new term must not overlap one already present.
function MemberSubscriptionEditor({memberId}:{memberId:string}) {
  const client=useQueryClient();
  const [planId,setPlanId]=useState('');
  const [startsOn,setStartsOn]=useState(todayInNairobi);
  const [error,setError]=useState('');
  const [success,setSuccess]=useState('');
  const subscriptions=useListSubscriptions({memberId,page:1,pageSize:50});
  const plans=useListMembershipPlans();
  const create=useCreateSubscription();
  const entries=subscriptions.data?.items||[];
  const current=entries.find(s=>s.status==='active') || entries.find(s=>s.status==='scheduled');
  function submit(e:FormEvent){
    e.preventDefault();setError('');setSuccess('');
    if(!planId||!startsOn){setError('Select a plan and start date.');return;}
    create.mutate({memberId,data:{planId,startsOn}}, {
      onSuccess:async()=>{
        setPlanId('');setSuccess('Membership term created successfully.');
        await client.invalidateQueries({queryKey:getListSubscriptionsQueryKey()});
      },
      onError:(err:unknown)=>setError(serverError(err,'Could not create this membership term. Check the dates and try again.')),
    });
  }
  return <section className="op-edit-subscriptions" aria-label="Membership details">
    <div className="op-edit-subscriptions-heading"><h3>Membership details</h3><span>Subscriptions</span></div>
    {subscriptions.isLoading?<p className="op-edit-subscription-muted">Loading membership details…</p>:
      subscriptions.isError?<p className="op-edit-subscription-error">Could not load membership details. <button type="button" onClick={()=>subscriptions.refetch()}>Retry</button></p>:
      current?<div className="op-edit-subscription-current">
        <div><small>{current.status==='active'?'Current membership':'Upcoming membership'}</small><strong>{current.planName}</strong></div>
        <div><small>Price</small><strong>{money(current.monthlyPriceKes)}</strong></div>
        <div><small>Period</small><strong>{date(current.startsOn)} – {date(current.expiresOn)}</strong></div>
        <span className="op-edit-subscription-status">{current.status}</span>
      </div>:<p className="op-edit-subscription-muted">No active or upcoming membership.</p>}
    {entries.length>1&&<p className="op-edit-subscription-muted">{entries.length} membership terms on record. Full history is available under Subscriptions.</p>}
    <form className="op-form op-edit-subscription-form" onSubmit={submit}>
      <h4>Start or renew membership</h4>
      <label>Membership plan<select value={planId} onChange={e=>setPlanId(e.target.value)} required disabled={plans.isLoading||create.isPending}>
        <option value="">Choose an active plan</option>
        {plans.data?.filter(p=>p.isActive).map(p=><option key={p.id} value={p.id}>{p.name} — {money(p.monthlyPriceKes)}</option>)}
      </select></label>
      <label>Membership starts on<input type="date" value={startsOn} onChange={e=>setStartsOn(e.target.value)} required disabled={create.isPending}/></label>
      <p className="op-edit-subscription-muted">Existing terms are preserved. New dates cannot overlap an existing subscription; payments remain separate.</p>
      {error&&<p className="op-edit-subscription-error" role="alert">{error}</p>}
      {success&&<p className="op-edit-subscription-success" role="status">{success}</p>}
      <div className="op-form-actions"><button className="op-button op-primary" type="submit" disabled={create.isPending||plans.isLoading||subscriptions.isLoading}>{create.isPending?'Saving…':'Save membership term'}</button></div>
    </form>
  </section>;
}

export function PlansPage() { return <StaffFrame active="membership-plans"><Plans /></StaffFrame>; }
function Plans() {
  const staff = useGetCurrentStaff(), client = useQueryClient(), [includeInactive, setIncludeInactive] = useState(false), [editing, setEditing] = useState<MembershipPlan | null | false>(false);
  const plans = useListMembershipPlans({ includeInactive: staff.data?.role === 'owner' && includeInactive });
  const create = useCreateMembershipPlan(), update = useUpdateMembershipPlan();
  const [name, setName] = useState(''), [price, setPrice] = useState(''), [active, setActive] = useState(true), [windows, setWindows] = useState<{weekday:number;startsAt:string;endsAt:string}[]>([]), [error, setError] = useState('');
  const owner = staff.data?.role === 'owner';
  function edit(plan?: MembershipPlan) { setEditing(plan || null); setName(plan?.name || ''); setPrice(plan ? String(plan.monthlyPriceKes) : ''); setActive(plan?.isActive ?? true); setWindows(plan?.accessWindows.map(({weekday,startsAt,endsAt}) => ({weekday,startsAt,endsAt})) || []); setError(''); }
  function save(e: FormEvent) { e.preventDefault(); setError(''); if (name.trim().length < 2 || Number(price) < 1 || Number(price) > 1000000) { setError('Add a plan name and a monthly price from KES 1 to KES 1,000,000.'); return; } if (active && windows.length === 0) { setError('Add at least one weekly access window before activating a plan.'); return; } if (new Set(windows.map((window) => window.weekday)).size !== windows.length) { setError('Choose only one access window for each weekday.'); return; } if (windows.some((window) => !window.startsAt || !window.endsAt || window.startsAt >= window.endsAt)) { setError('Each access window must end after it starts.'); return; }
    const data: MembershipPlanInput = { name: name.trim(), monthlyPriceKes: Number(price), isActive: active, accessWindows: windows }; const opts = { onSuccess: async () => { await client.invalidateQueries({ queryKey: getListMembershipPlansQueryKey() }); setEditing(false); }, onError: (error: unknown) => setError(serverError(error, 'Plan could not be saved. Check its access windows and try again.')) };
    if (editing) update.mutate({ planId: editing.id, data }, opts); else create.mutate({ data }, opts);
  }
  const editForm = editing !== false;
  return <><Heading eyebrow="ACCESS & PRICING" title="Membership plans" detail={owner ? 'Set clear monthly prices and the hours each plan can access the gym.' : 'Review currently active membership options.'} action={owner && <button className="op-button op-primary" onClick={() => edit()} data-testid="button-create-plan"><Plus size={16} /> New plan</button>} />
    {owner && <label className="op-toggle"><input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} data-testid="toggle-inactive-plans" /> Include inactive plans</label>}
    {plans.isLoading ? <LoadingRows /> : plans.error ? <Notice error>Plans could not be loaded. <button onClick={() => plans.refetch()} data-testid="button-retry-plans">Try again</button></Notice> : !plans.data?.length ? <div className="op-empty op-panel"><Dumbbell size={25} /><b>No plans are available</b><p>{owner ? 'Create a plan and set the weekly hours members may use it.' : 'Ask the gym owner to publish an active plan.'}</p></div> : <div className="op-plan-list">{plans.data.filter((p) => owner || p.isActive).map((plan) => <article className="op-plan-card" key={plan.id} data-testid={`card-plan-${plan.id}`}><div className="op-plan-top"><span className="op-plan-symbol"><Dumbbell size={18} /></span><div className="op-plan-title"><h2>{plan.name}</h2><Status value={plan.isActive ? 'active' : 'inactive'} /></div><strong>{money(plan.monthlyPriceKes)}<small> / month</small></strong>{owner && <button className="op-icon-button" aria-label={`Edit ${plan.name}`} onClick={() => edit(plan)} data-testid={`button-edit-plan-${plan.id}`}><Pencil size={15} /></button>}</div><div className="op-access-window">{plan.scheduleConfigured ? plan.accessWindows.map((w) => <span key={w.id}>{weekdays[w.weekday]} <b>{w.startsAt}–{w.endsAt}</b></span>) : <span className="op-muted">No access schedule configured</span>}</div></article>)}</div>}
    {editForm && owner && <div className="op-overlay"><section className="op-dialog op-wide-dialog"><button className="op-close" onClick={() => setEditing(false)} aria-label="Close plan form" data-testid="button-close-plan-form"><X size={18} /></button><div className="op-modal-kicker">PLAN SETUP</div><h2>{editing ? 'Edit membership plan' : 'Create membership plan'}</h2><form className="op-form" onSubmit={save}><div className="op-two-fields"><label>Plan name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} data-testid="input-plan-name" /></label><label>Monthly price (KES)<input type="number" min="1" max="1000000" value={price} onChange={(e) => setPrice(e.target.value)} required data-testid="input-plan-price" /></label></div><label className="op-check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} data-testid="toggle-plan-active" /> Active and available to staff</label><div className="op-window-heading"><div><b>Weekly access windows</b><small>Times use your gym’s local time.</small></div><button type="button" className="op-button op-light" onClick={() => setWindows([...windows, {weekday:0, startsAt:'06:00', endsAt:'21:00'}])} data-testid="button-add-access-window"><Plus size={15} /> Add hours</button></div>{windows.map((w, i) => <div className="op-window-row" key={`${i}-${w.weekday}`}><select value={w.weekday} onChange={(e) => setWindows(windows.map((x,j) => j===i ? {...x,weekday:Number(e.target.value)} : x))} data-testid={`select-window-day-${i}`}>{weekdays.map((day,n)=><option value={n} key={day}>{day}</option>)}</select><input type="time" value={w.startsAt} onChange={(e)=>setWindows(windows.map((x,j)=>j===i?{...x,startsAt:e.target.value}:x))} aria-label={`Start time ${i+1}`} data-testid={`input-window-start-${i}`} /><span>to</span><input type="time" value={w.endsAt} onChange={(e)=>setWindows(windows.map((x,j)=>j===i?{...x,endsAt:e.target.value}:x))} aria-label={`End time ${i+1}`} data-testid={`input-window-end-${i}`} /><button type="button" className="op-icon-button" onClick={()=>setWindows(windows.filter((_,j)=>j!==i))} aria-label="Remove access hours" data-testid={`button-remove-window-${i}`}><X size={15}/></button></div>)}{error && <Notice error>{error}</Notice>}<div className="op-form-actions"><button type="button" className="op-button op-light" onClick={()=>setEditing(false)} data-testid="button-cancel-plan">Cancel</button><button className="op-button op-primary" disabled={create.isPending||update.isPending} data-testid="button-save-plan">{create.isPending||update.isPending?'Saving…':'Save plan'}</button></div></form></section></div>}
  </>;
}

export function SubscriptionsPage() { return <StaffFrame active="subscriptions"><Subscriptions /></StaffFrame>; }
function Subscriptions() {
  const client=useQueryClient(), [status,setStatus]=useState(''), [page,setPage]=useState(1), [show,setShow]=useState(false), [memberId,setMemberId]=useState(''), [planId,setPlanId]=useState(''), [start,setStart]=useState(todayInNairobi), [error,setError]=useState('');
  const params={status:status as never || undefined,page,pageSize:10}, query=useListSubscriptions(params), members=useListMembers({page:1,pageSize:100}), plans=useListMembershipPlans(), create=useCreateSubscription();
  function submit(e:FormEvent){e.preventDefault();setError('');if(!memberId||!planId){setError('Choose a member and an active plan.');return;}if(!start){setError('Choose a start date.');return;}create.mutate({memberId,data:{planId,startsOn:start}},{onSuccess:async()=>{await client.invalidateQueries({queryKey:getListSubscriptionsQueryKey()});setShow(false);},onError:(error:unknown)=>setError(serverError(error,'Subscription could not be started. Check the member and plan status.'))});}
  return <><Heading eyebrow="MEMBERSHIPS" title="Subscriptions" detail="Start a fresh one-calendar-month term or renew an existing member." action={<button className="op-button op-primary" onClick={()=>setShow(true)} data-testid="button-start-subscription"><Plus size={16}/> Start or renew</button>}/><div className="op-filter-row"><label>Status <select value={status} onChange={(e)=>{setStatus(e.target.value);setPage(1);}} data-testid="select-subscription-status"><option value="">All statuses</option>{['active','scheduled','expired','cancelled'].map(s=><option key={s}>{s}</option>)}</select></label></div>
    <section className="op-panel">{query.isLoading?<LoadingRows/>:query.error?<Notice error>Subscriptions could not be loaded. <button onClick={()=>query.refetch()} data-testid="button-retry-subscriptions">Try again</button></Notice>:!query.data?.items.length?<div className="op-empty"><CreditCard size={25}/><b>No subscriptions found</b><p>Start a member’s plan to keep their access dates and price on record.</p></div>:<div className="op-table-wrap"><table className="op-table"><thead><tr><th>Member</th><th>Plan</th><th>Term</th><th>Price</th><th>Status</th></tr></thead><tbody>{query.data.items.map(s=><tr key={s.id} data-testid={`row-subscription-${s.id}`}><td><b>{s.memberName}</b><small className="op-cell-sub">{s.memberNumber}</small></td><td>{s.planName}</td><td>{date(s.startsOn)} – {date(s.expiresOn)}</td><td>{money(s.monthlyPriceKes)}</td><td><Status value={s.status}/></td></tr>)}</tbody></table></div>}<Pagination page={page} total={query.data?.total||0} setPage={setPage} testId="subscriptions"/></section>
    {show&&<div className="op-overlay"><section className="op-dialog"><button className="op-close" onClick={()=>setShow(false)} aria-label="Close subscription form" data-testid="button-close-subscription"><X size={18}/></button><div className="op-modal-kicker">ONE CALENDAR MONTH</div><h2>Start or renew a plan</h2><p>Choose the member, active plan and first day. Expiry is calculated by the membership service.</p><form className="op-form" onSubmit={submit}><label>Member<select value={memberId} onChange={e=>setMemberId(e.target.value)} required data-testid="select-subscription-member"><option value="">Choose a member</option>{members.data?.items.map(m=><option value={m.id} key={m.id}>{m.fullName} · {m.memberNumber}</option>)}</select></label><label>Active plan<select value={planId} onChange={e=>setPlanId(e.target.value)} required data-testid="select-subscription-plan"><option value="">Choose a plan</option>{plans.data?.filter(p=>p.isActive).map(p=><option value={p.id} key={p.id}>{p.name} · {money(p.monthlyPriceKes)}</option>)}</select></label><label>Starts on<input type="date" value={start} onChange={e=>setStart(e.target.value)} required data-testid="input-subscription-start"/></label>{error&&<Notice error>{error}</Notice>}<div className="op-form-actions"><button type="button" className="op-button op-light" onClick={()=>setShow(false)} data-testid="button-cancel-subscription">Cancel</button><button className="op-button op-primary" disabled={create.isPending} data-testid="button-save-subscription">{create.isPending?'Saving…':'Save subscription'}</button></div></form></section></div>}</>;
}

function Pagination({page,total,setPage,testId}:{page:number;total:number;setPage:(p:number)=>void;testId:string}){return <div className="op-pagination"><span>Page {page} of {Math.max(1,Math.ceil(total/10))}</span><div><button disabled={page<=1} onClick={()=>setPage(page-1)} data-testid={`button-${testId}-previous`}><ChevronLeft size={16}/> Previous</button><button disabled={page>=Math.ceil(total/10)} onClick={()=>setPage(page+1)} data-testid={`button-${testId}-next`}>Next <ChevronRight size={16}/></button></div></div>}

export function PaymentsPage(){return <StaffFrame active="payments"><Payments/></StaffFrame>}
function Payments(){
  const client=useQueryClient(),[status,setStatus]=useState(''),[page,setPage]=useState(1),[show,setShow]=useState(false),[voiding,setVoiding]=useState(''),[reason,setReason]=useState(''),[error,setError]=useState('');
  const query=useListPayments({status:status as never||undefined,page,pageSize:10}), members=useListMembers({page:1,pageSize:100}), record=useRecordPayment(), voidMutation=useVoidPayment();
  const [member,setMember]=useState(''),[amount,setAmount]=useState(''),[method,setMethod]=useState<PaymentMethod>('cash'),[reference,setReference]=useState(''),[paidAt,setPaidAt]=useState('');
  function submit(e:FormEvent){e.preventDefault();setError('');if(!member||Number(amount)<1||Number(amount)>1000000){setError('Select a member and enter an amount from KES 1 to KES 1,000,000.');return;}if(method==='mpesa_manual'&&!reference.trim()){setError('Enter the M-Pesa transaction reference.');return;}record.mutate({data:{memberId:member,amountKes:Number(amount),method,reference:reference.trim()||null,paidAt:paidAt||null}},{onSuccess:async()=>{await client.invalidateQueries({queryKey:getListPaymentsQueryKey()});setShow(false);setAmount('');setReference('');},onError:(error:unknown)=>setError(serverError(error,'Payment could not be recorded. Confirm the details and try again.'))});}
  function confirmVoid(){if(reason.trim().length<5){setError('Enter a void reason of at least 5 characters.');return;}voidMutation.mutate({paymentId:voiding,data:{reason:reason.trim()}},{onSuccess:async()=>{await client.invalidateQueries({queryKey:getListPaymentsQueryKey()});setVoiding('');setReason('');setError('');},onError:(error:unknown)=>setError(serverError(error,'Payment could not be voided. It may already have changed.'))});}
  return <><Heading eyebrow="CASHIER DESK" title="Payments" detail="Record staff-received payments and keep a clear audit of every entry." action={<button className="op-button op-primary" onClick={()=>{setError('');setShow(true)}} data-testid="button-record-payment"><Plus size={16}/> Record payment</button>}/><Notice>Manual M-Pesa references are staff-entered and are not verified by Safaricom.</Notice><div className="op-filter-row"><label>Status <select value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}} data-testid="select-payment-status"><option value="">All statuses</option><option value="recorded">Recorded</option><option value="voided">Voided</option></select></label></div>
  <section className="op-panel">{query.isLoading?<LoadingRows/>:query.error?<Notice error>Payments could not be loaded. <button onClick={()=>query.refetch()} data-testid="button-retry-payments">Try again</button></Notice>:!query.data?.items.length?<div className="op-empty"><Wallet size={25}/><b>No payment records</b><p>Staff-entered cash, bank and manual M-Pesa entries will appear here.</p></div>:<div className="op-table-wrap"><table className="op-table"><thead><tr><th>Member</th><th>Amount</th><th>Method / reference</th><th>Paid</th><th>Status</th><th/></tr></thead><tbody>{query.data.items.map(p=><tr key={p.id} data-testid={`row-payment-${p.id}`}><td><b>{p.memberName}</b><small className="op-cell-sub">{p.memberNumber} · recorded by {p.recordedByName}</small></td><td><b>{money(p.amountKes)}</b></td><td>{p.method.replaceAll('_',' ')}<small className="op-cell-sub">{p.reference||'No reference'} · {p.verificationStatus.replaceAll('_',' ')}</small></td><td>{time(p.paidAt)}</td><td><Status value={p.status}/></td><td>{p.status==='recorded'&&<button className="op-text-button danger-text" onClick={()=>{setVoiding(p.id);setError('')}} data-testid={`button-void-payment-${p.id}`}>Void</button>}</td></tr>)}</tbody></table></div>}<Pagination page={page} total={query.data?.total||0} setPage={setPage} testId="payments"/></section>
  {show&&<div className="op-overlay"><section className="op-dialog"><button className="op-close" onClick={()=>setShow(false)} aria-label="Close payment form" data-testid="button-close-payment"><X size={18}/></button><div className="op-modal-kicker">STAFF-RECORDED</div><h2>Record a payment</h2><form className="op-form" onSubmit={submit}><label>Member<select value={member} onChange={e=>setMember(e.target.value)} required data-testid="select-payment-member"><option value="">Choose a member</option>{members.data?.items.map(m=><option key={m.id} value={m.id}>{m.fullName} · {m.memberNumber}</option>)}</select></label><label>Amount (KES)<input type="number" min="1" max="1000000" value={amount} onChange={e=>setAmount(e.target.value)} required data-testid="input-payment-amount"/></label><label>Payment method<select value={method} onChange={e=>setMethod(e.target.value as PaymentMethod)} data-testid="select-payment-method"><option value="cash">Cash</option><option value="bank_transfer">Bank transfer</option><option value="mpesa_manual">Manual M-Pesa</option></select></label><label>Reference <span className="op-optional">Optional</span><input value={reference} onChange={e=>setReference(e.target.value)} maxLength={80} data-testid="input-payment-reference"/></label><label>Paid at <span className="op-optional">Optional</span><input type="datetime-local" value={paidAt} onChange={e=>setPaidAt(e.target.value)} data-testid="input-payment-date"/></label>{method==='mpesa_manual'&&<Notice>Manual M-Pesa references are not verified by Safaricom.</Notice>}{error&&<Notice error>{error}</Notice>}<div className="op-form-actions"><button type="button" className="op-button op-light" onClick={()=>setShow(false)} data-testid="button-cancel-payment">Cancel</button><button className="op-button op-primary" disabled={record.isPending} data-testid="button-save-payment">{record.isPending?'Recording…':'Record payment'}</button></div></form></section></div>}
  {voiding&&<div className="op-overlay"><section className="op-dialog"><button className="op-close" onClick={()=>setVoiding('')} aria-label="Close void form" data-testid="button-close-void"><X size={18}/></button><div className="op-modal-kicker">CONFIRM ACTION</div><h2>Void this payment?</h2><p>This keeps the audit record and marks it as void. Add a clear reason.</p><label className="op-standalone-label">Reason<textarea value={reason} onChange={e=>setReason(e.target.value)} minLength={5} maxLength={500} rows={4} data-testid="input-void-reason"/></label>{error&&<Notice error>{error}</Notice>}<div className="op-form-actions"><button className="op-button op-light" onClick={()=>setVoiding('')} data-testid="button-cancel-void">Keep payment</button><button className="op-button op-danger" onClick={confirmVoid} disabled={voidMutation.isPending} data-testid="button-confirm-void">{voidMutation.isPending?'Voiding…':'Confirm void'}</button></div></section></div>}</>;
}

export function AttendancePage(){return <StaffFrame active="attendance"><Attendance/></StaffFrame>}
function Attendance(){
  const client=useQueryClient(),[method,setMethod]=useState<'manual'|'qr'>('manual'),[search,setSearch]=useState(''),[review,setReview]=useState<AttendanceReview|null>(null),[error,setError]=useState(''),[overrideReason,setOverrideReason]=useState(''),[showOverride,setShowOverride]=useState(false);
  const members=useListMembers({search:search||undefined,page:1,pageSize:20}), checkIns=useListCheckIns({page:1,pageSize:20}), lookup=useLookupAttendance(), confirm=useConfirmCheckIn(), override=useOverrideCheckIn();
  const videoRef=useRef<HTMLVideoElement>(null);
  function runLookup(payload:{memberId?:string|null;qrToken?:string|null}){setError('');setReview(null);lookup.mutate({data:payload},{onSuccess:r=>setReview(r),onError:(error:unknown)=>setError(serverError(error,'No matching member was found. Check the number or scan again.'))});}
  useEffect(()=>{if(method!=='qr')return;let active=true;let controls:{stop:()=>void}|undefined;const reader=new BrowserMultiFormatReader();reader.decodeFromVideoDevice(undefined,videoRef.current!, (result)=>{if(result&&active){controls?.stop();runLookup({qrToken:result.getText()});}}).then(c=>{controls=c;if(!active)c.stop();}).catch(()=>setError('Camera could not start. Allow camera access or use manual member search.'));return()=>{active=false;controls?.stop();};},[method]);
  function checkIn(){if(!review)return;confirm.mutate({data:{memberId:review.member.id,confirmed:true,source:method}},{onSuccess:async()=>{setReview(null);await client.invalidateQueries({queryKey:getListCheckInsQueryKey()});},onError:(error:unknown)=>setError(serverError(error,'Check-in was not completed. Review the member and try again.'))});}
  function approve(){if(!review||overrideReason.trim().length<5){setError('Enter a reason of at least 5 characters.');return;}override.mutate({data:{memberId:review.member.id,confirmed:true,source:method,reason:overrideReason.trim()}},{onSuccess:async()=>{setReview(null);setShowOverride(false);setOverrideReason('');await client.invalidateQueries({queryKey:getListCheckInsQueryKey()});},onError:(error:unknown)=>setError(serverError(error,'This restriction could not be approved. Duplicate check-ins cannot be overridden.'))});}
  const allowedRestrictions=review?.restrictions.filter(r=>r.overrideAllowed&&r.code!=='duplicate')||[];
  return <><Heading eyebrow="FRONT DESK" title="Attendance" detail="Review access first. A separate confirmation records every check-in."/><div className="op-attendance-grid"><section className="op-panel op-scan-panel"><div className="op-mode-tabs"><button className={method==='manual'?'selected':''} onClick={()=>{setMethod('manual');setError('')}} data-testid="button-manual-lookup"><Search size={15}/> Find member</button><button className={method==='qr'?'selected':''} onClick={()=>{setMethod('qr');setError('')}} data-testid="button-start-qr-scan"><QrCode size={15}/> Scan QR</button></div>
    {method==='manual'?<><label className="op-search attendance-search"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search member name or number" data-testid="input-attendance-search"/></label>{search&&<div className="op-member-results">{members.data?.items.map(m=><button key={m.id} onClick={()=>runLookup({memberId:m.id})} data-testid={`button-lookup-member-${m.id}`}><span className="op-initials">{m.initials}</span><span><b>{m.fullName}</b><small>{m.memberNumber} · {m.phone}</small></span><ArrowRight size={15}/></button>)}</div>}<p className="op-muted op-small">Choose the correct member to review their current access.</p></>:<div className="op-camera-area"><video ref={videoRef} muted playsInline data-testid="video-qr-camera"/><div className="camera-outline"><span/></div><p>Point the camera at the member’s QR card.</p><button className="op-text-button" onClick={()=>setMethod('manual')} data-testid="button-stop-qr-scan">Stop camera and search manually</button></div>}
    {error&&<Notice error>{error}</Notice>}{review&&<div className="op-review" data-testid="attendance-review"><div className="op-review-head"><span className={`op-review-icon ${review.canCheckIn?'permitted':'restricted'}`}>{review.canCheckIn?<Check size={18}/>:<CircleAlert size={18}/>}</span><div><small>ACCESS REVIEW · {time(review.checkedAt)}</small><h2>{review.member.fullName}</h2><p>{review.member.memberNumber} · {review.member.phone}</p></div></div><div className="op-review-plan"><span>Current plan</span><b>{review.plan?.name||'No active plan'}</b><small>{review.subscription?`${date(review.subscription.startsOn)} – ${date(review.subscription.expiresOn)}`:'No active subscription'}</small></div>{review.restrictions.length>0&&<div className="op-restrictions">{review.restrictions.map((r,i)=><div key={`${r.code}-${i}`}><CircleAlert size={15}/><span><b>{r.message}</b><small>{r.code==='duplicate'?'Duplicate check-in: cannot be overridden':r.overrideAllowed?'Staff approval may be permitted':'Staff approval is not available'}</small></span></div>)}</div>}{review.duplicateCheckInAt&&<Notice error>Duplicate check-in recorded at {time(review.duplicateCheckInAt)}. No override is available.</Notice>}{review.canCheckIn?<button className="op-button op-primary op-full" onClick={checkIn} disabled={confirm.isPending} data-testid="button-confirm-check-in">{confirm.isPending?'Recording check-in…':'Confirm check-in'}</button>:allowedRestrictions.length>0&&!review.duplicateCheckInAt?<>{!showOverride?<button className="op-button op-light op-full" onClick={()=>setShowOverride(true)} data-testid="button-request-override">Approve permitted restriction</button>:<div className="op-override-form"><label>Reason for approval<textarea value={overrideReason} onChange={e=>setOverrideReason(e.target.value)} minLength={5} maxLength={500} rows={3} data-testid="input-override-reason"/></label><div className="op-inline-actions"><button className="op-button op-light" onClick={()=>setShowOverride(false)} data-testid="button-cancel-override">Cancel</button><button className="op-button op-primary" onClick={approve} disabled={override.isPending} data-testid="button-confirm-override">{override.isPending?'Approving…':'Confirm approval'}</button></div></div>}</>:<Notice error>Access is restricted. This restriction cannot be overridden.</Notice>}</div>}
    </section><section className="op-panel op-history"><div className="op-panel-title"><div><span className="op-eyebrow">TODAY AT THE DOOR</span><h2>Attendance history</h2></div><Clock3 size={18}/></div>{checkIns.isLoading?<LoadingRows/>:checkIns.error?<Notice error>Attendance history could not be loaded. <button onClick={()=>checkIns.refetch()} data-testid="button-retry-checkins">Retry</button></Notice>:!checkIns.data?.items.length?<div className="op-empty"><Clock3 size={24}/><b>No check-ins yet</b><p>Completed check-ins appear here.</p></div>:<div className="op-checkin-list">{checkIns.data.items.map(c=><div className="op-checkin-row" key={c.id} data-testid={`row-checkin-${c.id}`}><span className="op-initials">{c.memberName.split(' ').map(x=>x[0]).slice(0,2).join('').toUpperCase()}</span><span className="op-checkin-copy"><b>{c.memberName}</b><small>{c.memberNumber} · {c.source.toUpperCase()} · {c.staffName}</small>{c.wasOverridden&&<small className="op-override-tag">Approved: {c.overrideReason}</small>}</span><time>{time(c.checkedInAt)}</time></div>)}</div>}</section></div></>;
}
