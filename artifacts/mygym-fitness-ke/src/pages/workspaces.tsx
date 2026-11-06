import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Redirect } from 'wouter';
import {
  Activity, ArrowRight, CalendarDays, Check, CircleAlert, Clock3, Download,
  Dumbbell, FilePlus2, LoaderCircle, Plus, Search, ShieldCheck, UserCog,
  UsersRound, X,
} from 'lucide-react';
import { customFetch, useGetCurrentStaff } from '@workspace/api-client-react';
import type { CurrentStaff } from '@workspace/api-client-react';
import { StaffFrame } from '@/pages/operations';

type Role = 'owner' | 'receptionist' | 'trainer';
type Assessment = {
  id: string;
  recordedAt: string;
  weightKg: number | null;
  heightCm: number | null;
  bmi: number | null;
  bodyFatPercent: number | null;
  musclePercent: number | null;
  visceralFatLevel: number | null;
};
type TrainerMember = {
  id: string;
  memberNumber: string;
  fullName: string;
  status: string;
  assessmentCount: number;
  latestAssessment: Assessment | null;
};
type Exercise = {
  id: string;
  position: number;
  name: string;
  sets: number;
  repetitions: number | null;
  durationSeconds: number | null;
  restSeconds: number | null;
};
type WorkoutResource = {
  id: string;
  originalFilename: string;
  mediaType: string;
  sizeBytes: number;
  downloadUrl: string;
};
type Workout = {
  id: string;
  name: string;
  goal: string;
  description: string | null;
  goalsSupported: string[];
  minimumExperience: string;
  maximumExperience: string;
  recommendedDaysPerWeek: number;
  expectedSessionMinutes: number;
  equipmentRequirements: string[];
  trainerReviewRequired: boolean;
  status: string;
  exercises: Exercise[];
  resources: WorkoutResource[];
};
type OnboardingProgram = Pick<Workout,
  'id' | 'name' | 'goal' | 'description' | 'recommendedDaysPerWeek' |
  'expectedSessionMinutes' | 'equipmentRequirements' | 'trainerReviewRequired' | 'exercises'
> & { matchReasons: string[] };
type OnboardingReview = {
  memberId: string;
  memberName: string;
  memberNumber: string;
  primaryGoal: string;
  experience: string;
  availableDaysPerWeek: number;
  sessionDurationMinutes: number;
  equipmentPreferences: string[];
  limitations: string | null;
  notes: string | null;
  recommendation: OnboardingProgram | null;
  alternatives: OnboardingProgram[];
  submittedAt: string;
};
type Assignment = {
  id: string;
  programId: string;
  programName: string;
  memberId: string;
  memberNumber: string;
  memberName: string;
  startsOn: string;
  status: string;
  notes: string | null;
};
type EventItem = {
  id: string;
  name: string;
  description: string | null;
  startsAt: string;
  endsAt: string;
  capacity: number;
  instructorStaffId: string | null;
  instructorName: string | null;
  status: string;
  registeredCount: number;
  remainingSlots: number;
  coverUrl: string | null;
};
type EventRegistration = {
  id: string;
  eventId: string;
  memberId: string;
  memberNumber: string;
  memberName: string;
  status: string;
  registeredAt: string;
};
type MemberOption = { id: string; memberNumber: string; fullName: string; status: string };
type StaffMember = {
  id: string;
  name: string;
  email: string;
  role: Role;
  status: 'active' | 'inactive';
  createdAt: string;
};
type Summary = {
  role: Role;
  activeMembers?: number | null;
  newMembersLast30Days?: number | null;
  revenueThisMonthKes?: number | null;
  paymentsThisMonth?: number | null;
  membershipsExpiring: Array<{
    memberId: string;
    memberNumber: string;
    fullName: string;
    expiresOn: string;
    daysRemaining: number;
  }>;
  inactiveMembers?: number | null;
  checkInsToday?: number | null;
  attendanceTrend: Array<{ day: string; checkIns: number }>;
  staffCount?: number | null;
  trainerMemberCount?: number | null;
  recentAssessments?: number | null;
  assignedWorkouts?: number | null;
  upcomingEvents: EventItem[];
};
type ExerciseForm = { name: string; sets: string; repetitions: string; durationSeconds: string; restSeconds: string };
const programGoals = [
  ['build_strength', 'Build strength'], ['lose_weight', 'Lose weight'],
  ['improve_fitness', 'Improve fitness'], ['gain_muscle', 'Gain muscle'],
  ['general_wellness', 'General wellbeing'],
] as const;
const programEquipment = [
  ['bodyweight', 'Bodyweight'], ['dumbbells', 'Dumbbells'],
  ['resistance_bands', 'Resistance bands'], ['barbell', 'Barbell'],
  ['machines', 'Weight machines'], ['cardio_machines', 'Cardio machines'],
] as const;

const request = <T,>(path: string, init: RequestInit = {}) =>
  customFetch<T>(path, { ...init, responseType: 'json' });
const jsonBody = (method: string, value: unknown): RequestInit => ({
  method,
  body: JSON.stringify(value),
});
const nfmt = new Intl.NumberFormat('en-KE');
const fmtDate = (value?: string | null) =>
  value ? new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeZone: 'Africa/Nairobi' }).format(new Date(value)) : '—';
const fmtDateTime = (value?: string | null) =>
  value ? new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Africa/Nairobi' }).format(new Date(value)) : '—';
const localToday = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Africa/Nairobi', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
const localDateTimeInput = (value: string) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Africa/Nairobi', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
};
const serverError = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = (error as { data?: unknown }).data;
    if (data && typeof data === 'object' && 'error' in data && typeof data.error === 'string') return data.error;
  }
  return fallback;
};
const errorNotice = (error: unknown, fallback: string) =>
  error ? serverError(error, fallback) : '';

function LoadingPanel() {
  return <div className="ws-loading"><LoaderCircle size={19} className="spin" /> Loading workspace data…</div>;
}

function WorkspaceHeading({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode;
}) {
  return <header className="ws-heading"><div><span className="ws-eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

function StatCard({ label, value, note, Icon }: {
  label: string; value: string | number; note: string; Icon: typeof Activity;
}) {
  return <article className="ws-stat"><span className="ws-stat-icon"><Icon size={18} /></span><span className="ws-stat-label">{label}</span><b>{value}</b><small>{note}</small></article>;
}

export function WorkspaceOverview({ staff }: { staff: CurrentStaff }) {
  const query = useQuery({
    queryKey: ['workspace-summary', staff.id],
    queryFn: () => request<Summary>('/api/dashboard/summary'),
    staleTime: 30_000,
  });
  if (query.isLoading) return <LoadingPanel />;
  if (query.isError || !query.data) {
    return <div className="ws-error"><CircleAlert size={18} />{errorNotice(query.error, 'Dashboard information could not be loaded. Try refreshing.')}</div>;
  }
  const summary = query.data;
  const firstName = staff.name.split(' ')[0] || 'there';
  const today = new Intl.DateTimeFormat('en-KE', {
    weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Africa/Nairobi',
  }).format(new Date());
  const stats = staff.role === 'owner'
    ? [
        { label: 'Active memberships', value: summary.activeMembers ?? 0, note: 'Current access today', Icon: UsersRound },
        { label: 'New members', value: summary.newMembersLast30Days ?? 0, note: 'Registered in the last 30 days', Icon: Activity },
        { label: 'Recorded revenue', value: summary.revenueThisMonthKes == null ? '—' : `KES ${nfmt.format(summary.revenueThisMonthKes)}`, note: `${summary.paymentsThisMonth ?? 0} recorded payments this month`, Icon: ShieldCheck },
        { label: 'Check-ins today', value: summary.checkInsToday ?? 0, note: 'Gym-local calendar day', Icon: CalendarDays },
        { label: 'Active staff', value: summary.staffCount ?? 0, note: 'Owner, receptionist and trainer accounts', Icon: UserCog },
      ]
    : staff.role === 'receptionist'
      ? [
          { label: 'Check-ins today', value: summary.checkInsToday ?? 0, note: 'Gym-local calendar day', Icon: CalendarDays },
          { label: 'Renewals coming up', value: summary.membershipsExpiring.length, note: 'Within the reminder window', Icon: Clock3 },
          { label: 'Inactive member profiles', value: summary.inactiveMembers ?? 0, note: 'Marked inactive in the member record', Icon: UsersRound },
        ]
      : [
          { label: 'Active member profiles', value: summary.trainerMemberCount ?? 0, note: 'Available for fitness follow-up', Icon: UsersRound },
          { label: 'Assessments recorded', value: summary.recentAssessments ?? 0, note: 'In the last 30 days', Icon: Activity },
          { label: 'Active assignments', value: summary.assignedWorkouts ?? 0, note: 'Assigned or in progress', Icon: Dumbbell },
          { label: 'Upcoming events', value: summary.upcomingEvents.length, note: 'Published gym events', Icon: CalendarDays },
        ];
  const title = staff.role === 'owner' ? 'Your gym at a glance' : staff.role === 'receptionist' ? 'Today’s front desk' : 'Your coaching workspace';
  const intro = staff.role === 'owner'
    ? 'A live view of memberships, recorded payments, attendance and your team.'
    : staff.role === 'receptionist'
      ? 'Quick context for arrivals, renewals and member support.'
      : 'Fitness follow-ups, workout plans and the next events on the calendar.';
  return <div className="ws-page">
    <WorkspaceHeading eyebrow={`${staff.role.toUpperCase()} WORKSPACE`} title={`Good to see you, ${firstName}.`} description={intro} />
    <div className="ws-date-line"><span className="ws-date-dot" />{today}<span>·</span> Figures shown here come from saved gym records.</div>
    <div className={`ws-stat-grid ${staff.role === 'receptionist' ? 'is-frontdesk' : ''}`}>
      {stats.map(({ label, value, note, Icon }) => <StatCard key={label} label={label} value={value} note={note} Icon={Icon} />)}
    </div>
    {staff.role !== 'trainer' && <section className="ws-panel">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">MEMBER FOLLOW-UP</span><h2>Memberships expiring soon</h2></div><Link className="ws-text-link" href="/subscriptions">Open subscriptions <ArrowRight size={15} /></Link></div>
      {summary.membershipsExpiring.length === 0
        ? <p className="ws-empty">No memberships are in the configured reminder window.</p>
        : <div className="ws-table-wrap"><table className="ws-table"><thead><tr><th>Member</th><th>Member number</th><th>Expires</th><th>Time left</th></tr></thead><tbody>
          {summary.membershipsExpiring.map((member) => <tr key={member.memberId}><td>{member.fullName}</td><td>{member.memberNumber}</td><td>{fmtDate(member.expiresOn)}</td><td>{member.daysRemaining === 0 ? 'Today' : `${member.daysRemaining} days`}</td></tr>)}
        </tbody></table></div>}
    </section>}
    {staff.role === 'trainer' && <section className="ws-panel">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">NEXT UP</span><h2>Upcoming published events</h2></div><Link className="ws-text-link" href="/events">Manage events <ArrowRight size={15} /></Link></div>
      {summary.upcomingEvents.length === 0
        ? <p className="ws-empty">There are no published upcoming events yet.</p>
        : <div className="ws-event-list">{summary.upcomingEvents.map((event) => <div className="ws-event-row" key={event.id}><span className="ws-event-icon"><CalendarDays size={17} /></span><span><b>{event.name}</b><small>{fmtDateTime(event.startsAt)}{event.instructorName ? ` · ${event.instructorName}` : ''}</small></span><span className="ws-capacity">{event.registeredCount}/{event.capacity} booked</span></div>)}</div>}
    </section>}
    <div className="ws-quick-links">
      {staff.role === 'owner' && <Link href="/staff"><UserCog size={17} /><span><b>Manage staff access</b><small>Add a verified staff account or update a role</small></span><ArrowRight size={16} /></Link>}
      {staff.role === 'trainer' && <Link href="/trainer/members"><UsersRound size={17} /><span><b>Open fitness members</b><small>Review assessments and record a check-in</small></span><ArrowRight size={16} /></Link>}
      <Link href="/events"><CalendarDays size={17} /><span><b>Gym events</b><small>Create a class or register a member</small></span><ArrowRight size={16} /></Link>
      {staff.role !== 'receptionist' && <Link href="/workouts"><Dumbbell size={17} /><span><b>Workout library</b><small>Prepare a reusable plan for a member</small></span><ArrowRight size={16} /></Link>}
    </div>
  </div>;
}

export function TrainerMembersPage() {
  const client = useQueryClient();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<TrainerMember | null>(null);
  const [measurements, setMeasurements] = useState({
    weightKg: '', heightCm: '', bodyFatPercent: '', musclePercent: '', visceralFatLevel: '',
  });
  const [message, setMessage] = useState('');
  const [formError, setFormError] = useState('');
  const members = useQuery({
    queryKey: ['trainer-members', search],
    queryFn: () => request<TrainerMember[]>(`/api/trainer/members${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  });
  const history = useQuery({
    queryKey: ['fitness-history', selected?.id],
    enabled: Boolean(selected),
    queryFn: () => request<{ items: Assessment[] }>(`/api/members/${selected!.id}/fitness-assessments`),
  });
  const record = useMutation({
    mutationFn: (data: Record<string, number>) => request<Assessment>(
      `/api/members/${selected!.id}/fitness-assessments`,
      jsonBody('POST', data),
    ),
    onSuccess: async () => {
      setMessage('Fitness assessment saved.');
      setFormError('');
      setMeasurements({ weightKg: '', heightCm: '', bodyFatPercent: '', musclePercent: '', visceralFatLevel: '' });
      await Promise.all([
        client.invalidateQueries({ queryKey: ['fitness-history', selected?.id] }),
        client.invalidateQueries({ queryKey: ['trainer-members'] }),
        client.invalidateQueries({ queryKey: ['workspace-summary'] }),
      ]);
    },
    onError: (error) => setFormError(serverError(error, 'Assessment could not be saved.')),
  });

  function submitAssessment(event: FormEvent) {
    event.preventDefault();
    setMessage('');
    setFormError('');
    const body: Record<string, number> = {};
    for (const [key, value] of Object.entries(measurements)) {
      if (value.trim()) body[key] = Number(value);
    }
    if (Object.keys(body).length === 0 || Object.values(body).some((value) => !Number.isFinite(value))) {
      setFormError('Enter at least one valid measurement.');
      return;
    }
    record.mutate(body);
  }

  return <StaffFrame active="trainer-members"><div className="ws-page">
    <WorkspaceHeading eyebrow="TRAINER WORKSPACE" title="Fitness members" description="Review recent measurements and keep a useful fitness history for each member." />
    <div className="ws-toolbar"><label className="ws-search"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name or member number" /></label><span className="ws-muted">Member contact and billing details stay outside this view.</span></div>
    {members.isLoading ? <LoadingPanel /> : members.isError ? <div className="ws-error"><CircleAlert size={18} />{serverError(members.error, 'Members could not be loaded.')}</div> :
      <div className="ws-two-column">
        <section className="ws-panel ws-member-list"><div className="ws-panel-head"><div><span className="ws-eyebrow">MEMBER PROFILES</span><h2>{members.data?.length ?? 0} members shown</h2></div></div>
          {(members.data ?? []).length === 0 ? <p className="ws-empty">No active members match that search.</p> :
            (members.data ?? []).map((member) => <button key={member.id} className={`ws-member-choice ${selected?.id === member.id ? 'is-selected' : ''}`} onClick={() => { setSelected(member); setMessage(''); setFormError(''); }}>
              <span className="ws-member-initial">{member.fullName.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase()}</span>
              <span><b>{member.fullName}</b><small>{member.memberNumber} · {member.assessmentCount} assessments</small></span>
              <span className="ws-member-latest">{member.latestAssessment?.weightKg != null ? `${member.latestAssessment.weightKg} kg` : 'No weight'}</span>
            </button>)}
        </section>
        <section className="ws-panel">
          {!selected ? <div className="ws-empty-state"><UsersRound size={24} /><h2>Choose a member</h2><p>Select a profile to review its recorded fitness measurements.</p></div> :
            <>
              <div className="ws-panel-head"><div><span className="ws-eyebrow">FITNESS PROFILE</span><h2>{selected.fullName}</h2><p>{selected.memberNumber}</p></div><span className="ws-status">{selected.status}</span></div>
              <div className="ws-history">
                {history.isLoading ? <LoadingPanel /> : history.isError ? <div className="ws-error">{serverError(history.error, 'Fitness history could not be loaded.')}</div> :
                  (history.data?.items ?? []).length === 0 ? <p className="ws-empty">No fitness assessments have been recorded yet.</p> :
                    (history.data?.items ?? []).map((item) => <div className="ws-assessment" key={item.id}><div><b>{fmtDate(item.recordedAt)}</b><small>Recorded {fmtDateTime(item.recordedAt)}</small></div><div className="ws-measurements">{item.weightKg != null && <span>{item.weightKg} kg</span>}{item.heightCm != null && <span>{item.heightCm} cm</span>}{item.bmi != null && <span>BMI {item.bmi}</span>}{item.bodyFatPercent != null && <span>{item.bodyFatPercent}% body fat</span>}{item.musclePercent != null && <span>{item.musclePercent}% muscle</span>}{item.visceralFatLevel != null && <span>Visceral {item.visceralFatLevel}</span>}</div></div>)}
              </div>
              <form className="ws-form ws-assessment-form" onSubmit={submitAssessment}>
                <h3>Record assessment</h3><p>Only enter measurements collected for this visit.</p>
                <div className="ws-field-grid">
                  {([
                    ['weightKg', 'Weight (kg)', '0.1'],
                    ['heightCm', 'Height (cm)', '0.1'],
                    ['bodyFatPercent', 'Body fat (%)', '0.1'],
                    ['musclePercent', 'Muscle (%)', '0.1'],
                    ['visceralFatLevel', 'Visceral fat level', '1'],
                  ] as const).map(([key, label, step]) => <label className="ws-field" key={key}>{label}<input type="number" min="0.1" step={step} value={measurements[key]} onChange={(event) => setMeasurements({ ...measurements, [key]: event.target.value })} /></label>)}
                </div>
                {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
                {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
                <button className="ws-button" disabled={record.isPending}>{record.isPending ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />} Save assessment</button>
              </form>
            </>}
        </section>
      </div>}
  </div></StaffFrame>;
}

const blankExercise = (): ExerciseForm => ({
  name: '', sets: '3', repetitions: '10', durationSeconds: '', restSeconds: '60',
});

function OnboardingReviewQueue({ programs }: { programs: Workout[] }) {
  const client = useQueryClient();
  const [selectedPrograms, setSelectedPrograms] = useState<Record<string, string>>({});
  const [startDates, setStartDates] = useState<Record<string, string>>({});
  const [trainerNotes, setTrainerNotes] = useState<Record<string, string>>({});
  const [safetyConfirmed, setSafetyConfirmed] = useState<Record<string, boolean>>({});
  const [formError, setFormError] = useState('');
  const [message, setMessage] = useState('');
  const reviews = useQuery({
    queryKey: ['member-onboarding-reviews'],
    queryFn: () => request<OnboardingReview[]>('/api/onboarding/reviews'),
  });
  useEffect(() => {
    if (!reviews.data) return;
    setSelectedPrograms((current) => {
      const next = { ...current };
      for (const item of reviews.data ?? []) {
        if (!(item.memberId in next) && item.recommendation) next[item.memberId] = item.recommendation.id;
      }
      return next;
    });
    setStartDates((current) => {
      const next = { ...current };
      for (const item of reviews.data ?? []) if (!(item.memberId in next)) next[item.memberId] = localToday();
      return next;
    });
  }, [reviews.data]);
  const assign = useMutation({
    mutationFn: ({ item, programId }: { item: OnboardingReview; programId: string }) =>
      request(`/api/onboarding/reviews/${item.memberId}/assign`, jsonBody('POST', {
        programId,
        startsOn: startDates[item.memberId] || localToday(),
        notes: trainerNotes[item.memberId]?.trim() || null,
      })),
    onSuccess: async () => {
      setMessage('Trainer review saved and the final program assigned.');
      setFormError('');
      await Promise.all([
        client.invalidateQueries({ queryKey: ['member-onboarding-reviews'] }),
        client.invalidateQueries({ queryKey: ['workout-assignments'] }),
        client.invalidateQueries({ queryKey: ['workspace-summary'] }),
      ]);
    },
    onError: (error) => setFormError(serverError(error, 'The program could not be assigned. Please review the member and try again.')),
  });
  function submit(item: OnboardingReview) {
    const programId = selectedPrograms[item.memberId];
    const program = programs.find((entry) => entry.id === programId);
    if (!program) {
      setFormError('Choose an active saved program before assigning.');
      return;
    }
    if ((item.limitations || program.trainerReviewRequired) && !safetyConfirmed[item.memberId]) {
      setFormError('Confirm that you reviewed the member-reported limitation or trainer-review requirement first.');
      return;
    }
    setFormError('');
    setMessage('');
    assign.mutate({ item, programId });
  }

  return <section className="ws-panel ws-onboarding-queue" aria-label="New member workout review queue">
    <div className="ws-panel-head"><div><span className="ws-eyebrow">TRAINER REVIEW QUEUE</span><h2>New member recommendations</h2><p>Review every suggestion before assigning a workout.</p></div><span className="ws-queue-count">{reviews.data?.length ?? '—'} awaiting</span></div>
    {reviews.isLoading ? <LoadingPanel /> : reviews.isError ? <div className="ws-error"><CircleAlert size={18} />{serverError(reviews.error, 'The trainer review queue could not be loaded.')}</div> :
      !reviews.data?.length ? <p className="ws-empty">No new member recommendations are waiting for review.</p> :
        <div className="ws-review-list">{reviews.data.map((item) => {
          const chosen = programs.find((program) => program.id === selectedPrograms[item.memberId]);
          const needsConfirmation = Boolean(item.limitations || chosen?.trainerReviewRequired);
          return <article className="ws-review-card" key={item.memberId}>
            <div className="ws-review-head"><div><span className="ws-eyebrow">NEW MEMBER · {item.memberNumber}</span><h3>{item.memberName}</h3></div><time>{fmtDateTime(item.submittedAt)}</time></div>
            <div className="ws-review-facts">
              <span><b>Goal</b>{item.primaryGoal.replaceAll('_', ' ')}</span>
              <span><b>Experience</b>{item.experience}</span>
              <span><b>Availability</b>{item.availableDaysPerWeek} days · up to {item.sessionDurationMinutes} min/session</span>
              <span><b>Equipment</b>{item.equipmentPreferences.length ? item.equipmentPreferences.map((value) => value.replaceAll('_', ' ')).join(', ') : 'Not specified'}</span>
            </div>
            {item.recommendation ? <div className="ws-review-suggestion"><b>Saved program suggested: {item.recommendation.name}</b><p>{item.recommendation.goal} · {item.recommendation.recommendedDaysPerWeek} days/week · {item.recommendation.expectedSessionMinutes} minutes/session</p><small>Exercises: {item.recommendation.exercises.map((exercise) => exercise.name).join(', ') || 'Ask the member and gym team to review the template details.'}</small>{item.alternatives.length > 0 && <small>Other matching templates: {item.alternatives.map((program) => program.name).join(', ')}</small>}</div> :
              <div className="ws-review-no-match"><CircleAlert size={16} /> No saved program matches every answer. Review the member's details and choose a suitable active program or create one first.</div>}
            {item.limitations && <div className="ws-review-limitation"><b>Member-reported limitation</b><p>{item.limitations}</p><small>Discuss this with the member in person; the system deliberately did not generate a workout suggestion.</small></div>}
            {item.notes && <div className="ws-review-member-note"><b>Member note</b><p>{item.notes}</p></div>}
            <div className="ws-review-assign">
              <label className="ws-field">Final program
                <select value={selectedPrograms[item.memberId] ?? ''} onChange={(event) => setSelectedPrograms((current) => ({ ...current, [item.memberId]: event.target.value }))}>
                  <option value="">Choose an active saved program</option>{programs.map((program) => <option key={program.id} value={program.id}>{program.name} · {program.recommendedDaysPerWeek} days/week</option>)}
                </select>
              </label>
              <label className="ws-field">Starts on<input type="date" value={startDates[item.memberId] ?? localToday()} onChange={(event) => setStartDates((current) => ({ ...current, [item.memberId]: event.target.value }))} /></label>
              <label className="ws-field">Trainer note <span className="ws-muted">(optional)</span><input value={trainerNotes[item.memberId] ?? ''} maxLength={1000} onChange={(event) => setTrainerNotes((current) => ({ ...current, [item.memberId]: event.target.value }))} placeholder="Coaching context" /></label>
            </div>
            {needsConfirmation && <label className="ws-review-confirm"><input type="checkbox" checked={Boolean(safetyConfirmed[item.memberId])} onChange={(event) => setSafetyConfirmed((current) => ({ ...current, [item.memberId]: event.target.checked }))} /><span>I reviewed the member's reported limitation or the program's trainer-review flag before assigning.</span></label>}
            <button className="ws-button" disabled={assign.isPending || !programs.length || (needsConfirmation && !safetyConfirmed[item.memberId])} onClick={() => submit(item)}>{assign.isPending ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />} Approve &amp; assign final program</button>
          </article>;
        })}</div>}
    {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
    {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
  </section>;
}

export function WorkoutsPage() {
  const client = useQueryClient();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editing, setEditing] = useState<Workout | null>(null);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [description, setDescription] = useState('');
  const [goalsSupported, setGoalsSupported] = useState<string[]>([]);
  const [minimumExperience, setMinimumExperience] = useState('beginner');
  const [maximumExperience, setMaximumExperience] = useState('advanced');
  const [recommendedDaysPerWeek, setRecommendedDaysPerWeek] = useState('3');
  const [expectedSessionMinutes, setExpectedSessionMinutes] = useState('45');
  const [equipmentRequirements, setEquipmentRequirements] = useState<string[]>([]);
  const [trainerReviewRequired, setTrainerReviewRequired] = useState(false);
  const [exerciseForms, setExerciseForms] = useState<ExerciseForm[]>([blankExercise()]);
  const [selectedProgram, setSelectedProgram] = useState('');
  const [memberSearch, setMemberSearch] = useState('');
  const [selectedMember, setSelectedMember] = useState<MemberOption | null>(null);
  const [startsOn, setStartsOn] = useState(localToday());
  const [assignmentNotes, setAssignmentNotes] = useState('');
  const [formError, setFormError] = useState('');
  const [message, setMessage] = useState('');
  const programs = useQuery({
    queryKey: ['workout-programs', includeArchived],
    queryFn: () => request<Workout[]>(`/api/workouts${includeArchived ? '?includeArchived=true' : ''}`),
  });
  const assignments = useQuery({
    queryKey: ['workout-assignments'],
    queryFn: () => request<Assignment[]>('/api/workout-assignments'),
  });
  const memberResults = useQuery({
    queryKey: ['workout-member-search', memberSearch],
    enabled: memberSearch.trim().length > 0,
    queryFn: () => request<MemberOption[]>(`/api/events/members?search=${encodeURIComponent(memberSearch.trim())}`),
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['workout-programs'] }),
      client.invalidateQueries({ queryKey: ['workout-assignments'] }),
      client.invalidateQueries({ queryKey: ['workspace-summary'] }),
    ]);
  };
  const saveProgram = useMutation({
    mutationFn: (payload: object) => request<Workout>(
      editing ? `/api/workouts/${editing.id}` : '/api/workouts',
      jsonBody(editing ? 'PATCH' : 'POST', payload),
    ),
    onSuccess: async () => {
      setMessage(editing ? 'Workout template updated.' : 'Workout template created.');
      setFormError('');
      clearEditor();
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Workout template could not be saved.')),
  });
  const assign = useMutation({
    mutationFn: () => request<Assignment>(
      `/api/workouts/${selectedProgram}/assignments`,
      jsonBody('POST', {
        memberId: selectedMember!.id,
        startsOn,
        notes: assignmentNotes.trim() || null,
      }),
    ),
    onSuccess: async () => {
      setMessage('Workout assigned to the member.');
      setFormError('');
      setSelectedMember(null);
      setMemberSearch('');
      setAssignmentNotes('');
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Workout assignment could not be saved.')),
  });
  const updateProgram = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: object }) =>
      request<Workout>(`/api/workouts/${id}`, jsonBody('PATCH', payload)),
    onSuccess: refresh,
    onError: (error) => setFormError(serverError(error, 'Workout template could not be updated.')),
  });
  const updateAssignment = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      request<Assignment>(`/api/workout-assignments/${id}`, jsonBody('PATCH', { status })),
    onSuccess: refresh,
    onError: (error) => setFormError(serverError(error, 'Assignment could not be updated.')),
  });
  const uploadResource = useMutation({
    mutationFn: async ({ programId, file }: { programId: string; file: File }) =>
      customFetch<WorkoutResource>(`/api/workouts/${programId}/resources`, {
        method: 'POST',
        body: file,
        headers: {
          'content-type': 'application/octet-stream',
          'x-file-name': encodeURIComponent(file.name),
        },
        responseType: 'json',
      }),
    onSuccess: async () => {
      setMessage('Private resource uploaded.');
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Resource could not be uploaded.')),
  });

  function clearEditor() {
    setEditing(null);
    setName('');
    setGoal('');
    setDescription('');
    setGoalsSupported([]);
    setMinimumExperience('beginner');
    setMaximumExperience('advanced');
    setRecommendedDaysPerWeek('3');
    setExpectedSessionMinutes('45');
    setEquipmentRequirements([]);
    setTrainerReviewRequired(false);
    setExerciseForms([blankExercise()]);
  }
  function editProgram(program: Workout) {
    setEditing(program);
    setName(program.name);
    setGoal(program.goal);
    setDescription(program.description ?? '');
    setGoalsSupported(program.goalsSupported ?? []);
    setMinimumExperience(program.minimumExperience ?? 'beginner');
    setMaximumExperience(program.maximumExperience ?? 'advanced');
    setRecommendedDaysPerWeek(String(program.recommendedDaysPerWeek ?? 3));
    setExpectedSessionMinutes(String(program.expectedSessionMinutes ?? 45));
    setEquipmentRequirements(program.equipmentRequirements ?? []);
    setTrainerReviewRequired(program.trainerReviewRequired ?? false);
    setExerciseForms(program.exercises.map((exercise) => ({
      name: exercise.name,
      sets: String(exercise.sets),
      repetitions: exercise.repetitions == null ? '' : String(exercise.repetitions),
      durationSeconds: exercise.durationSeconds == null ? '' : String(exercise.durationSeconds),
      restSeconds: exercise.restSeconds == null ? '' : String(exercise.restSeconds),
    })));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function submitProgram(event: FormEvent) {
    event.preventDefault();
    setFormError('');
    setMessage('');
    if (exerciseForms.some((exercise) => !exercise.name.trim() || (!exercise.repetitions && !exercise.durationSeconds))) {
      setFormError('Each exercise needs a name and either repetitions or a duration.');
      return;
    }
    if (!goalsSupported.length) {
      setFormError('Choose at least one goal so this saved program can be matched safely.');
      return;
    }
    if (['beginner', 'intermediate', 'advanced'].indexOf(minimumExperience) > ['beginner', 'intermediate', 'advanced'].indexOf(maximumExperience)) {
      setFormError('Minimum experience cannot be higher than maximum experience.');
      return;
    }
    const exercises = exerciseForms.map((exercise) => ({
      name: exercise.name.trim(),
      sets: Number(exercise.sets),
      repetitions: exercise.repetitions ? Number(exercise.repetitions) : null,
      durationSeconds: exercise.durationSeconds ? Number(exercise.durationSeconds) : null,
      restSeconds: exercise.restSeconds ? Number(exercise.restSeconds) : null,
    }));
    saveProgram.mutate({
      name: name.trim(),
      goal: goal.trim(),
      description: description.trim() || null,
      goalsSupported,
      minimumExperience,
      maximumExperience,
      recommendedDaysPerWeek: Number(recommendedDaysPerWeek),
      expectedSessionMinutes: Number(expectedSessionMinutes),
      equipmentRequirements,
      trainerReviewRequired,
      exercises,
    });
  }
  function submitAssignment(event: FormEvent) {
    event.preventDefault();
    setFormError('');
    if (!selectedProgram || !selectedMember) {
      setFormError('Choose an active template and a member before assigning.');
      return;
    }
    assign.mutate();
  }

  return <StaffFrame active="workouts"><div className="ws-page">
    <WorkspaceHeading eyebrow="TRAINING LIBRARY" title="Workout plans" description="Build reusable programs, attach private coaching resources and assign plans to members." />
    <OnboardingReviewQueue programs={(programs.data ?? []).filter((item) => item.status === 'active')} />
    <section className="ws-panel">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">{editing ? 'EDIT TEMPLATE' : 'WORKOUT DESIGN'}</span><h2>{editing ? `Update ${editing.name}` : 'Create a workout template'}</h2></div>{editing && <button className="ws-quiet-button" onClick={clearEditor}><X size={15} /> Cancel edit</button>}</div>
      <form className="ws-form" onSubmit={submitProgram}>
        <div className="ws-field-grid ws-three-columns">
          <label className="ws-field">Template name<input required minLength={2} maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Strength foundation" /></label>
          <label className="ws-field">Training goal<input required minLength={2} maxLength={200} value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="Build full-body strength" /></label>
          <label className="ws-field">Notes<input maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Optional coaching notes" /></label>
        </div>
        <section className="ws-match-metadata" aria-label="Program matching details">
          <div><span className="ws-eyebrow">MEMBER MATCHING</span><h3>Who this saved program is for</h3><p>Only active programs with matching details can appear as member suggestions.</p></div>
          <fieldset className="ws-meta-options"><legend>Goals supported</legend><div>{programGoals.map(([value, label]) => <label key={value}><input type="checkbox" checked={goalsSupported.includes(value)} onChange={() => setGoalsSupported((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])} /><span>{label}</span></label>)}</div></fieldset>
          <div className="ws-field-grid ws-three-columns">
            <label className="ws-field">Minimum experience<select value={minimumExperience} onChange={(event) => setMinimumExperience(event.target.value)}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
            <label className="ws-field">Maximum experience<select value={maximumExperience} onChange={(event) => setMaximumExperience(event.target.value)}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
            <label className="ws-field">Training days each week<input type="number" min="1" max="7" value={recommendedDaysPerWeek} onChange={(event) => setRecommendedDaysPerWeek(event.target.value)} /></label>
            <label className="ws-field">Expected session length (minutes)<input type="number" min="15" max="240" value={expectedSessionMinutes} onChange={(event) => setExpectedSessionMinutes(event.target.value)} /></label>
          </div>
          <fieldset className="ws-meta-options"><legend>Equipment required</legend><div>{programEquipment.map(([value, label]) => <label key={value}><input type="checkbox" checked={equipmentRequirements.includes(value)} onChange={() => setEquipmentRequirements((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])} /><span>{label}</span></label>)}</div><small>Leave all unchecked if no specific equipment is needed.</small></fieldset>
          <label className="ws-meta-review"><input type="checkbox" checked={trainerReviewRequired} onChange={(event) => setTrainerReviewRequired(event.target.checked)} /><span><b>Trainer review required before assignment</b><small>Use this for programs that need an in-person suitability check.</small></span></label>
        </section>
        <div className="ws-exercise-editor">
          {exerciseForms.map((exercise, index) => <div className="ws-exercise-row" key={index}>
            <b className="ws-exercise-index">{String(index + 1).padStart(2, '0')}</b>
            <label className="ws-field">Exercise<input required value={exercise.name} onChange={(event) => setExerciseForms(exerciseForms.map((item, i) => i === index ? { ...item, name: event.target.value } : item))} placeholder="Goblet squat" /></label>
            <label className="ws-field">Sets<input required type="number" min="1" max="50" value={exercise.sets} onChange={(event) => setExerciseForms(exerciseForms.map((item, i) => i === index ? { ...item, sets: event.target.value } : item))} /></label>
            <label className="ws-field">Reps<input type="number" min="1" max="1000" value={exercise.repetitions} onChange={(event) => setExerciseForms(exerciseForms.map((item, i) => i === index ? { ...item, repetitions: event.target.value } : item))} placeholder="10" /></label>
            <label className="ws-field">Duration (sec)<input type="number" min="1" max="86400" value={exercise.durationSeconds} onChange={(event) => setExerciseForms(exerciseForms.map((item, i) => i === index ? { ...item, durationSeconds: event.target.value } : item))} placeholder="Optional" /></label>
            <label className="ws-field">Rest (sec)<input type="number" min="0" max="3600" value={exercise.restSeconds} onChange={(event) => setExerciseForms(exerciseForms.map((item, i) => i === index ? { ...item, restSeconds: event.target.value } : item))} placeholder="60" /></label>
            <button type="button" className="ws-icon-button" aria-label="Remove exercise" disabled={exerciseForms.length === 1} onClick={() => setExerciseForms(exerciseForms.filter((_, i) => i !== index))}><X size={15} /></button>
          </div>)}
          <button type="button" className="ws-quiet-button" onClick={() => setExerciseForms([...exerciseForms, blankExercise()])}><Plus size={15} /> Add exercise</button>
        </div>
        {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
        {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
        <button className="ws-button" disabled={saveProgram.isPending}>{saveProgram.isPending ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{editing ? 'Save template' : 'Create template'}</button>
      </form>
    </section>
    <div className="ws-two-column ws-top-gap">
      <section className="ws-panel">
        <div className="ws-panel-head"><div><span className="ws-eyebrow">PROGRAM LIBRARY</span><h2>Saved templates</h2></div><label className="ws-check"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} /> Include archived</label></div>
        {programs.isLoading ? <LoadingPanel /> : programs.isError ? <div className="ws-error">{serverError(programs.error, 'Workout templates could not be loaded.')}</div> :
          (programs.data ?? []).length === 0 ? <p className="ws-empty">No templates yet. Create one above to get started.</p> :
            <div className="ws-program-list">{(programs.data ?? []).map((program) => <article className="ws-program-card" key={program.id}>
              <div className="ws-panel-head"><div><h3>{program.name}</h3><p>{program.goal}</p></div><span className={`ws-status ${program.status === 'archived' ? 'is-muted' : ''}`}>{program.status}</span></div>
              {program.description && <p className="ws-program-notes">{program.description}</p>}
               <div className="ws-program-meta"><span>{program.recommendedDaysPerWeek} days/week</span><span>{program.expectedSessionMinutes} min/session</span><span>{program.minimumExperience}–{program.maximumExperience}</span>{program.trainerReviewRequired && <span>Trainer review required</span>}</div>
              <ol className="ws-exercise-list">{program.exercises.map((exercise) => <li key={exercise.id}><span>{exercise.name}</span><small>{exercise.sets} sets{exercise.repetitions ? ` · ${exercise.repetitions} reps` : ''}{exercise.durationSeconds ? ` · ${exercise.durationSeconds}s` : ''}{exercise.restSeconds != null ? ` · ${exercise.restSeconds}s rest` : ''}</small></li>)}</ol>
              {program.resources.length > 0 && <div className="ws-resource-list">{program.resources.map((resource) => <button className="ws-resource" key={resource.id} onClick={async () => {
                try {
                  const blob = await customFetch<Blob>(resource.downloadUrl, { responseType: 'blob' });
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement('a'); anchor.href = url; anchor.download = resource.originalFilename; anchor.click(); URL.revokeObjectURL(url);
                } catch { setFormError('Private resource could not be downloaded.'); }
              }}><Download size={14} />{resource.originalFilename}<small>{Math.ceil(resource.sizeBytes / 1024)} KB</small></button>)}</div>}
              <div className="ws-program-actions">
                <button className="ws-quiet-button" onClick={() => editProgram(program)}>Edit template</button>
                <button className="ws-quiet-button" onClick={() => { setSelectedProgram(program.id); setMessage(`${program.name} selected for assignment.`); window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }); }} disabled={program.status !== 'active'}>Assign</button>
                <button className="ws-quiet-button" onClick={() => updateProgram.mutate({ id: program.id, payload: { status: program.status === 'archived' ? 'active' : 'archived' } })}>{program.status === 'archived' ? 'Restore' : 'Archive'}</button>
                <label className="ws-file-button"><FilePlus2 size={15} /> Add PDF/image<input type="file" accept=".pdf,image/jpeg,image/png,image/webp" onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) uploadResource.mutate({ programId: program.id, file });
                  event.currentTarget.value = '';
                }} /></label>
              </div>
            </article>)}</div>
        }
      </section>
      <div className="ws-stack">
        <section className="ws-panel">
          <div className="ws-panel-head"><div><span className="ws-eyebrow">MEMBER ASSIGNMENT</span><h2>Assign a plan</h2></div><Dumbbell size={18} /></div>
          <form className="ws-form" onSubmit={submitAssignment}>
            <label className="ws-field">Workout template<select value={selectedProgram} onChange={(event) => setSelectedProgram(event.target.value)}><option value="">Choose an active template</option>{(programs.data ?? []).filter((item) => item.status === 'active').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label className="ws-field">Find member<input value={memberSearch} onChange={(event) => { setMemberSearch(event.target.value); setSelectedMember(null); }} placeholder="Name or member number" /></label>
            {memberResults.data && <div className="ws-search-results">{memberResults.data.map((member) => <button type="button" key={member.id} onClick={() => { setSelectedMember(member); setMemberSearch(member.fullName); }}><b>{member.fullName}</b><small>{member.memberNumber} · {member.status}</small></button>)}</div>}
            {selectedMember && <p className="ws-selected-member"><Check size={15} /> {selectedMember.fullName} · {selectedMember.memberNumber}</p>}
            <div className="ws-field-grid ws-two-fields">
              <label className="ws-field">Start date<input type="date" value={startsOn} onChange={(event) => setStartsOn(event.target.value)} /></label>
              <label className="ws-field">Coaching note<input value={assignmentNotes} onChange={(event) => setAssignmentNotes(event.target.value)} placeholder="Optional" maxLength={1000} /></label>
            </div>
            {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
            <button className="ws-button" disabled={assign.isPending}>{assign.isPending ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />} Assign plan</button>
          </form>
        </section>
        <section className="ws-panel">
          <div className="ws-panel-head"><div><span className="ws-eyebrow">ASSIGNMENT TRACKER</span><h2>Member plans</h2></div></div>
          {assignments.isLoading ? <LoadingPanel /> : assignments.isError ? <p className="ws-empty">Assignments could not be loaded.</p> :
            (assignments.data ?? []).length === 0 ? <p className="ws-empty">No workout plans have been assigned yet.</p> :
              <div className="ws-assignment-list">{(assignments.data ?? []).map((item) => <div className="ws-assignment-row" key={item.id}><span><b>{item.programName}</b><small>{item.memberName} · {item.memberNumber} · from {fmtDate(item.startsOn)}</small></span><select aria-label={`Status for ${item.memberName}`} value={item.status} onChange={(event) => updateAssignment.mutate({ id: item.id, status: event.target.value })}><option value="assigned">Assigned</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></div>)}</div>}
        </section>
      </div>
    </div>
  </div></StaffFrame>;
}

function PrivateEventCover({ event }: { event: EventItem }) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    let active = true;
    let objectUrl = '';
    if (event.coverUrl) {
      customFetch<Blob>(event.coverUrl, { responseType: 'blob' }).then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setSrc(objectUrl);
      }).catch(() => { if (active) setSrc(''); });
    }
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setSrc('');
    };
  }, [event.coverUrl]);
  return src ? <img className="ws-event-cover" src={src} alt={`${event.name} cover`} /> : <div className="ws-event-cover ws-event-cover-empty"><CalendarDays size={22} /><span>Event cover</span></div>;
}

export function EventsPage() {
  const client = useQueryClient();
  const staff = useGetCurrentStaff();
  const [timeframe, setTimeframe] = useState<'upcoming' | 'past'>('upcoming');
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [capacity, setCapacity] = useState('20');
  const [instructorId, setInstructorId] = useState('');
  const [status, setStatus] = useState('draft');
  const [search, setSearch] = useState('');
  const [registrationSearch, setRegistrationSearch] = useState('');
  const [formError, setFormError] = useState('');
  const [message, setMessage] = useState('');
  const events = useQuery({
    queryKey: ['events', timeframe],
    queryFn: () => request<EventItem[]>(`/api/events?timeframe=${timeframe}`),
  });
  const instructors = useQuery({
    queryKey: ['event-instructors'],
    queryFn: () => request<Array<{ id: string; name: string; role: Role }>>('/api/events/instructors'),
  });
  const registrations = useQuery({
    queryKey: ['event-registrations', selected?.id],
    enabled: Boolean(selected),
    queryFn: () => request<EventRegistration[]>(`/api/events/${selected!.id}/registrations`),
  });
  const memberResults = useQuery({
    queryKey: ['event-member-search', registrationSearch],
    enabled: registrationSearch.trim().length > 0 && Boolean(selected),
    queryFn: () => request<MemberOption[]>(`/api/events/members?search=${encodeURIComponent(registrationSearch.trim())}`),
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['events'] }),
      client.invalidateQueries({ queryKey: ['event-registrations'] }),
      client.invalidateQueries({ queryKey: ['workspace-summary'] }),
    ]);
  };
  const saveEvent = useMutation({
    mutationFn: (payload: object) => request<EventItem>(
      selected ? `/api/events/${selected.id}` : '/api/events',
      jsonBody(selected ? 'PATCH' : 'POST', payload),
    ),
    onSuccess: async (event) => {
      setMessage(selected ? 'Event details updated.' : 'Event created.');
      setFormError('');
      setSelected(event);
      setName(event.name);
      setDescription(event.description ?? '');
      setStartsAt(localDateTimeInput(event.startsAt));
      setEndsAt(localDateTimeInput(event.endsAt));
      setCapacity(String(event.capacity));
      setInstructorId(event.instructorStaffId ?? '');
      setStatus(event.status);
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Event could not be saved.')),
  });
  const updateEvent = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: object }) =>
      request<EventItem>(`/api/events/${id}`, jsonBody('PATCH', payload)),
    onSuccess: async (event) => {
      if (selected?.id === event.id) setSelected(event);
      setMessage('Event status updated.');
      setFormError('');
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Event could not be updated.')),
  });
  const register = useMutation({
    mutationFn: (memberId: string) => request<EventRegistration>(
      `/api/events/${selected!.id}/registrations`,
      jsonBody('POST', { memberId }),
    ),
    onSuccess: async () => {
      setMessage('Member registered for this event.');
      setFormError('');
      setRegistrationSearch('');
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Member could not be registered.')),
  });
  const cancelRegistration = useMutation({
    mutationFn: (registrationId: string) =>
      request<EventRegistration>(`/api/events/${selected!.id}/registrations/${registrationId}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: (error) => setFormError(serverError(error, 'Registration could not be cancelled.')),
  });
  const uploadCover = useMutation({
    mutationFn: ({ eventId, file }: { eventId: string; file: File }) =>
      customFetch<EventItem>(`/api/events/${eventId}/cover`, {
        method: 'POST',
        body: file,
        headers: {
          'content-type': 'application/octet-stream',
          'x-file-name': encodeURIComponent(file.name),
        },
        responseType: 'json',
      }),
    onSuccess: async (event) => {
      setSelected(event);
      setMessage('Private event cover uploaded.');
      await refresh();
    },
    onError: (error) => setFormError(serverError(error, 'Event cover could not be uploaded.')),
  });

  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setDescription(selected.description ?? '');
    setStartsAt(localDateTimeInput(selected.startsAt));
    setEndsAt(localDateTimeInput(selected.endsAt));
    setCapacity(String(selected.capacity));
    setInstructorId(selected.instructorStaffId ?? '');
    setStatus(selected.status);
  }, [selected?.id]);

  function resetEvent() {
    setSelected(null);
    setName('');
    setDescription('');
    setStartsAt('');
    setEndsAt('');
    setCapacity('20');
    setInstructorId('');
    setStatus('draft');
    setFormError('');
    setMessage('');
  }
  function submitEvent(event: FormEvent) {
    event.preventDefault();
    setFormError('');
    setMessage('');
    if (!startsAt || !endsAt || new Date(startsAt).getTime() >= new Date(endsAt).getTime()) {
      setFormError('Choose an end time after the start time.');
      return;
    }
    saveEvent.mutate({
      name: name.trim(),
      description: description.trim() || null,
      startsAt,
      endsAt,
      capacity: Number(capacity),
      instructorStaffId: instructorId || null,
      status,
    });
  }

  if (staff.isLoading) return <div className="op-loading"><LoadingPanel /></div>;
  if (!staff.data) return <div className="op-loading"><div className="ws-error">Staff access could not be confirmed.</div></div>;
  const canManage = staff.data.role !== 'receptionist';
  const editable = !selected || selected.status !== 'cancelled';
  const visibleEvents = (events.data ?? []).filter((event) => !search.trim() || event.name.toLowerCase().includes(search.trim().toLowerCase()));

  return <StaffFrame active="events"><div className="ws-page">
    <WorkspaceHeading eyebrow="GYM CALENDAR" title="Events and classes" description="Publish a class, keep its capacity accurate and register members from the front desk or training workspace." />
    {canManage && <section className="ws-panel">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">{selected ? 'EDIT EVENT' : 'EVENT PLANNING'}</span><h2>{selected ? `Update ${selected.name}` : 'Create a gym event'}</h2></div>{selected && <button className="ws-quiet-button" onClick={resetEvent}><X size={15} /> New event</button>}</div>
      <form className="ws-form" onSubmit={submitEvent}>
        <div className="ws-field-grid ws-three-columns">
          <label className="ws-field">Event name<input required minLength={2} maxLength={140} value={name} onChange={(event) => setName(event.target.value)} placeholder="Saturday strength class" /></label>
          <label className="ws-field">Instructor<select value={instructorId} onChange={(event) => setInstructorId(event.target.value)}><option value="">No instructor selected</option>{(instructors.data ?? []).map((person) => <option key={person.id} value={person.id}>{person.name} · {person.role}</option>)}</select></label>
          <label className="ws-field">Capacity<input required type="number" min="1" max="10000" value={capacity} onChange={(event) => setCapacity(event.target.value)} /></label>
          <label className="ws-field">Starts (Nairobi time)<input required type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
          <label className="ws-field">Ends (Nairobi time)<input required type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} /></label>
          <label className="ws-field">Visibility<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="draft">Draft</option><option value="published">Published</option><option value="cancelled">Cancelled</option></select></label>
        </div>
        <label className="ws-field">Description<textarea rows={3} maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What should members know before they arrive?" /></label>
        {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
        {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
        <button className="ws-button" disabled={saveEvent.isPending}>{saveEvent.isPending ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{selected ? 'Save event' : 'Create event'}</button>
      </form>
    </section>}
    <div className="ws-event-layout ws-top-gap">
      <section className="ws-panel">
        <div className="ws-panel-head"><div><span className="ws-eyebrow">EVENT LIST</span><h2>{timeframe === 'upcoming' ? 'Upcoming' : 'Past'} events</h2></div><div className="ws-toggle"><button className={timeframe === 'upcoming' ? 'active' : ''} onClick={() => setTimeframe('upcoming')}>Upcoming</button><button className={timeframe === 'past' ? 'active' : ''} onClick={() => setTimeframe('past')}>Past</button></div></div>
        <div className="ws-toolbar ws-toolbar-compact"><label className="ws-search"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter event names" /></label></div>
        {events.isLoading ? <LoadingPanel /> : events.isError ? <div className="ws-error">{serverError(events.error, 'Events could not be loaded.')}</div> :
          visibleEvents.length === 0 ? <p className="ws-empty">No events match this view.</p> :
            <div className="ws-event-cards">{visibleEvents.map((event) => <article className={`ws-event-card ${selected?.id === event.id ? 'is-selected' : ''}`} key={event.id}>
              <button className="ws-event-select" onClick={() => { setSelected(event); setFormError(''); setMessage(''); }}><span><b>{event.name}</b><small>{fmtDateTime(event.startsAt)} · {event.instructorName || 'No instructor'}</small></span><span className={`ws-status status-${event.status}`}>{event.status}</span></button>
              <p>{event.description || 'No event description.'}</p>
              <div className="ws-event-meta"><span><UsersRound size={14} /> {event.registeredCount}/{event.capacity} registered</span><span>{event.remainingSlots} spaces available</span></div>
            </article>)}</div>}
      </section>
      <section className="ws-panel">
        {!selected ? <div className="ws-empty-state"><CalendarDays size={24} /><h2>Select an event</h2><p>Choose an event to review bookings and register a member.</p></div> :
          <>
            <div className="ws-panel-head"><div><span className="ws-eyebrow">EVENT DETAILS</span><h2>{selected.name}</h2><p>{fmtDateTime(selected.startsAt)} – {fmtDateTime(selected.endsAt)}</p></div><span className={`ws-status status-${selected.status}`}>{selected.status}</span></div>
            <PrivateEventCover event={selected} />
            {canManage && <div className="ws-event-tools">
              <label className="ws-file-button"><FilePlus2 size={15} /> Upload cover<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) uploadCover.mutate({ eventId: selected.id, file });
                event.currentTarget.value = '';
              }} /></label>
              {editable && selected.status !== 'cancelled' && <button className="ws-quiet-button ws-danger-action" onClick={() => updateEvent.mutate({ id: selected.id, payload: { status: 'cancelled' } })}><X size={15} /> Cancel event</button>}
            </div>}
            <div className="ws-event-booking">
              <div className="ws-panel-head"><div><span className="ws-eyebrow">MEMBER BOOKINGS</span><h3>{selected.registeredCount} of {selected.capacity} spots</h3></div><span className="ws-status">{selected.remainingSlots} open</span></div>
              {selected.status === 'published' && <div className="ws-register-box">
                <label className="ws-field">Find an active member<input value={registrationSearch} onChange={(event) => { setRegistrationSearch(event.target.value); setMessage(''); }} placeholder="Name, phone or member number" /></label>
                {memberResults.data && <div className="ws-search-results">{memberResults.data.map((member) => <button type="button" key={member.id} disabled={member.status !== 'active'} onClick={() => register.mutate(member.id)}><b>{member.fullName}</b><small>{member.memberNumber} · {member.status} · register</small></button>)}</div>}
              </div>}
              {registrations.isLoading ? <LoadingPanel /> : registrations.isError ? <div className="ws-error">{serverError(registrations.error, 'Registrations could not be loaded.')}</div> :
                (registrations.data ?? []).length === 0 ? <p className="ws-empty">No members are registered yet.</p> :
                  <div className="ws-registrations">{(registrations.data ?? []).map((entry) => <div className="ws-registration-row" key={entry.id}><span><b>{entry.memberName}</b><small>{entry.memberNumber} · {entry.status}</small></span>{entry.status === 'confirmed' && <button className="ws-icon-button" aria-label={`Cancel ${entry.memberName}'s registration`} onClick={() => cancelRegistration.mutate(entry.id)}><X size={15} /></button>}</div>)}</div>}
              {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
              {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
            </div>
          </>}
      </section>
    </div>
  </div></StaffFrame>;
}

function StaffRow({ member, onSave, saving }: {
  member: StaffMember; onSave: (id: string, changes: object) => void; saving: boolean;
}) {
  const [role, setRole] = useState(member.role);
  const [status, setStatus] = useState(member.status);
  useEffect(() => {
    setRole(member.role);
    setStatus(member.status);
  }, [member.role, member.status]);
  const changed = role !== member.role || status !== member.status;
  function save() {
    const changes: Record<string, string> = {};
    if (role !== member.role) changes.role = role;
    if (status !== member.status) changes.status = status;
    onSave(member.id, changes);
  }
  return <tr>
    <td><b>{member.name}</b><small>{member.email}</small></td>
    <td><select value={role} onChange={(event) => setRole(event.target.value as Role)}>{member.role === 'owner' && <option value="owner">Owner</option>}<option value="receptionist">Receptionist</option><option value="trainer">Trainer</option></select></td>
    <td><select value={status} onChange={(event) => setStatus(event.target.value as 'active' | 'inactive')}><option value="active">Active</option><option value="inactive">Inactive</option></select></td>
    <td><button className="ws-quiet-button" onClick={save} disabled={!changed || saving}>{saving ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />} Save</button></td>
  </tr>;
}

export function StaffManagementPage() {
  const staff = useGetCurrentStaff();
  const client = useQueryClient();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'receptionist' | 'trainer'>('receptionist');
  const [message, setMessage] = useState('');
  const [formError, setFormError] = useState('');
  const list = useQuery({
    queryKey: ['staff-list'],
    enabled: staff.data?.role === 'owner',
    queryFn: () => request<StaffMember[]>('/api/staff'),
  });
  const addStaff = useMutation({
    mutationFn: () => request<StaffMember>('/api/staff', jsonBody('POST', { email: email.trim(), role })),
    onSuccess: async () => {
      setEmail('');
      setMessage('Staff access assigned. The person can sign in with this verified account.');
      setFormError('');
      await client.invalidateQueries({ queryKey: ['staff-list'] });
    },
    onError: (error) => setFormError(serverError(error, 'Staff access could not be assigned.')),
  });
  const updateStaff = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: object }) =>
      request<StaffMember>(`/api/staff/${id}`, jsonBody('PATCH', changes)),
    onSuccess: async () => {
      setMessage('Staff role or status updated.');
      setFormError('');
      await client.invalidateQueries({ queryKey: ['staff-list'] });
    },
    onError: (error) => setFormError(serverError(error, 'Staff access could not be updated.')),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    setFormError('');
    setMessage('');
    addStaff.mutate();
  }

  if (staff.isLoading) return <div className="op-loading"><LoadingPanel /></div>;
  if (!staff.data) return <div className="op-loading"><div className="ws-error">Staff access could not be confirmed.</div></div>;
  if (staff.data.role !== 'owner') return <Redirect to="/dashboard" />;
  return <StaffFrame active="staff"><div className="ws-page">
    <WorkspaceHeading eyebrow="OWNER CONTROLS" title="Staff access" description="Assign a verified sign-in account to a gym role and keep active access limited to the right people." />
    <section className="ws-panel">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">ADD A TEAM MEMBER</span><h2>Assign staff access</h2></div><UserCog size={19} /></div>
      <p className="ws-helper-copy">The person must already have a verified MyGym sign-in account using this email. This action assigns their role; it does not create a sign-in account or grant owner access.</p>
      <form className="ws-staff-add" onSubmit={submit}>
        <label className="ws-field">Verified account email<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" /></label>
        <label className="ws-field">Role<select value={role} onChange={(event) => setRole(event.target.value as 'receptionist' | 'trainer')}><option value="receptionist">Receptionist</option><option value="trainer">Trainer</option></select></label>
        <button className="ws-button" disabled={addStaff.isPending}>{addStaff.isPending ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />} Assign role</button>
      </form>
      {message && <p className="ws-success" role="status"><Check size={16} />{message}</p>}
      {formError && <p className="ws-error" role="alert"><CircleAlert size={16} />{formError}</p>}
    </section>
    <section className="ws-panel ws-top-gap">
      <div className="ws-panel-head"><div><span className="ws-eyebrow">TEAM DIRECTORY</span><h2>Gym staff</h2></div><span className="ws-muted">{list.data?.length ?? 0} accounts</span></div>
      {list.isLoading ? <LoadingPanel /> : list.isError ? <div className="ws-error">{serverError(list.error, 'Staff accounts could not be loaded.')}</div> :
        (list.data ?? []).length === 0 ? <p className="ws-empty">No staff accounts are available.</p> :
          <div className="ws-table-wrap"><table className="ws-table ws-staff-table"><thead><tr><th>Staff account</th><th>Role</th><th>Status</th><th>Update</th></tr></thead><tbody>
            {(list.data ?? []).map((member) => <StaffRow key={member.id} member={member} saving={updateStaff.isPending} onSave={(id, changes) => updateStaff.mutate({ id, changes })} />)}
          </tbody></table></div>}
      <p className="ws-last-owner-note"><ShieldCheck size={15} /> The gym must always keep at least one active owner.</p>
    </section>
  </div></StaffFrame>;
}
