import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ClerkProvider, Show, SignIn, SignUp, useClerk, useAuth } from '@clerk/react';
import { publishableKeyFromHost } from '@clerk/react/internal';
import { shadcn } from '@clerk/themes';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Check, CheckCircle2, CreditCard,
  CalendarDays, ChevronRight, CircleHelp, ClipboardList, Clock3, Dumbbell, ExternalLink,
  Search, Fingerprint, MessageCircle, CircleAlert, Gauge, LoaderCircle, LogOut, MapPin, Menu, Settings2, ShieldCheck,
  SlidersHorizontal, QrCode, Sparkles, UserCog, UsersRound, Wallet, Wifi, X, XCircle,
} from 'lucide-react';
import { Link, Redirect, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import {
  setAuthTokenGetter, customFetch,
  getGetCurrentStaffQueryKey, getGetGymSettingsQueryKey, getHealthCheckQueryKey,
  useBootstrapInitialOwner, useGetCurrentStaff, useGetGymSettings, useHealthCheck, useUpdateGymSettings,
} from '@workspace/api-client-react';
import type { CurrentStaff, GymSettings, GymSettingsUpdate } from '@workspace/api-client-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import { NewGymSignupPage } from '@/pages/NewGymSignupPage';
import { GymImportPage } from '@/pages/GymImportPage';
import '@/pages/gym-import.css';
import { PlatformAdminPage } from '@/pages/platform-admin';
import { AttendancePage, MembersPage, PaymentsPage, PlansPage, SubscriptionsPage } from '@/pages/operations';
import { EventsPage, StaffManagementPage, TrainerMembersPage, WorkoutsPage, WorkspaceOverview } from '@/pages/workspaces';
import { MemberOnboardingPage } from '@/pages/member-onboarding';
import { MemberWorkoutPage } from '@/pages/member-workout';
import './index.css';

const queryClient = new QueryClient();
const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
const clerkPubKey = publishableKeyFromHost(window.location.hostname, import.meta.env.VITE_CLERK_PUBLISHABLE_KEY);
const clerkProxyUrl = import.meta.env.VITE_CLERK_PROXY_URL;

if (!clerkPubKey) throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY in environment.');

function stripBase(path: string) {
  return basePath && path.startsWith(basePath) ? path.slice(basePath.length) || '/' : path;
}

const clerkAppearance = {
  theme: shadcn,
  cssLayerName: 'clerk',
  options: {
    logoPlacement: 'inside' as const,
    logoLinkUrl: basePath || '/',
    logoImageUrl: `${window.location.origin}${basePath}/logo.svg`,
  },
  variables: {
    colorPrimary: '#285d43',
    colorForeground: '#26352d',
    colorMutedForeground: '#68766e',
    colorDanger: '#ad3933',
    colorBackground: '#ffffff',
    colorInput: '#fbfcfb',
    colorInputForeground: '#26352d',
    colorNeutral: '#dce4de',
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: '0.85rem',
  },
  elements: {
    rootBox: 'w-full flex justify-center',
    cardBox: 'bg-white rounded-[22px] w-[440px] max-w-full overflow-hidden shadow-lg',
    card: '!shadow-none !border-0 !bg-transparent !rounded-none',
    footer: '!shadow-none !border-0 !bg-transparent !rounded-none',
    headerTitle: 'text-[#26352d] font-bold tracking-tight',
    headerSubtitle: 'text-[#68766e]',
    socialButtonsBlockButtonText: 'text-[#26352d] font-semibold',
    formFieldLabel: 'text-[#34443a] font-semibold',
    footerActionLink: 'text-[#285d43] font-semibold',
    footerActionText: 'text-[#68766e]',
    dividerText: 'text-[#7a887f]',
    identityPreviewEditButton: 'text-[#285d43]',
    formFieldSuccessText: 'text-[#285d43]',
    alertText: 'text-[#8f312d]',
    logoBox: 'rounded-xl overflow-hidden',
    logoImage: 'object-contain',
    socialButtonsBlockButton: 'border-[#dce4de] hover:bg-[#f4f8f5]',
    formButtonPrimary: 'bg-[#285d43] hover:bg-[#1f4b35] text-white',
    formFieldInput: 'bg-[#fbfcfb] border-[#dce4de] text-[#26352d]',
    footerAction: 'border-t border-[#e7ece8]',
    dividerLine: 'bg-[#e7ece8]',
    alert: 'bg-[#fff4f2] border-[#f0d1cc]',
    otpCodeFieldInput: 'border-[#dce4de]',
    formFieldRow: 'gap-2',
    main: 'gap-5',
  },
};

function errorCode(error: unknown) {
  if (!error || typeof error !== 'object') return '';
  const item = error as { status?: number; code?: string; response?: { status?: number }; message?: string };
  return `${item.status ?? item.response?.status ?? ''} ${item.code ?? ''} ${item.message ?? ''}`.toLowerCase();
}

function isForbidden(error: unknown) {
  const text = errorCode(error);
  return text.includes('403') || text.includes('forbidden') || text.includes('staff_role');
}

function isUnauthorized(error: unknown) {
  const text = errorCode(error);
  return text.includes('401') || text.includes('unauthorized');
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="brand-lockup" aria-label="MyGym Fitness KE home" data-testid="link-brand-home">
      <span className="brand-mark"><Dumbbell size={18} strokeWidth={2.6} /></span>
      {!compact && <span className="brand-type"><strong>MyGym</strong><small>FITNESS KE</small></span>}
    </Link>
  );
}

function ButtonLink({ href, children, variant = 'primary', className = '' }: {
  href: string; children: ReactNode; variant?: 'primary' | 'subtle'; className?: string;
}) {
  return <Link href={href} className={`button ${variant === 'subtle' ? 'button-subtle' : 'button-primary'} ${className}`}>{children}</Link>;
}

/* MYGYM_FICCA_LANDING_V1 */
function HomePage() {
  const [role, setRole] = useState<'owner' | 'receptionist' | 'trainer'>('owner');
  const [billing, setBilling] = useState<'monthly' | 'yearly'>('monthly');
  const [faq, setFaq] = useState(0);
  const roleDetails = {
    owner: { label: 'Owner dashboard', description: 'Track membership health, recorded payments, check-ins, and follow-up priorities.', stats: [['Members', 'Profiles'], ['Attendance', 'Visits'], ['Renewals', 'Due soon'], ['Revenue', 'Recorded']] },
    receptionist: { label: 'Front desk', description: 'Register members, find subscriptions, record payments, and check people in.', stats: [['Members', 'Directory'], ['Check-ins', 'Today'], ['Payments', 'Ledger'], ['Plans', 'Access']] },
    trainer: { label: 'Trainer workspace', description: 'Review member fitness goals, assessments, and assigned workout plans.', stats: [['Members', 'Coaching'], ['Goals', 'Reviewed'], ['Plans', 'Assigned'], ['Progress', 'Tracked']] },
  };
  const questions = [
    ['Do my members need to install an app?', 'No. Members can use secure links to access their onboarding and workout information in a mobile browser. Staff can share supported links through WhatsApp.'],
    ['What do I need to get started?', 'Create an account and complete your gym setup when your gym workspace and owner access have been provisioned. Configure your gym settings and membership plans before adding members.'],
    ['Who sees what?', 'Owners manage the business and staff access. Receptionists handle front-desk operations. Trainers work with fitness assessments and workouts. Permissions are enforced by the backend.'],
    ['How are M-Pesa payments handled?', 'Payments are currently recorded by staff. Automated M-Pesa confirmation and subscription renewals are planned, not yet live.'],
    ['Can I run more than one branch?', 'MyGym is being extended to support separately managed gyms. Multi-gym provisioning and branch-level access are still under development.'],
  ];
  return <>
    <Show when="signed-in"><Redirect to="/dashboard" /></Show>
    <Show when="signed-out">
      <main className="lp2" id="top">
        <header className="lp2-nav lp2-wrap">
          <Link href="/" className="lp2-brand" aria-label="MyGym home"><span className="lp2-brand-symbol">M</span><b>MyGym</b></Link>
          <nav className="lp2-navlinks" aria-label="Landing navigation">
            <a href="#product">Product</a><a href="#dashboards">Dashboards</a><a href="#how-it-works">How it works</a><a href="#pricing">Pricing</a><a href="#questions">Questions</a>
          </nav>
          <div className="lp2-nav-actions"><Link className="lp2-btn lp2-btn-outline" href="/sign-in">Login</Link><Link className="lp2-btn lp2-btn-mint" href="/get-started">Get started</Link></div>
        </header>

        <section className="lp2-hero lp2-wrap" aria-labelledby="lp2-hero-title">
          <div className="lp2-hero-copy"><span className="lp2-bubble lp2-bubble-blue">Owner</span><h1 id="lp2-hero-title">Keep your whole gym organised, from check-in to renewal.</h1><p>MyGym brings memberships, recorded payments, attendance and coaching into one place. Owners, receptionists and trainers each get their own workspace.</p><div className="lp2-hero-actions"><Link href="/get-started" className="lp2-btn lp2-btn-mint lp2-btn-lg">Get started <ArrowRight size={16}/></Link><a href="#dashboards" className="lp2-btn lp2-btn-outline lp2-btn-lg">See the dashboards</a></div><div className="lp2-proof"><span><Check size={15}/> No member app required</span><span><Check size={15}/> Built for gyms in Kenya</span><span><Check size={15}/> Staff access by role</span></div></div>
          <div className="lp2-hero-visual"><span className="lp2-bubble lp2-bubble-violet lp2-tag-front">Front desk</span><div className="lp2-checkin"><div className="lp2-preview-header"><span className="lp2-chip lp2-chip-green">Checked in</span><span>•••</span></div><h3>Morning session</h3><div className="lp2-checkin-people">{[['AK','Achieng Kamau'],['BO','Brian Otieno'],['WM','Wanjiku Mwangi']].map(([initial,name],i)=><div className="lp2-checkin-person" key={initial}><span className={`lp2-circle lp2-circle-${i}`}>{initial}</span><b>{name}</b><span className="lp2-qr-mark"><QrCode size={40} strokeWidth={1.6}/></span><small>QR member access</small></div>)}</div><div className="lp2-checkin-foot"><span className="lp2-mini-avatars"><i>FN</i><i>SK</i><i>LW</i></span><span>Front-desk attendance</span></div></div><div className="lp2-renewal"><span className="lp2-chip lp2-chip-yellow">Due in 3 days</span><h3>Faith's renewal</h3><p>Upcoming membership expiry. Staff can review the subscription and follow up.</p><span className="lp2-renewal-foot"><MessageCircle size={15}/> Follow-up needed</span></div><span className="lp2-bubble lp2-bubble-pink lp2-tag-trainer">Trainer</span></div>
        </section>

        <section className="lp2-roles lp2-wrap" id="product"><div className="lp2-section-intro"><h2>One platform for everyone <span>at the gym</span></h2><p>Each person signs in to the same gym and sees the part that is theirs.</p></div><div className="lp2-role-cards">{[
          {icon:<Gauge size={31}/>,name:'Gym owners',desc:'Revenue, renewals and retention'},
          {icon:<UsersRound size={31}/>,name:'Front desk',desc:'Check-ins, members and payments'},
          {icon:<Dumbbell size={31}/>,name:'Trainers',desc:'Assessments and workout plans'},
          {icon:<Activity size={31}/>,name:'Members',desc:'Secure links and fitness plans'},
          {icon:<Settings2 size={31}/>,name:'Gym groups',desc:'Multi-gym management in development'},
        ].map((x,i)=><article className="lp2-role-card" key={x.name}><span className={`lp2-role-icon lp2-role-icon-${i}`}>{x.icon}</span><h3>{x.name}</h3><p>{x.desc}</p></article>)}</div>
          <div className="lp2-feature"><div className="lp2-feature-copy"><h2>A front desk that keeps the queue moving</h2><ul><li><Check size={16}/> Check members in by QR code or by name</li><li><Check size={16}/> Register members and assign plans</li><li><Check size={16}/> Record payments and review subscription expiry</li><li><Check size={16}/> Keep a clear history of staff operations</li></ul><Link href="/get-started" className="lp2-textlink">Explore MyGym <ArrowRight size={17}/></Link></div><div className="lp2-feature-screen"><div className="lp2-mini-rail"><b>● MyGym</b><span>Overview</span><span>Members</span><strong>Check-ins →</strong><span>Payments</span><span>Settings</span></div><div className="lp2-mini-main"><div className="lp2-mini-search"><Search size={15}/> Search name or phone</div><h3>Check-ins</h3><small>Member attendance overview</small>{[['AK','Achieng Kamau','Checked in'],['BO','Brian Otieno','Active'],['FN','Faith Njeri','Renewal due']].map(([ini,name,status],i)=><div className={`lp2-check-row ${i===0?'lp2-check-highlight':''}`} key={ini}><span className="lp2-circle">{ini}</span><b>{name}</b><small>{status}</small></div>)}</div></div></div>
        </section>

        <section className="lp2-comparison lp2-wrap"><div className="lp2-section-intro"><h2>Running a gym is more <span>than check-ins</span></h2><p>When daily operations live in different places, important work gets missed.</p></div><div className="lp2-compare-grid"><article className="lp2-compare-before"><h3><CircleAlert size={24}/> Without a system</h3>{['A paper register nobody can search','Renewals remembered by whoever is at the desk','Owner, desk and trainers keeping separate notes','More admin every time your gym grows'].map(x=><p key={x}><X size={16}/>{x}</p>)}</article><article className="lp2-compare-after"><h3><CheckCircle2 size={25}/> With MyGym</h3>{['Member, visit and payment records in one place','Upcoming expiries flagged for review','A separate workspace for each staff role','A foundation for multi-gym operations'].map(x=><p key={x}><Check size={16}/>{x}</p>)}</article></div></section>

        <section className="lp2-dashboards" id="dashboards"><div className="lp2-wrap"><div className="lp2-section-intro"><h2>The right dashboard <span>for each role</span></h2><p>Pick a role to see what that person works with every day.</p></div><div className="lp2-tabs" role="tablist" aria-label="Dashboard role">{(['owner','receptionist','trainer'] as const).map(r=><button key={r} type="button" role="tab" aria-selected={role===r} className={role===r?'active':''} onClick={()=>setRole(r)}>{r==='owner'?'Owner':r==='receptionist'?'Receptionist':'Trainer'}</button>)}</div><p className="lp2-dashboard-desc">{roleDetails[role].description}</p><div className="lp2-dashboard-visual"><aside className="lp2-dashboard-rail"><b>m</b><span>⌂</span><span>♙</span><span>▱</span><span>⚙</span></aside><aside className="lp2-dashboard-menu"><strong>Dashboards</strong><span>{roleDetails[role].label}</span><span>Members</span><span>Subscriptions</span><span>Attendance</span><span>Workouts</span><span>Settings</span></aside><div className="lp2-dashboard-canvas"><div className="lp2-dashboard-top"><span><Search size={14}/> Search</span><b>MyGym workspace</b></div><h3>{roleDetails[role].label}</h3><p>Illustrative interface • No live account data</p><div className="lp2-dashboard-statgrid">{roleDetails[role].stats.map(([k,v],i)=><div key={k}><span className={`lp2-stat-dot lp2-stat-dot-${i}`}/><small>{k}</small><b>{v}</b></div>)}</div><div className="lp2-dashboard-bottom"><article><h4>Membership overview</h4><div className="lp2-linegraph"><svg viewBox="0 0 460 150" preserveAspectRatio="none"><path d="M0 115 C60 104 80 80 132 84 S226 50 270 55 S375 23 460 20" fill="none" stroke="#6252DC" strokeWidth="4" strokeLinecap="round"/><path d="M0 138 C100 135 115 121 210 116 S350 100 460 90" fill="none" stroke="#22B87A" strokeWidth="3" strokeDasharray="7 6"/></svg></div></article><article><h4>Needs attention</h4><b>Renewals</b><div className="lp2-attention-bars"><i/><i/><i/></div><p>Upcoming expiry · Attendance follow-up</p></article></div></div></div></div></section>

        <section className="lp2-journey lp2-wrap" id="how-it-works"><div className="lp2-steps">{[['01','Register','Member profile'],['02','Subscribe','Membership and payment'],['03','Check in','QR or staff entry'],['04','Train','Workout support'],['05','Retain','Renewal follow-up']].map(([num,title,desc],i)=><div className="lp2-journey-step" key={num} style={{marginLeft:`${i*10}%`}}><span>{num}</span><div><b>{title}</b><small>{desc}</small></div><ArrowRight size={17}/></div>)}</div><div className="lp2-journey-copy"><h2>From sign-up to a lasting membership</h2><p>The same member record moves through all five stages, so reception, owners and trainers never type the same thing twice.</p><Link href="/get-started" className="lp2-btn lp2-btn-mint lp2-btn-lg">Get started <ArrowRight size={16}/></Link></div></section>

        <section className="lp2-mobile"><div className="lp2-wrap"><div className="lp2-mobile-head"><h2>Coaching and membership, <span>on the member's phone</span></h2><p>Members can open secure onboarding and workout links in their browser. There's no extra app to install.</p></div><div className="lp2-mobile-display"><div className="lp2-mobile-cardstack"><article><ClipboardList size={25}/><div><b>Fitness onboarding</b><p>Goals, experience and preferred workout days.</p></div></article><article><ShieldCheck size={26}/><div><b>Trainer review</b><p>Review and approve suggested training plans.</p></div></article></div><div className="lp2-phone"><div className="lp2-phone-island"/><small>Good morning</small><h3>Achieng</h3><div className="lp2-phone-pass"><QrCode size={53}/><div><b>Membership</b><span>Your secure gym pass</span></div></div><div className="lp2-phone-workout"><b>Today's workout</b><span>Week 2</span>{['Back squat','Bench press','Plank'].map((x,i)=><p key={x}>{x}<small>{i===2?'3 × 45 sec':'4 × 8'}</small></p>)}</div><div className="lp2-phone-note">Your workout plan is ready.</div></div><div className="lp2-mobile-cardstack"><article><Gauge size={26}/><div><b>Progress tracking</b><p>Assessments and reassessments in one history.</p></div></article><article><MessageCircle size={26}/><div><b>Easy sharing</b><p>Secure workout links and WhatsApp click-to-chat.</p></div></article></div></div></div></section>

        <section className="lp2-insights lp2-wrap"><div><h2>See the numbers, and who needs attention</h2><p>Clear figures and follow-up rules you can read, so nothing is left to guesswork.</p><div className="lp2-insight-metrics">{[['Members','Directory'],['Renewals','Due soon'],['Attendance','Last 30 days'],['Follow-ups','At risk']].map(([k,v])=><article key={k}><b>{v}</b><small>{k}</small></article>)}</div></div><div className="lp2-insight-tasks">{[['Renewal due','Review subscriptions before they expire','Subscription'],['No visits in 14 days','Check in with the member','Attendance'],['Declining attendance','Review recent activity','Retention']].map(([h,d,tag],i)=><article key={h}><span className={`lp2-task-icon lp2-task-${i}`}><Clock3 size={21}/></span><div><b>{h}</b><small>{d}</small></div><span className="lp2-task-tag">{tag}</span></article>)}</div></section>

        <section className="lp2-groups lp2-wrap"><div><span className="lp2-chip lp2-chip-yellow">In development</span><h2>One control centre <span>for several gyms</span></h2><p>Built towards an overview for gym groups, while each gym keeps its own records and access controls.</p><ul><li><Check size={16}/> Isolated member records for each gym</li><li><Check size={16}/> Owner assignment and gym activation workflows</li><li><Check size={16}/> Audited support access planned</li></ul></div><div className="lp2-groups-preview"><div className="lp2-groups-head"><b>All gyms</b><span>Illustration</span></div><div className="lp2-mini-search"><Search size={14}/> Search gyms</div>{[['M','MyGym Fitness KE','Existing gym'],['D','DemoFit Studio','Demo environment'],['N','New gym','Setup required']].map(([initial,name,desc])=><div className="lp2-gym-row" key={name}><span>{initial}</span><div><b>{name}</b><small>{desc}</small></div></div>)}</div></section>

        <section className="lp2-pricing lp2-wrap" id="pricing"><div className="lp2-section-intro"><h2>Plans for your gym</h2><p>Platform subscription pricing is being finalised. Membership prices such as Peak and Off-Peak are set by each gym.</p></div><div className="lp2-tabs lp2-billing" role="tablist" aria-label="Billing cycle"><button type="button" role="tab" aria-selected={billing==='monthly'} className={billing==='monthly'?'active':''} onClick={()=>setBilling('monthly')}>Monthly</button><button type="button" role="tab" aria-selected={billing==='yearly'} className={billing==='yearly'?'active':''} onClick={()=>setBilling('yearly')}>Yearly</button></div><p className="lp2-billing-note">{billing==='monthly'?'Monthly subscription rates will be announced.':'Annual subscription rates will be announced.'}</p><div className="lp2-pricing-grid">{[
          {name:'Starter',desc:'For a gym getting organised',items:['Member profiles and plans','QR and front-desk check-ins','Subscription expiry tracking','Owner and receptionist access']},
          {name:'Growth',desc:'For a growing gym team',items:['Everything in Starter','Fitness assessment workflows','Trainer workspace and workouts','Member retention insights']},
          {name:'Multi-gym',desc:'Under development',items:['Separate gym databases','Gym registry and activation','Platform administration','Audited support tooling (planned)']},
        ].map((plan,i)=><article key={plan.name} className={i===1?'lp2-plan-featured':''}><div><h3>{plan.name}</h3><span>{i===2?'In development':'Pricing soon'}</span></div><p>{plan.desc}</p><ul>{plan.items.map(x=><li key={x}><Check size={15}/>{x}</li>)}</ul><Link className={`lp2-btn ${i===1?'lp2-btn-dark':'lp2-btn-outline'}`} href="/get-started">Explore setup <ArrowRight size={15}/></Link></article>)}</div></section>

        <section className="lp2-faq lp2-wrap" id="questions"><div><h2>Questions <span>gym owners ask</span></h2><p>Want to explore the product? Start with a secure account and we'll guide you through available setup options.</p><Link href="/get-started" className="lp2-btn lp2-btn-outline">Get started <ArrowRight size={15}/></Link></div><div className="lp2-faq-list">{questions.map(([q,a],i)=><article key={q} className={faq===i?'open':''}><button type="button" aria-expanded={faq===i} aria-controls={`lp2-faq-answer-${i}`} onClick={()=>setFaq(faq===i?-1:i)}>{q}<span>{faq===i?'×':'+'}</span></button>{faq===i&&<p id={`lp2-faq-answer-${i}`}>{a}</p>}</article>)}</div></section>

        <section className="lp2-final lp2-wrap"><div><h2>Less admin.<br/>More gym.</h2><p>Bring your gym's operations together and set up a workspace that grows with your team.</p><div><Link href="/get-started" className="lp2-btn lp2-btn-dark lp2-btn-lg">Get started <ArrowRight size={15}/></Link><Link href="/sign-in" className="lp2-btn lp2-btn-outline lp2-btn-lg">Already a user? Login</Link></div></div></section>
        <footer className="lp2-footer lp2-wrap"><Link href="/" className="lp2-brand"><span className="lp2-brand-symbol">M</span><b>MyGym</b></Link><nav><a href="#product">Product</a><a href="#dashboards">Dashboards</a><a href="#how-it-works">How it works</a><a href="#pricing">Pricing</a><a href="#questions">Questions</a></nav><span>MyGym Fitness KE · Built for gyms in Kenya.</span></footer>
      </main>
    </Show>
  </>;
}

function AppShell({ staff, children }: { staff: CurrentStaff; children: ReactNode }) {
  const client = useQueryClient();
  const { signOut } = useClerk();
  const [location] = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileNavToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => setMobileNavOpen(false), [location]);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const navigation = document.getElementById('app-navigation');
    const focusable = navigation?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');
    focusable?.[0]?.focus();
    const handleNavigationKeys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileNavOpen(false);
        mobileNavToggle.current?.focus();
        return;
      }
      if (event.key === 'Tab' && focusable?.length) {
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', handleNavigationKeys);
    return () => window.removeEventListener('keydown', handleNavigationKeys);
  }, [mobileNavOpen]);
  const role = staff.role.charAt(0).toUpperCase() + staff.role.slice(1);
  const navigation = staff.role === 'trainer'
    ? [
        { href: '/dashboard', label: 'Overview', Icon: Gauge },
        { href: '/trainer/members', label: 'Fitness members', Icon: UsersRound },
        { href: '/workouts', label: 'Workouts', Icon: ClipboardList },
        { href: '/events', label: 'Events', Icon: CalendarDays },
      ]
    : [
        { href: '/dashboard', label: 'Overview', Icon: Gauge },
        { href: '/members', label: 'Members', Icon: UsersRound },
        { href: '/membership-plans', label: 'Plans', Icon: Dumbbell },
        { href: '/subscriptions', label: 'Subscriptions', Icon: CreditCard },
        { href: '/payments', label: 'Payments', Icon: Wallet },
        { href: '/attendance', label: 'Attendance', Icon: QrCode },
        ...(staff.role === 'owner'
          ? [{ href: '/workouts', label: 'Workouts', Icon: ClipboardList }]
          : []),
        { href: '/events', label: 'Events', Icon: CalendarDays },
        ...(staff.role === 'owner'
          ? [{ href: '/staff', label: 'Staff', Icon: UserCog }]
          : []),
        ...(staff.role === 'owner'
          ? [{ href: '/settings/gym', label: 'Gym settings', Icon: Settings2 }]
          : []),
      ];
  const currentLabel = navigation.find((item) => item.href === location)?.label ?? 'Overview';
  return (
    <div className={`app-frame ${mobileNavOpen ? 'navigation-open' : ''}`}>
      {mobileNavOpen && <button className="mobile-nav-scrim" onClick={() => { setMobileNavOpen(false); mobileNavToggle.current?.focus(); }} aria-label="Close navigation menu" />}
      <aside className={`sidebar ${mobileNavOpen ? 'is-open' : ''}`} id="app-navigation">
        <div className="sidebar-brand"><Brand /></div>
        <div className="workspace-label">WORKSPACE</div>
        <Link href="/access-pending" className="gym-switcher" onClick={() => setMobileNavOpen(false)}><span className="gym-avatar"><Dumbbell size={18} /></span><span><b>Gym operations</b><small>Switch gym</small></span><ChevronRight size={15} /></Link>
        <div className="nav-label">YOUR SPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map(({ href, label, Icon }) => (
            <Link key={href} href={href} onClick={() => setMobileNavOpen(false)} className={`nav-item ${location === href ? 'selected' : ''}`} data-testid={`link-${href.replaceAll('/', '-').replace(/^-/, '')}`}>
              <Icon size={17} /><span>{label}</span>
              {href === '/settings/gym' && <span className="nav-owner">OWNER</span>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="help-card"><div className="help-icon"><CircleHelp size={17} /></div><b>Need a hand?</b><p>Your gym owner can help with access and setup.</p></div>
          <div className="sidebar-user"><span className="staff-avatar">{initials(staff.name)}</span><span className="user-copy"><b>{staff.name || 'Staff member'}</b><small>{role}</small></span><button className="icon-button logout-icon" onClick={() => signOut({ redirectUrl: basePath || '/' })} aria-label="Sign out" data-testid="button-sign-out"><LogOut size={16} /></button></div>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <button
            ref={mobileNavToggle}
            type="button"
            className="mobile-nav-toggle"
            aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={mobileNavOpen}
            aria-controls="app-navigation"
            onClick={() => setMobileNavOpen((open) => !open)}
          >{mobileNavOpen ? <X size={18} /> : <Menu size={18} />}</button>
          <div className="breadcrumbs"><span>MyGym</span><ChevronRight size={14} /><b>{currentLabel}</b></div>
          <div className="topbar-actions"><span className="topbar-status"><span className="status-dot" /> Staff workspace</span><span className="topbar-avatar">{initials(staff.name)}</span></div>
        </header>
        <main className="content-area page-enter">{children}</main>
      </div>
    </div>
  );
}

function initials(name: string) {
  return name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part.charAt(0).toUpperCase()).join('') || 'MG';
}

function LoadingPage() {
  return <div className="loading-page" aria-label="Loading workspace"><div className="loading-brand"><span /><span /><span /></div><div className="skeleton skeleton-title" /><div className="skeleton skeleton-copy" /><div className="skeleton-grid"><div className="skeleton" /><div className="skeleton" /></div></div>;
}

function Notice({ kind = 'error', title, detail, action }: { kind?: 'error' | 'info'; title: string; detail: string; action?: ReactNode }) {
  return <div className={`notice notice-${kind}`} role="status">{kind === 'error' ? <XCircle size={20} /> : <CircleHelp size={20} />}<div><b>{title}</b><p>{detail}</p>{action}</div></div>;
}

function StaffDashboard() {
  const staffQuery = useGetCurrentStaff({ query: { queryKey: getGetCurrentStaffQueryKey() } });
  const healthQuery = useHealthCheck({ query: { queryKey: getHealthCheckQueryKey(), refetchInterval: 60000 } });

  if (staffQuery.isLoading) return <LoadingPage />;
  if (isUnauthorized(staffQuery.error)) return <SessionExpired />;
  if (isForbidden(staffQuery.error)) return <Redirect to="/access-pending" />;
  if (staffQuery.error || !staffQuery.data) return <div className="centered-state"><Notice title="We couldn't load your staff profile" detail="Please check your connection and try again. Your gym details have not been changed." action={<button className="text-action" onClick={() => staffQuery.refetch()} data-testid="button-retry-staff">Try again <ArrowRight size={14} /></button>} /></div>;

  const staff = staffQuery.data;
  if (staff.status === 'inactive') return <AppShell staff={staff}><Notice title="Your staff access is inactive" detail="Please ask your gym owner to reactivate your staff account before continuing." /></AppShell>;

  return (
    <AppShell staff={staff}>
      {healthQuery.isError && <Notice title="Some services may be unavailable" detail="The app could not confirm service health. Your workspace data can still be reviewed." />}
      <WorkspaceOverview staff={staff} />
      <div className="dashboard-footer"><span>Signed in as <b>{staff.email}</b></span><span><ShieldCheck size={14} /> Private staff workspace</span></div>
    </AppShell>
  );
}

function DashboardContent({ staff, settings, health }: { staff: CurrentStaff; settings: GymSettings; health?: string }) {
  const complete = Boolean(settings.gymName?.trim() && settings.timezone);
  const updated = settings.updatedAt ? new Date(settings.updatedAt) : null;
  return (
    <>
      <section className="welcome-band"><div className="welcome-mark"><Sparkles size={19} /></div><div className="welcome-copy"><div className="welcome-meta"><span>{settings.gymName || 'Your gym'}</span><span className="meta-separator">/</span><span>{staff.role}</span></div><h2>{complete ? 'Your foundation is in place.' : 'A few details to set up.'}</h2><p>{complete ? 'Your core gym details are saved and ready for the next milestone.' : 'Add your gym’s name and operating preferences to finish the basics.'}</p></div><div className="welcome-action"><span className={`setup-pill ${complete ? 'setup-done' : ''}`}><i /> {complete ? 'SETUP STARTED' : 'SETUP NEEDED'}</span><Link href="/settings/gym" className="button button-light" data-testid="link-edit-gym-settings">Review settings <ArrowRight size={15} /></Link></div></section>
      <div className="overview-grid">
        <section className="panel gym-panel">
          <div className="panel-heading"><div><span className="small-cap">GYM PROFILE</span><h3>Core details</h3></div><span className="panel-symbol"><Dumbbell size={17} /></span></div>
          <div className="profile-name"><span className="profile-glyph">{(settings.gymName || 'G').slice(0, 1).toUpperCase()}</span><div><b data-testid="text-gym-name">{settings.gymName || 'Gym name not set'}</b><small><MapPin size={13} /> {settings.timezone || 'Time zone not set'}</small></div></div>
          <div className="detail-list">
            <div><span>Local currency</span><b className="currency-value">KES <small>Kenyan shilling</small></b></div>
            <div><span>Settings last updated</span><b>{updated && !Number.isNaN(updated.valueOf()) ? new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', year: 'numeric' }).format(updated) : 'Not available'}</b></div>
          </div>
          <Link href="/settings/gym" className="panel-link" data-testid="link-open-settings">Manage gym details <ArrowRight size={15} /></Link>
        </section>
        <section className="panel setup-panel">
          <div className="panel-heading"><div><span className="small-cap">SETUP CHECKLIST</span><h3>The essentials</h3></div><span className="check-count">{complete ? '2 / 2' : '1 / 2'}</span></div>
          <div className="check-row"><span className={`check-circle ${settings.gymName ? 'checked' : ''}`}>{settings.gymName ? <Check size={13} /> : '1'}</span><span><b>Gym profile</b><small>{settings.gymName ? 'Name saved' : 'Add your gym name'}</small></span><span className={`check-status ${settings.gymName ? 'done' : ''}`}>{settings.gymName ? 'DONE' : 'TO DO'}</span></div>
          <div className="check-row"><span className={`check-circle ${settings.timezone ? 'checked' : ''}`}>{settings.timezone ? <Check size={13} /> : '2'}</span><span><b>Local preferences</b><small>{settings.timezone ? 'Time zone selected' : 'Choose your local time zone'}</small></span><span className={`check-status ${settings.timezone ? 'done' : ''}`}>{settings.timezone ? 'DONE' : 'TO DO'}</span></div>
          <div className="check-row check-later"><span className="check-circle later-check"><Clock3 size={13} /></span><span><b>Peak access hours</b><small>Available with membership plans</small></span><span className="check-status scheduled">LATER</span></div>
          <p className="check-note"><span className="note-stroke" /> Peak-access hours are not configured yet. This will be set in a later membership-plan milestone.</p>
        </section>
      </div>
      <section className="status-strip"><div className="status-strip-main"><span className="service-icon"><Activity size={17} /></span><div><b>Workspace status</b><small>Staff access and gym setup</small></div><span className="status-healthy"><i /> {health ? 'Services operational' : 'Connected'}</span></div><div className="status-person"><span className="status-mini-avatar">{initials(staff.name)}</span><span><b>{staff.name}</b><small>{staff.role.charAt(0).toUpperCase() + staff.role.slice(1)} · {staff.status}</small></span><ArrowUpRight size={16} /></div></section>
    </>
  );
}

function EmptySetup() {
  return <div className="empty-setup"><span className="empty-icon"><Dumbbell size={23} /></span><h2>Your gym setup is waiting</h2><p>There are no gym settings to show yet. Ask the owner to finish the initial setup, then try again.</p><Link href="/settings/gym" className="button button-primary">Open gym settings <ArrowRight size={15} /></Link></div>;
}

function GymSettingsPage() {
  const staffQuery = useGetCurrentStaff({ query: { queryKey: getGetCurrentStaffQueryKey() } });
  if (staffQuery.isLoading) return <LoadingPage />;
  if (isUnauthorized(staffQuery.error)) return <SessionExpired />;
  if (isForbidden(staffQuery.error)) return <Redirect to="/access-pending" />;
  if (staffQuery.error || !staffQuery.data) return <div className="centered-state"><Notice title="Staff access couldn't be confirmed" detail="Please try again. Your settings are unchanged." action={<button className="text-action" onClick={() => staffQuery.refetch()} data-testid="button-retry-settings-staff">Try again <ArrowRight size={14} /></button>} /></div>;
  if (staffQuery.data.role === 'trainer') return <Redirect to="/dashboard" />;
  if (staffQuery.data.status === 'inactive') return <AppShell staff={staffQuery.data}><Notice title="Your staff access is inactive" detail="Please ask your gym owner to reactivate your account." /></AppShell>;
  return <SettingsContent staff={staffQuery.data} />;
}

function SettingsContent({ staff }: { staff: CurrentStaff }) {
  const settingsQuery = useGetGymSettings({ query: { queryKey: getGetGymSettingsQueryKey() } });
  const updateSettings = useUpdateGymSettings();
  const client = useQueryClient();
  const [gymName, setGymName] = useState('');
  const [timezone, setTimezone] = useState('');
  const [duplicateInterval, setDuplicateInterval] = useState('15');
  const [inactiveDays, setInactiveDays] = useState('30');
  const [renewalDays, setRenewalDays] = useState('7');
  const [saved, setSaved] = useState(false);
  const [formError, setFormError] = useState('');

  useEffect(() => {
    if (!settingsQuery.data) return;
    setGymName(settingsQuery.data.gymName);
    setTimezone(settingsQuery.data.timezone);
    setDuplicateInterval(String(settingsQuery.data.attendanceDuplicateIntervalMinutes));
    setInactiveDays(String(settingsQuery.data.inactivityThresholdDays));
    setRenewalDays(String(settingsQuery.data.renewalReminderDaysBefore));
  }, [settingsQuery.data]);

  if (isUnauthorized(settingsQuery.error)) return <SessionExpired />;
  if (isForbidden(settingsQuery.error)) return <AppShell staff={staff}><Notice title="Owner access required" detail="Only the gym owner can change gym configuration. Please contact your owner if a setting needs attention." /></AppShell>;
  if (settingsQuery.isLoading) return <AppShell staff={staff}><LoadingPage /></AppShell>;
  if (settingsQuery.error) return <AppShell staff={staff}><div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> CONFIGURATION</div><h1>Gym settings</h1></div></div><Notice title="We couldn't load gym settings" detail="Your settings are unchanged. Try again or contact your gym owner if the issue continues." action={<button className="text-action" onClick={() => settingsQuery.refetch()} data-testid="button-retry-settings">Try again <ArrowRight size={14} /></button>} /></AppShell>;
  if (!settingsQuery.data) return <AppShell staff={staff}><div className="empty-setup"><span className="empty-icon"><Settings2 size={22} /></span><h2>Gym settings aren't available</h2><p>There are no saved gym settings to edit. Ask your gym owner to complete the initial setup.</p></div></AppShell>;

  const owner = staff.role === 'owner';
  const changed = gymName !== settingsQuery.data.gymName || timezone !== settingsQuery.data.timezone ||
    Number(duplicateInterval) !== settingsQuery.data.attendanceDuplicateIntervalMinutes ||
    Number(inactiveDays) !== settingsQuery.data.inactivityThresholdDays ||
    Number(renewalDays) !== settingsQuery.data.renewalReminderDaysBefore;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(false);
    setFormError('');
    if (!owner) return;
    if (gymName.trim().length < 2 || gymName.trim().length > 120) {
      setFormError('Gym name must be between 2 and 120 characters.');
      return;
    }
    if (!timezone) {
      setFormError('Choose a time zone before saving.');
      return;
    }
    const values = [
      { label: 'Attendance duplicate interval', value: Number(duplicateInterval), min: 1, max: 120 },
      { label: 'Inactivity threshold', value: Number(inactiveDays), min: 1, max: 90 },
      { label: 'Renewal reminder', value: Number(renewalDays), min: 1, max: 30 },
    ];
    const invalid = values.find((item) => !Number.isInteger(item.value) || item.value < item.min || item.value > item.max);
    if (invalid) {
      setFormError(`${invalid.label} must be a whole number from ${invalid.min} to ${invalid.max}.`);
      return;
    }
    const data: GymSettingsUpdate = {
      gymName: gymName.trim(),
      timezone,
      attendanceDuplicateIntervalMinutes: Number(duplicateInterval),
      inactivityThresholdDays: Number(inactiveDays),
      renewalReminderDaysBefore: Number(renewalDays),
    };
    updateSettings.mutate({ data }, {
      onSuccess: async () => {
        await client.invalidateQueries({ queryKey: getGetGymSettingsQueryKey() });
        setSaved(true);
      },
      onError: (error) => setFormError(isUnauthorized(error)
        ? 'Your session has expired. Sign in again to save changes.'
        : isForbidden(error)
          ? 'Only the gym owner can save these settings. Your changes were not saved.'
          : 'Your changes could not be saved. Please try again.'),
    });
  }

  return (
    <AppShell staff={staff}>
      <div className="page-heading settings-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> CONFIGURATION</div><h1>Gym settings</h1><p>Keep the essentials for your gym accurate and close at hand.</p></div><div className="settings-scope"><span className="scope-shield"><ShieldCheck size={16} /></span><span><b>Owner-managed</b><small>Changes apply to this gym</small></span></div></div>
      {!owner && <Notice kind="info" title="View only" detail="Only the gym owner can update these settings. You can review the current configuration below." />}
      {saved && <div className="save-success" role="status"><CheckCircle2 size={18} /><span><b>Settings saved.</b> Your gym details are up to date.</span><button onClick={() => setSaved(false)} aria-label="Dismiss saved message" data-testid="button-dismiss-success"><XCircle size={16} /></button></div>}
      <form className="settings-layout" onSubmit={submit}>
        <div className="settings-form-column">
          <section className="panel form-panel">
            <div className="form-section-heading"><span className="form-section-icon"><Dumbbell size={17} /></span><div><h2>Gym identity</h2><p>The name and local time zone used in your workspace.</p></div><span className="section-number">01</span></div>
            <label className="field-label" htmlFor="gym-name">Gym name <span>Required</span></label>
            <input id="gym-name" className="text-input" value={gymName} onChange={(event) => setGymName(event.target.value)} minLength={2} maxLength={120} disabled={!owner || updateSettings.isPending} placeholder="For example, Umoja Fitness Club" data-testid="input-gym-name" />
            <div className="field-hint">This name appears throughout your staff workspace.</div>
            <label className="field-label field-label-spaced" htmlFor="gym-timezone">Time zone <span>Required</span></label>
            <select id="gym-timezone" className="text-input select-input" value={timezone} onChange={(event) => setTimezone(event.target.value)} disabled={!owner || updateSettings.isPending} data-testid="select-gym-timezone">
              <option value="">Select a time zone</option>
              <option value="Africa/Nairobi">East Africa Time · Nairobi (UTC+03:00)</option>
              <option value="Africa/Kampala">East Africa Time · Kampala (UTC+03:00)</option>
              <option value="Africa/Dar_es_Salaam">East Africa Time · Dar es Salaam (UTC+03:00)</option>
              <option value="Africa/Addis_Ababa">East Africa Time · Addis Ababa (UTC+03:00)</option>
              <option value="Africa/Johannesburg">South Africa Standard Time · Johannesburg (UTC+02:00)</option>
              {timezone && !['Africa/Nairobi', 'Africa/Kampala', 'Africa/Dar_es_Salaam', 'Africa/Addis_Ababa', 'Africa/Johannesburg'].includes(timezone) && <option value={timezone}>{timezone}</option>}
            </select>
            <div className="field-hint">Used to keep operating times consistent for your team.</div>
            <div className="currency-callout"><span className="currency-symbol">KSh</span><span><b>Default currency</b><small>Kenyan shilling (KES) is set for your gym.</small></span><span className="locked-pill"><ShieldCheck size={12} /> FIXED</span></div>
          </section>
          <section className="panel form-panel">
            <div className="form-section-heading"><span className="form-section-icon warm-form-icon"><Clock3 size={17} /></span><div><h2>Operating preferences</h2><p>Small defaults that help keep future records consistent.</p></div><span className="section-number">02</span></div>
            <NumberField id="duplicate-interval" label="Attendance duplicate interval" detail="Ignore repeated check-ins within this many minutes." value={duplicateInterval} min={1} max={120} suffix="minutes" onChange={setDuplicateInterval} disabled={!owner || updateSettings.isPending} testId="input-duplicate-interval" />
            <NumberField id="inactive-days" label="Inactivity threshold" detail="Mark a member as inactive after this many days without a visit." value={inactiveDays} min={1} max={90} suffix="days" onChange={setInactiveDays} disabled={!owner || updateSettings.isPending} testId="input-inactivity-threshold" />
            <NumberField id="renewal-days" label="Renewal reminder" detail="Send a renewal reminder this many days before expiry." value={renewalDays} min={1} max={30} suffix="days before" onChange={setRenewalDays} disabled={!owner || updateSettings.isPending} testId="input-renewal-reminder" />
          </section>
          <section className="later-banner"><span className="later-banner-icon"><Clock3 size={17} /></span><div><b>Peak-access hours come later</b><p>Peak hours are not configured yet. They’ll be set up in a later membership-plan milestone.</p></div><span className="scheduled-pill">NOT CONFIGURED</span></section>
          {formError && <div className="form-error" role="alert"><XCircle size={17} /><span>{formError}</span></div>}
          <div className="form-actions"><span className="autosave-note"><ShieldCheck size={14} /> Only gym owners can save changes</span><button className="button button-primary save-button" type="submit" disabled={!owner || updateSettings.isPending || !changed} data-testid="button-save-gym-settings">{updateSettings.isPending ? <><LoaderCircle size={16} className="spin" /> Saving…</> : <><Check size={16} /> Save changes</>}</button></div>
        </div>
        <aside className="settings-aside">
          <div className="aside-card aside-note"><span className="aside-note-icon"><CircleHelp size={18} /></span><span className="small-cap">A NOTE ON SETUP</span><h3>Start with what matters.</h3><p>These preferences create a dependable base for your gym. You can adjust them as your team’s routines become clearer.</p></div>
          <div className="aside-card access-card"><span className="small-cap">ACCESS</span><div className="access-status"><span className="status-dot" /> Your account is active</div><div className="access-rule" /><div className="access-person"><span className="staff-avatar">{initials(staff.name)}</span><span><b>{staff.name}</b><small>{staff.email}</small></span></div><p>Role <b>{staff.role.charAt(0).toUpperCase() + staff.role.slice(1)}</b></p></div>
          <div className="aside-help"><ExternalLink size={15} /><span>Need to change who can manage settings? Ask your gym owner.</span></div>
        </aside>
      </form>
    </AppShell>
  );
}

function NumberField({ id, label, detail, value, min, max, suffix, onChange, disabled, testId }: {
  id: string; label: string; detail: string; value: string; min: number; max: number; suffix: string; onChange: (value: string) => void; disabled: boolean; testId: string;
}) {
  return <div className="number-row"><div><label className="field-label" htmlFor={id}>{label}</label><p className="number-detail">{detail}</p></div><div className="number-entry"><input id={id} type="number" min={min} max={max} step="1" value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} data-testid={testId} /><span>{suffix}</span></div></div>;
}

type AvailableGym = { id: string; name: string; role: string; environment_kind: string };

function WorkspaceSelection() {
  const client = useQueryClient();
  const [, navigate] = useLocation();
  const [gyms, setGyms] = useState<AvailableGym[] | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);

  async function enter(gym: AvailableGym) {
    // A client-side selection is only a hint; every API request still verifies
    // this Clerk identity's active membership inside the chosen gym database.
    document.cookie = `mygym_gym=${encodeURIComponent(gym.id)}; Path=/api; SameSite=Lax`;
    client.clear();
    navigate('/dashboard');
  }

  useEffect(() => {
    let cancelled = false;
    customFetch<AvailableGym[]>('/api/platform/workspaces/me', { responseType: 'json' })
      .then(async items => {
        if (cancelled) return;
        setError('');
        setGyms(items);
        if (items.length === 1) await enter(items[0]);
      })
      .catch(() => { if (!cancelled) setError('Unable to verify gym access. Please retry.'); });
    return () => { cancelled = true; };
  }, [refresh]);

  if (error) return <main className="pending-page"><section className="pending-card"><h1>Gym selection unavailable</h1><p>{error}</p><button className="button button-primary" onClick={() => {setError('');setRefresh(n => n + 1);}}>Retry</button></section></main>;
  if (gyms === null || gyms.length === 1) return <LoadingPage />;
  if (gyms.length === 0) return <PendingPanel />;
  return <main className="pending-page">
    <header className="pending-nav"><Brand /><span className="pending-secure"><ShieldCheck size={15}/> VERIFIED STAFF WORKSPACES</span></header>
    <section className="pending-card page-enter">
      <div className="pending-icon"><Dumbbell size={23}/></div>
      <span className="small-cap">GYM WORKSPACES</span>
      <h1>Choose your<br/><em>gym.</em></h1>
      <p>Only gyms where your sign-in account has active staff access are listed.</p>
      {gyms.map(gym => <button key={gym.id} type="button" className="button button-primary pending-button"
        onClick={() => enter(gym)} data-testid={`select-gym-${gym.id}`}>
        {gym.name} · {gym.role} <ArrowRight size={16}/>
      </button>)}
    </section>
  </main>;
}

function AccessPendingPage() {
  return <WorkspaceSelection />;
}

function SessionSignOut() {
  const { signOut } = useClerk();
  return <button className="text-action" onClick={() => signOut({ redirectUrl: `${basePath}/sign-in` })} data-testid="button-session-sign-out">Sign out and sign in again <ArrowRight size={14} /></button>;
}

function SessionExpired() {
  return <main className="pending-page"><header className="pending-nav"><Brand /><span className="pending-secure"><ShieldCheck size={15} /> SECURE STAFF ACCESS</span></header><section className="pending-card page-enter"><div className="pending-icon"><ShieldCheck size={23} /></div><span className="small-cap">SESSION CHECK</span><h1>Please sign in<br /><em>again.</em></h1><p>Your gym workspace could not confirm the current sign-in. Sign out and start a fresh session to continue safely.</p><SessionSignOut /></section><div className="pending-bottom"><Brand compact /><span>MyGym Fitness KE <i>·</i> Staff workspace</span></div></main>;
}

function PendingPanel({ staff }: { staff?: CurrentStaff }) {
  const client = useQueryClient();
  const { signOut } = useClerk();
  const [, setLocation] = useLocation();
  const [bootstrapError, setBootstrapError] = useState('');
  const bootstrapOwner = useBootstrapInitialOwner({
    mutation: {
      onSuccess: async () => {
        setBootstrapError('');
        await client.invalidateQueries({ queryKey: getGetCurrentStaffQueryKey() });
        setLocation('/dashboard');
      },
      onError: (error) => {
        const status = errorCode(error);
        if (status.includes('403') || status.includes('forbidden')) {
          setBootstrapError('This account is not authorised to become the first owner. Sign in with the email configured by your gym administrator.');
        } else if (status.includes('409') || status.includes('conflict')) {
          setBootstrapError('An owner or staff account has already been set up. Ask your gym owner to assign your staff access.');
        } else if (status.includes('503') || status.includes('unavailable')) {
          setBootstrapError('First-owner setup is temporarily unavailable. Please try again shortly.');
        } else {
          setBootstrapError('We could not complete first-owner setup. Please try again or contact your gym administrator.');
        }
      },
    },
  });
  return (
    <main className="pending-page">
      <header className="pending-nav"><Brand /><span className="pending-secure"><ShieldCheck size={15} /> SECURE STAFF ACCESS</span></header>
      <div className="pending-card page-enter">
        <div className="pending-icon"><UsersRound size={24} /></div><span className="small-cap">ACCESS REQUEST</span>
        <h1>Your account is<br /><em>almost there.</em></h1>
        <p>You're signed in, but this account doesn't have an assigned staff role for a gym yet. Your gym owner can grant access when they're ready.</p>
        <div className="pending-steps"><span className="pending-step-number">01</span><span><b>Ask your gym owner</b><small>Share the email address you used to sign in.</small></span><ArrowDownRight size={16} /></div>
        <div className="pending-steps"><span className="pending-step-number">02</span><span><b>Come back here</b><small>Once access is assigned, sign in again to continue.</small></span><CheckCircle2 size={16} /></div>
        {staff?.email && <div className="pending-email"><span>Signed in as</span><b>{staff.email}</b></div>}
        <div className="ngs-pending-entry" style={{padding:"17px",border:"1px solid #cce5d5",borderRadius:12,background:"#f1faf4",margin:"18px 0"}}><b>Opening a new gym?</b><p>Create your own gym workspace instead of requesting access to an existing one.</p><Link href="/setup/new-gym" className="button button-primary" data-testid="link-create-new-gym">Register your gym <ArrowRight size={15}/></Link></div>
        <div className="bootstrap-owner">
          <b>Setting up a new gym?</b>
          <p>If your account matches the gym’s configured first-owner email and no staff accounts exist, you can securely initialise the owner account here.</p>
          {bootstrapError && <div className="bootstrap-error" role="alert" data-testid="status-bootstrap-owner-error"><XCircle size={15} /><span>{bootstrapError}</span></div>}
          <button className="button button-primary pending-button" onClick={() => { setBootstrapError(''); bootstrapOwner.mutate(); }} disabled={bootstrapOwner.isPending} data-testid="button-bootstrap-owner">
            {bootstrapOwner.isPending ? <><LoaderCircle size={16} className="spin" /> Setting up…</> : <>Set up first owner account <ArrowRight size={16} /></>}
          </button>
        </div>
        <button className="button button-primary pending-button" onClick={() => signOut({ redirectUrl: basePath || '/' })} data-testid="button-pending-sign-out">Sign out <ArrowRight size={16} /></button>
        <span className="pending-footnote">ACCESS IS MANAGED BY YOUR GYM OWNER</span>
      </div>
      <div className="pending-bottom"><Brand compact /><span>MyGym Fitness KE <i>·</i> Staff workspace</span></div>
    </main>
  );
}

function SignInPage() {
  return <main className="auth-page"><div className="auth-backdrop" /><div className="auth-aside"><Brand /><div><span className="eyebrow"><span className="eyebrow-line" /> FOR KENYAN GYM TEAMS</span><h1>A good gym<br />runs on <em>good people.</em></h1><p>Your staff workspace, ready when you are.</p><div className="auth-aside-foot"><ShieldCheck size={16} /> Secure access for authorised staff</div></div></div><div className="auth-form-area"><Link href="/" className="auth-home-link" data-testid="link-auth-home"><ArrowRight size={15} /> Back to MyGym</Link><SignIn routing="path" path={`${basePath}/sign-in`} signUpUrl={`${basePath}/sign-up`} forceRedirectUrl={`${basePath}/dashboard`} /></div></main>;
}


function PlatformSignInPage() {
  return (
    <>
      <Show when="signed-in">
        <Redirect to="/platform" />
      </Show>
      <Show when="signed-out">
        <main className="auth-page">
          <div className="auth-backdrop" />
          <div className="auth-aside">
            <Brand />
            <div>
              <span className="eyebrow">
                <span className="eyebrow-line" />
                PLATFORM ADMINISTRATION
              </span>
              <h1>One platform.<br /><em>Every gym.</em></h1>
              <p>Secure administration for the MyGym platform.</p>
              <div className="auth-aside-foot">
                <ShieldCheck size={16} />
                Restricted to authorised platform administrators
              </div>
            </div>
          </div>
          <div className="auth-form-area">
            <Link href="/" className="auth-home-link">
              Back to MyGym
            </Link>
            <SignIn
              routing="path"
              path={`${basePath}/platform/sign-in`}
              forceRedirectUrl={`${basePath}/platform`}
            />
          </div>
        </main>
      </Show>
    </>
  );
}

function SignUpPage() {
  return <main className="auth-page"><div className="auth-backdrop" /><div className="auth-aside"><Brand /><div><span className="eyebrow"><span className="eyebrow-line" /> JOIN YOUR GYM TEAM</span><h1>Your next shift<br />starts with <em>a welcome.</em></h1><p>Create an account to get started. Your gym owner will assign your staff access.</p><div className="auth-aside-foot"><ShieldCheck size={16} /> A secure space for gym staff</div></div></div><div className="auth-form-area"><Link href="/" className="auth-home-link" data-testid="link-auth-home"><ArrowRight size={15} /> Back to MyGym</Link><SignUp routing="path" path={`${basePath}/sign-up`} signInUrl={`${basePath}/sign-in`} forceRedirectUrl={`${basePath}/setup`} /></div></main>;
}


// MYGYM_ONBOARDING_CONNECTION_V1
function GetStartedPage() {
  return <main className="mg-onboard-page">
    <header className="mg-onboard-nav"><Brand/><Link href="/sign-in" className="button button-light">Sign in <ArrowRight size={16}/></Link></header>
    <section className="mg-onboard-intro"><span className="small-cap">WELCOME TO MYGYM</span><h1>How will you use <em>MyGym?</em></h1><p>Choose the right path. Your account and permissions stay protected by Clerk and your gym administrator.</p></section>
    <div className="mg-onboard-options">
      <article className="mg-onboard-option"><span className="mg-onboard-icon"><Dumbbell size={23}/></span><h2>I'm setting up a gym</h2><p>Create your account, then configure your gym when the platform administrator has provisioned your gym and assigned you as its owner.</p><Link href="/sign-up" className="button button-primary">Create owner account <ArrowRight size={17}/></Link></article>
      <article className="mg-onboard-option"><span className="mg-onboard-icon"><UsersRound size={23}/></span><h2>I'm joining a gym team</h2><p>Create a staff account and ask the gym owner to grant Receptionist or Trainer access. You won't see another gym's records.</p><Link href="/sign-up" className="button button-light">Create staff account <ArrowRight size={17}/></Link></article>
    </div>
    <p className="mg-onboard-note"><ShieldCheck size={15}/> Creating an account does not create a gym or grant owner permissions.</p>
  </main>;
}

function GymSetupHub() {
  const staff = useGetCurrentStaff({query:{queryKey:getGetCurrentStaffQueryKey()}});
  const settings = useGetGymSettings({query:{queryKey:getGetGymSettingsQueryKey(),enabled:staff.data?.role==='owner'}});
  if (staff.isLoading) return <LoadingPage/>;
  if (isUnauthorized(staff.error)) return <SessionExpired/>;
  if (isForbidden(staff.error)) return <PendingPanel/>;
  if (staff.error || !staff.data) return <main className="centered-state"><Notice title="We couldn't verify your gym access" detail="Please try again. No gym setup has been changed." action={<button className="text-action" onClick={()=>staff.refetch()}>Retry <ArrowRight size={14}/></button>}/></main>;
  if (staff.data.role!=='owner') return <Redirect to="/dashboard"/>;
  if (settings.isLoading) return <LoadingPage/>;
  if (isUnauthorized(settings.error)) return <SessionExpired/>;
  const gymReady=Boolean(settings.data?.gymName?.trim() && settings.data?.timezone);
  return <AppShell staff={staff.data}>
    <div className="mg-setup-heading"><span className="small-cap">GETTING STARTED</span><h1>Make MyGym yours.</h1><p>Complete the essentials using your existing gym settings and membership-plan tools. You can return here any time.</p></div>
    {settings.error && <div className="mg-setup-warning" role="alert">Gym settings couldn't be loaded. Check your connection before continuing.</div>}
    <div className="mg-setup-steps">
      <article className="mg-setup-step"><span className="mg-setup-number">01</span><div><span className="small-cap">GYM PROFILE</span><h2>Name and operating preferences</h2><p>Set your gym name, timezone and attendance defaults.</p><span className={`mg-setup-state ${gymReady?'done':''}`}>{gymReady?'Configured':'Review setup'}</span></div><Link href="/settings/gym" className="button button-light">{gymReady?'Review settings':'Set up gym'} <ArrowRight size={16}/></Link></article>
      <article className="mg-setup-step"><span className="mg-setup-number">02</span><div><span className="small-cap">MEMBERSHIPS</span><h2>Define your membership plans</h2><p>Configure Peak, Off-Peak or other plans and their access windows. Plans are gym-specific.</p></div><Link href="/membership-plans" className="button button-light">Manage plans <ArrowRight size={16}/></Link></article>
      <article className="mg-setup-step"><span className="mg-setup-number">03</span><div><span className="small-cap">TEAM & MEMBERS</span><h2>Bring your team and members in</h2><p>Upload existing member records and subscriptions from CSV or Excel. Invite staff when ready.</p></div><Link href="/setup/import" className="button button-light">Import members <ArrowRight size={16}/></Link></article>
    </div>
    <div className="mg-setup-footer"><span><ShieldCheck size={16}/> Owner-only setup. Changes are saved by the existing MyGym APIs.</span><Link href="/dashboard" className="button button-primary">Go to dashboard <ArrowRight size={17}/></Link></div>
  </AppShell>;
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function ClerkQueryCacheInvalidator() {
  const { addListener } = useClerk();
  const client = useQueryClient();
  useEffect(() => {
    let previous: string | null | undefined;
    const unsubscribe = addListener(({ user }) => {
      const next = user?.id ?? null;
      if (previous !== undefined && previous !== next) client.clear();
      previous = next;
    });
    return unsubscribe;
  }, [addListener, client]);
  return null;
}

function RoutedPages() {
  return <RoutedErrorBoundary><Switch>
    <Route path="/" component={HomePage} />
    <Route path="/get-started" component={GetStartedPage} />
    <Route path="/setup/import"><Show when="signed-in"><GymImportPage /></Show><Show when="signed-out"><Redirect to="/sign-in" /></Show></Route>
    <Route path="/setup"><Show when="signed-in"><GymSetupHub /></Show><Show when="signed-out"><Redirect to="/sign-up" /></Show></Route>
    <Route path="/platform/sign-in/*?" component={PlatformSignInPage} />
    <Route path="/sign-in/*?" component={SignInPage} />
    <Route path="/sign-up/*?" component={SignUpPage} />
    <Route path="/onboarding/:token">{(params) => <MemberOnboardingPage token={params.token} />}</Route>
    <Route path="/my-workout/:token">{(params) => <MemberWorkoutPage token={params.token} />}</Route>
    <Route path="/platform"><Show when="signed-in"><PlatformAdminPage /></Show><Show when="signed-out"><Redirect to="/platform/sign-in" /></Show></Route>
    <Route path="/dashboard"><Show when="signed-in"><StaffDashboard /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/settings/gym"><Show when="signed-in"><GymSettingsPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/members"><Show when="signed-in"><MembersPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/membership-plans"><Show when="signed-in"><PlansPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/subscriptions"><Show when="signed-in"><SubscriptionsPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/payments"><Show when="signed-in"><PaymentsPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/attendance"><Show when="signed-in"><AttendancePage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/trainer/members"><Show when="signed-in"><TrainerMembersPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/workouts"><Show when="signed-in"><WorkoutsPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/events"><Show when="signed-in"><EventsPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/staff"><Show when="signed-in"><StaffManagementPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route path="/setup/new-gym"><Show when="signed-in"><NewGymSignupPage /></Show><Show when="signed-out"><Redirect to="/sign-in" /></Show></Route>
    <Route path="/access-pending"><Show when="signed-in"><AccessPendingPage /></Show><Show when="signed-out"><Redirect to="/" /></Show></Route>
    <Route component={NotFound} />
  </Switch></RoutedErrorBoundary>;
}


function ClerkApiAuthBridge({ children }: { children: ReactNode }) {
  const { isLoaded, getToken } = useAuth();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isLoaded) return;

    setAuthTokenGetter(() => getToken());
    setReady(true);

    return () => {
      setAuthTokenGetter(null);
    };
  }, [isLoaded, getToken]);

  if (!isLoaded || !ready) return <LoadingPage />;

  return <>{children}</>;
}

function ClerkProviderWithRoutes() {
  const [, setLocation] = useLocation();
  return <ClerkProvider
    publishableKey={clerkPubKey}
    proxyUrl={clerkProxyUrl}
    appearance={clerkAppearance}
    signInUrl={`${basePath}/sign-in`}
    signUpUrl={`${basePath}/sign-up`}
    localization={{
      signIn: { start: { title: 'Welcome back', subtitle: 'Sign in to access your gym workspace.' } },
      signUp: { start: { title: 'Create your staff account', subtitle: 'Your gym owner will assign your access.' } },
    }}
    routerPush={(to) => setLocation(stripBase(to))}
    routerReplace={(to) => setLocation(stripBase(to), { replace: true })}
  >
    <ClerkApiAuthBridge>
      <QueryClientProvider client={queryClient}>
      <ClerkQueryCacheInvalidator />
      <TooltipProvider><RoutedPages /><Toaster /></TooltipProvider>
      </QueryClientProvider>
    </ClerkApiAuthBridge>
  </ClerkProvider>;
}

function App() {
  return <WouterRouter base={basePath}><ClerkProviderWithRoutes /></WouterRouter>;
}

export default App;
