import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ClerkProvider, Show, SignIn, SignUp, useClerk, useAuth } from '@clerk/react';
import { publishableKeyFromHost } from '@clerk/react/internal';
import { shadcn } from '@clerk/themes';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Check, CheckCircle2, CreditCard,
  CalendarDays, ChevronRight, CircleHelp, ClipboardList, Clock3, Dumbbell, ExternalLink,
  Fingerprint, Gauge, LoaderCircle, LogOut, MapPin, Menu, Settings2, ShieldCheck,
  SlidersHorizontal, QrCode, Sparkles, UserCog, UsersRound, Wallet, Wifi, X, XCircle,
} from 'lucide-react';
import { Link, Redirect, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import {
  setAuthTokenGetter,
  getGetCurrentStaffQueryKey, getGetGymSettingsQueryKey, getHealthCheckQueryKey,
  useBootstrapInitialOwner, useGetCurrentStaff, useGetGymSettings, useHealthCheck, useUpdateGymSettings,
} from '@workspace/api-client-react';
import type { CurrentStaff, GymSettings, GymSettingsUpdate } from '@workspace/api-client-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
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

function HomePage() {
  return (
    <>
      <Show when="signed-in"><Redirect to="/dashboard" /></Show>
      <Show when="signed-out">
        <main className="landing">
          <header className="landing-nav wrap">
            <Brand />
            <div className="landing-nav-actions">
              <span className="kenya-note"><span className="kenya-dot" /> Built for gyms in Kenya</span>
              <ButtonLink href="/sign-in" variant="subtle">Staff sign in <ArrowRight size={16} /></ButtonLink>
            </div>
          </header>
          <section className="landing-hero wrap">
            <div className="hero-copy page-enter">
              <div className="eyebrow"><span className="eyebrow-line" /> SIMPLE GYM OPERATIONS</div>
              <h1>Run your gym<br /><em>with clarity.</em></h1>
              <p className="hero-description">Members, subscriptions, payments, attendance, workouts and events — one connected workspace for your whole team.</p>
              <div className="hero-actions">
                <ButtonLink href="/sign-in">Sign in to your gym <ArrowRight size={17} /></ButtonLink>
                <span className="secure-note"><ShieldCheck size={15} /> For authorised gym staff</span>
              </div>
              <div className="hero-proof"><div className="proof-line" /><span>Made for the rhythm of local gyms</span></div>
            </div>
            <div className="hero-art" aria-label="Gym operations preview">
              <div className="art-wash" />
              <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
              <div className="art-label"><span className="label-mark" /> YOUR GYM, IN GOOD ORDER</div>
              <div className="preview-card">
                <div className="preview-head"><div><span className="micro-label">ILLUSTRATIVE PRODUCT PREVIEW</span><h3>Owner dashboard</h3></div><span className="live-pill"><i /> Demo</span></div>
                <div className="preview-rule" />
                <div className="preview-setting"><span className="preview-icon"><UsersRound size={16} /></span><div><b>Active memberships</b><small>25 fictional demo members</small></div><b>25</b></div>
                <div className="preview-setting"><span className="preview-icon warm"><Clock3 size={16} /></span><div><b>Renewals & follow-up</b><small>See members needing attention</small></div><span className="later-pill">LIVE</span></div>
                <div className="preview-footer"><span><Wifi size={14} /> Secure staff access</span><span className="foot-arc" /></div>
              </div>
              <div className="art-stamp"><span>MG</span><small>EST. FOR<br />KENYA</small></div>
            </div>
          </section>
          <section className="m8-feature-section wrap" id="features" aria-label="What MyGym can do">
            <div className="m8-section-head"><span className="section-index">THE MYGYM EXPERIENCE</span><h2>Everything your gym needs,
            <em> in one place.</em></h2><p>From your front desk to your coaching floor, keep your people and operations connected.</p></div>
            <div className="m8-feature-grid">
              {[
                { Icon: Gauge, title:'Owner dashboard', desc:'See your gym performance: memberships, recorded revenue and attendance.' },
                { Icon: Activity, title:'Member retention', desc:'Spot renewals, prolonged inactivity and declining visits before follow-ups are missed.' },
                { Icon: QrCode, title:'Daily operations', desc:'Register members, record payments and check people in by QR.' },
                { Icon: Dumbbell, title:'Fitness support', desc:'Review goals and assign trainer-approved workout programs.' },
                { Icon: UsersRound, title:'Member experience', desc:'Share onboarding and workout links via WhatsApp and let members save their plans.' },
              ].map(({Icon,title,desc})=><article key={title} className="m8-feature-card"><span><Icon size={20}/></span><h3>{title}</h3><p>{desc}</p></article>)}
            </div>
          </section>
          <section className="m8-how wrap"><span className="section-index">HOW IT WORKS</span><h2>Simple from day one.</h2><div>{['Register and manage memberships','Record visits and payments','Help trainers deliver personalized programs'].map((s,i)=><article key={s}><b>0{i+1}</b><p>{s}</p></article>)}</div><Link className="button button-primary" href="/sign-in">Sign in to MyGym <ArrowRight size={16}/></Link></section>
          <section className="landing-bottom wrap">
            <div className="landing-bottom-lead"><span className="section-index">01 / THE STARTING POINT</span><h2>One steady place<br />to start from.</h2></div>
            <div className="landing-benefit"><div className="benefit-icon"><Fingerprint size={19} /></div><div><b>Staff-first access</b><p>Your team signs in securely and sees the right workspace for their role.</p></div></div>
            <div className="landing-benefit"><div className="benefit-icon warm-icon"><SlidersHorizontal size={19} /></div><div><b>Practical setup</b><p>Set your gym name, local time zone and a few useful operating defaults.</p></div></div>
            <div className="landing-footnote">MYGYM FITNESS KE <span>·</span> A SIMPLE FOUNDATION FOR YOUR GYM</div>
          </section>
        </main>
      </Show>
    </>
  );
}

function AppShell({ staff, children }: { staff: CurrentStaff; children: ReactNode }) {
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
        <div className="gym-switcher"><span className="gym-avatar"><Dumbbell size={18} /></span><span><b>Gym operations</b><small>Staff workspace</small></span><ChevronRight size={15} /></div>
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

function AccessPendingPage() {
  const staffQuery = useGetCurrentStaff({ query: { queryKey: getGetCurrentStaffQueryKey() } });
  if (staffQuery.isLoading) return <LoadingPage />;
  if (isUnauthorized(staffQuery.error)) return <SessionExpired />;
  if (staffQuery.data && !isForbidden(staffQuery.error)) {
    if (staffQuery.data.status === 'active') return <Redirect to="/dashboard" />;
    return <AppShell staff={staffQuery.data}><Notice title="Your staff access is inactive" detail="Please ask your gym owner to reactivate your account before using the workspace." /></AppShell>;
  }
  return <PendingPanel />;
}

function SessionSignOut() {
  const { signOut } = useClerk();
  return <button className="text-action" onClick={() => signOut({ redirectUrl: `${basePath}/sign-in` })} data-testid="button-session-sign-out">Sign out and sign in again <ArrowRight size={14} /></button>;
}

function SessionExpired() {
  return <main className="pending-page"><header className="pending-nav"><Brand /><span className="pending-secure"><ShieldCheck size={15} /> SECURE STAFF ACCESS</span></header><section className="pending-card page-enter"><div className="pending-icon"><ShieldCheck size={23} /></div><span className="small-cap">SESSION CHECK</span><h1>Please sign in<br /><em>again.</em></h1><p>Your gym workspace could not confirm the current sign-in. Sign out and start a fresh session to continue safely.</p><SessionSignOut /></section><div className="pending-bottom"><Brand compact /><span>MyGym Fitness KE <i>·</i> Staff workspace</span></div></main>;
}

function PendingPanel({ staff }: { staff?: CurrentStaff }) {
  const { signOut } = useClerk();
  const client = useQueryClient();
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
  return <main className="auth-page"><div className="auth-backdrop" /><div className="auth-aside"><Brand /><div><span className="eyebrow"><span className="eyebrow-line" /> FOR KENYAN GYM TEAMS</span><h1>A good gym<br />runs on <em>good people.</em></h1><p>Your staff workspace, ready when you are.</p><div className="auth-aside-foot"><ShieldCheck size={16} /> Secure access for authorised staff</div></div></div><div className="auth-form-area"><Link href="/" className="auth-home-link" data-testid="link-auth-home"><ArrowRight size={15} /> Back to MyGym</Link><SignIn routing="path" path={`${basePath}/sign-in`} signUpUrl={`${basePath}/sign-up`} /></div></main>;
}

function SignUpPage() {
  return <main className="auth-page"><div className="auth-backdrop" /><div className="auth-aside"><Brand /><div><span className="eyebrow"><span className="eyebrow-line" /> JOIN YOUR GYM TEAM</span><h1>Your next shift<br />starts with <em>a welcome.</em></h1><p>Create an account to get started. Your gym owner will assign your staff access.</p><div className="auth-aside-foot"><ShieldCheck size={16} /> A secure space for gym staff</div></div></div><div className="auth-form-area"><Link href="/" className="auth-home-link" data-testid="link-auth-home"><ArrowRight size={15} /> Back to MyGym</Link><SignUp routing="path" path={`${basePath}/sign-up`} signInUrl={`${basePath}/sign-in`} /></div></main>;
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
    <Route path="/sign-in/*?" component={SignInPage} />
    <Route path="/sign-up/*?" component={SignUpPage} />
    <Route path="/onboarding/:token">{(params) => <MemberOnboardingPage token={params.token} />}</Route>
    <Route path="/my-workout/:token">{(params) => <MemberWorkoutPage token={params.token} />}</Route>
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
