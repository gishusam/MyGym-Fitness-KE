import { useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight, Check, CircleAlert, Clock3, Dumbbell, LoaderCircle,
  ShieldCheck, Sparkles, UserRound, UsersRound,
} from 'lucide-react';
import { customFetch } from '@workspace/api-client-react';

type Goal = 'build_strength' | 'lose_weight' | 'improve_fitness' | 'gain_muscle' | 'general_wellness';
type Experience = 'beginner' | 'intermediate' | 'advanced';
type Equipment = 'bodyweight' | 'dumbbells' | 'resistance_bands' | 'barbell' | 'machines' | 'cardio_machines' | 'full_gym';
type Exercise = {
  id: string;
  name: string;
  sets: number;
  repetitions: number | null;
  durationSeconds: number | null;
  restSeconds: number | null;
};
type Program = {
  id: string;
  name: string;
  goal: string;
  description: string | null;
  recommendedDaysPerWeek: number;
  expectedSessionMinutes: number;
  equipmentRequirements: string[];
  trainerReviewRequired: boolean;
  exercises: Exercise[];
  matchReasons: string[];
};
type Questionnaire = {
  primaryGoal: Goal;
  experience: Experience;
  availableDaysPerWeek: number;
  sessionDurationMinutes: number;
  equipmentPreferences: Equipment[];
  limitations: string | null;
  notes: string | null;
};
type OnboardingView = {
  firstName: string;
  expiresAt: string;
  submitted: boolean;
  questionnaire: Questionnaire | null;
  reviewStatus: 'awaiting_review' | 'trainer_approved' | null;
  recommendation: Program | null;
  alternatives: Program[];
  noMatchReason: string | null;
  assignedProgram: Program | null;
};

const goals: Array<{ value: Goal; label: string }> = [
  { value: 'build_strength', label: 'Build strength' },
  { value: 'lose_weight', label: 'Lose weight' },
  { value: 'improve_fitness', label: 'Improve fitness' },
  { value: 'gain_muscle', label: 'Gain muscle' },
  { value: 'general_wellness', label: 'General wellbeing' },
];
const equipment: Array<{ value: Equipment; label: string }> = [
  { value: 'bodyweight', label: 'Bodyweight' },
  { value: 'dumbbells', label: 'Dumbbells' },
  { value: 'resistance_bands', label: 'Resistance bands' },
  { value: 'barbell', label: 'Barbell' },
  { value: 'machines', label: 'Weight machines' },
  { value: 'cardio_machines', label: 'Cardio machines' },
  { value: 'full_gym', label: 'Full gym access' },
];
const emptyForm = (): Questionnaire => ({
  primaryGoal: 'improve_fitness',
  experience: 'beginner',
  availableDaysPerWeek: 3,
  sessionDurationMinutes: 45,
  equipmentPreferences: [],
  limitations: null,
  notes: null,
});
const request = <T,>(path: string, init?: RequestInit) =>
  customFetch<T>(path, { ...init, responseType: 'json' });

function ProgramCard({ program, label }: { program: Program; label: string }) {
  return <article className="member-program-card">
    <div className="member-program-head"><div><span>{label}</span><h3>{program.name}</h3></div><span className="member-program-time"><Clock3 size={14} />{program.expectedSessionMinutes} min</span></div>
    <p className="member-program-focus">{program.goal}</p>
    {program.description && <p className="member-program-description">{program.description}</p>}
    <div className="member-program-schedule"><Dumbbell size={16} /><span><b>{program.recommendedDaysPerWeek} sessions each week</b><small>Choose days that fit your routine and space sessions out for recovery.</small></span></div>
    <h4>Exercises in this saved program</h4>
    {program.exercises.length ? <ol className="member-exercise-list">{program.exercises.map((exercise) =>
      <li key={exercise.id}><span>{exercise.name}</span><small>{exercise.sets} sets{exercise.repetitions ? ` · ${exercise.repetitions} reps` : ''}{exercise.durationSeconds ? ` · ${Math.round(exercise.durationSeconds / 60)} min` : ''}{exercise.restSeconds != null ? ` · ${exercise.restSeconds}s rest` : ''}</small></li>,
    )}</ol> : <p className="member-empty-note">Ask a trainer to walk you through this plan.</p>}
    {program.matchReasons.length > 0 && <div className="member-match"><b>Why it fits your answers</b><ul>{program.matchReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
    {program.trainerReviewRequired && <p className="member-review-note"><ShieldCheck size={15} /> This program needs trainer review before it can be assigned.</p>}
  </article>;
}

function BeginnerGuidance() {
  return <section className="member-guidance">
    <div className="member-guidance-title"><Sparkles size={18} /><div><b>Your first weeks are about learning</b><span>Start steadily; you can build up over time.</span></div></div>
    <ul>
      <li>Ask an on-site trainer to demonstrate new movements and check your technique.</li>
      <li>Choose a manageable effort. Stop and ask for help if something feels wrong.</li>
      <li>Keep the routine consistent and leave time between sessions to recover.</li>
      <li>Increase weight or difficulty gradually, with a trainer's guidance.</li>
    </ul>
    <p>MyGym's trainers are here in person to help you stay consistent and make progress toward your goals.</p>
  </section>;
}

export function MemberOnboardingPage({ token }: { token: string }) {
  const client = useQueryClient();
  const [form, setForm] = useState<Questionnaire>(emptyForm);
  const [editing, setEditing] = useState(false);
  const query = useQuery({
    queryKey: ['public-member-onboarding', token],
    queryFn: () => request<OnboardingView>(`/api/public/onboarding/${encodeURIComponent(token)}`),
    retry: false,
  });
  useEffect(() => {
    if (query.data?.questionnaire) setForm(query.data.questionnaire);
  }, [query.data?.questionnaire]);

  const submit = useMutation({
    mutationFn: () => request<OnboardingView>(
      `/api/public/onboarding/${encodeURIComponent(token)}`,
      { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(form) },
    ),
    onSuccess: async (view) => {
      client.setQueryData(['public-member-onboarding', token], view);
      setEditing(false);
    },
  });
  function setField<K extends keyof Questionnaire>(key: K, value: Questionnaire[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }
  function toggleEquipment(value: Equipment) {
    setForm((previous) => ({
      ...previous,
      equipmentPreferences: previous.equipmentPreferences.includes(value)
        ? previous.equipmentPreferences.filter((item) => item !== value)
        : [...previous.equipmentPreferences, value],
    }));
  }
  function submitQuestionnaire(event: FormEvent) {
    event.preventDefault();
    submit.mutate();
  }

  const view = query.data;
  const shouldShowForm = !view?.submitted || editing;
  const isApproved = view?.reviewStatus === 'trainer_approved' && !!view.assignedProgram;

  return <main className="member-onboarding-page">
    <header className="member-onboarding-nav"><a href="/" aria-label="MyGym home"><span className="member-brand-mark"><Dumbbell size={18} /></span><span><b>MyGym</b><small>FITNESS KE</small></span></a><span><ShieldCheck size={15} /> Private member link</span></header>
    <div className="member-onboarding-wrap">
      {query.isLoading ? <section className="member-loading"><LoaderCircle size={24} className="spin" /><p>Opening your secure onboarding link…</p></section> :
        query.isError || !view ? <section className="member-error-state"><CircleAlert size={28} /><h1>This link is no longer available</h1><p>Ask the MyGym receptionist to prepare a fresh onboarding link for you.</p></section> :
          <>
            <section className="member-welcome-card">
              <span className="member-eyebrow">WELCOME TO MYGYM</span>
              <h1>{view.assignedProgram ? `You're ready, ${view.firstName}.` : `Let's find a good place to start, ${view.firstName}.`}</h1>
              <p>Tell us a little about your goals and routine. MyGym will suggest a program already saved by your gym team, and a trainer will review the final plan with you.</p>
              <div className="member-welcome-points"><span><UserRound size={15} /> No staff account needed</span><span><ShieldCheck size={15} /> Link expires {new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeZone: 'Africa/Nairobi' }).format(new Date(view.expiresAt))}</span></div>
            </section>

            {shouldShowForm ? <section className="member-questionnaire">
              <div className="member-section-heading"><span>YOUR FITNESS PROFILE</span><h2>{view.submitted ? 'Update your answers' : 'A few quick questions'}</h2><p>There are no wrong answers. This helps your trainer suggest a routine that fits your week.</p></div>
              <form onSubmit={submitQuestionnaire}>
                <label className="member-field">What is your main goal?
                  <select value={form.primaryGoal} onChange={(event) => setField('primaryGoal', event.target.value as Goal)}>{goals.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select>
                </label>
                <label className="member-field">How would you describe your training experience?
                  <select value={form.experience} onChange={(event) => setField('experience', event.target.value as Experience)}>
                    <option value="beginner">New to gym training</option><option value="intermediate">Some regular experience</option><option value="advanced">Experienced</option>
                  </select>
                </label>
                <div className="member-field-grid">
                  <label className="member-field">How many days can you train each week?
                    <select value={form.availableDaysPerWeek} onChange={(event) => setField('availableDaysPerWeek', Number(event.target.value))}>{[1,2,3,4,5,6,7].map((days) => <option key={days} value={days}>{days} {days === 1 ? 'day' : 'days'}</option>)}</select>
                  </label>
                  <label className="member-field">Preferred session length
                    <select value={form.sessionDurationMinutes} onChange={(event) => setField('sessionDurationMinutes', Number(event.target.value))}>{[30,45,60,75,90,120,180].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select>
                  </label>
                </div>
                <fieldset className="member-field member-equipment"><legend>What equipment can you use?</legend><p>Select what is available to you. Leave blank if you are unsure.</p><div>{equipment.map((item) => <label key={item.value}><input type="checkbox" checked={form.equipmentPreferences.includes(item.value)} onChange={() => toggleEquipment(item.value)} /><span>{item.label}</span></label>)}</div></fieldset>
                <label className="member-field">Any movement limitations or injuries your trainer should know about? <span>Optional</span>
                  <textarea value={form.limitations ?? ''} maxLength={1200} rows={3} onChange={(event) => setField('limitations', event.target.value || null)} placeholder="Share only what you are comfortable telling your trainer." />
                  <small>This is not medical advice. If you share a limitation, MyGym will send your profile to a trainer rather than guess at exercises.</small>
                </label>
                <label className="member-field">Anything else that would help us support you? <span>Optional</span>
                  <textarea value={form.notes ?? ''} maxLength={1200} rows={2} onChange={(event) => setField('notes', event.target.value || null)} placeholder="For example, what helps you stay consistent?" />
                </label>
                {submit.isError && <p className="member-form-error" role="alert"><CircleAlert size={16} />{submit.error instanceof Error ? submit.error.message : 'We could not save your answers. Please try again.'}</p>}
                <div className="member-form-footer"><span>Your answers are only shared with authorised MyGym staff.</span><button type="submit" disabled={submit.isPending}>{submit.isPending ? <LoaderCircle size={17} className="spin" /> : <ArrowRight size={17} />}{submit.isPending ? 'Saving…' : 'See my recommendation'}</button></div>
              </form>
            </section> :
              <section className="member-results">
                <div className={`member-result-status ${isApproved ? 'is-approved' : ''}`}><span>{isApproved ? <Check size={15} /> : <Clock3 size={15} />}</span><div><b>{isApproved ? 'Your trainer approved this program' : 'Trainer review pending'}</b><small>{isApproved ? 'This is the program assigned for you.' : 'This is a suggestion, not an assigned workout. A trainer will confirm or adjust it with you.'}</small></div></div>
                {view.assignedProgram && <ProgramCard program={view.assignedProgram} label="YOUR ASSIGNED PROGRAM" />}
                {!view.assignedProgram && view.recommendation && <ProgramCard program={view.recommendation} label="A SUGGESTED PROGRAM FROM YOUR GYM" />}
                {view.noMatchReason && <div className="member-no-match"><UsersRound size={19} /><p>{view.noMatchReason}</p></div>}
                {!view.assignedProgram && view.alternatives.length > 0 && <section className="member-alternatives"><div><span>OTHER SAVED OPTIONS</span><h2>Programs your trainer can consider</h2></div><div>{view.alternatives.map((program) => <ProgramCard key={program.id} program={program} label="ALTERNATIVE" />)}</div></section>}
                {view.questionnaire?.experience === 'beginner' && <BeginnerGuidance />}
                <div className="member-trainer-cta"><UsersRound size={20} /><div><b>Your trainers are here to help</b><p>Talk to an on-site trainer about technique, intensity, recovery and staying consistent as you work toward your goal.</p></div></div>
                {!isApproved && <button className="member-edit-answers" onClick={() => setEditing(true)}>Update my answers</button>}
              </section>}
            <footer className="member-onboarding-footer"><span>MYGYM FITNESS KE</span><span>Need a hand? Ask the receptionist or an on-site trainer.</span></footer>
          </>}
    </div>
  </main>;
}
