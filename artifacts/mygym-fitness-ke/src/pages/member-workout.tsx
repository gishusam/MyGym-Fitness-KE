import { useQuery } from '@tanstack/react-query';
import { Clock3, Download, Dumbbell, ShieldCheck, UsersRound } from 'lucide-react';

type Workout = {
  memberFirstName: string;
  memberName: string;
  programName: string;
  goal: string;
  description: string | null;
  daysPerWeek: number;
  sessionMinutes: number;
  startsOn: string;
  trainerNotes: string | null;
  trainerGuidance: string;
  exercises: Array<{ name: string; sets: number; repetitions: number | null; durationSeconds: number | null; restSeconds: number | null }>;
};

export function MemberWorkoutPage({ token }: { token: string }) {
  const base = `/api/public/workout/${encodeURIComponent(token)}`;
  const query = useQuery({
    queryKey: ['member-workout', token],
    queryFn: async () => {
      const response = await fetch(base, { cache: 'no-store' });
      if (!response.ok) {
        if (response.status === 403) throw new Error('Your membership is not currently active. Please contact reception.');
        throw new Error('This private workout link has expired or is no longer available. Ask your trainer for a new one.');
      }
      return await response.json() as Workout;
    },
    retry: false,
  });
  const workout = query.data;
  return <main className="member-onboarding-page" style={{ minHeight: '100vh' }}>
    <header className="member-onboarding-nav">
      <a href="/"><span className="member-brand-mark"><Dumbbell size={18}/></span><span><b>MyGym</b><small>FITNESS KE</small></span></a>
      <span><ShieldCheck size={15}/> Private workout link</span>
    </header>
    <div className="member-onboarding-wrap">
      {query.isLoading && <section className="member-loading">Opening your workout…</section>}
      {query.isError && <section className="member-error-state"><h1>Workout unavailable</h1><p>{query.error instanceof Error ? query.error.message : 'Please contact your gym.'}</p></section>}
      {workout && <>
        <section className="member-welcome-card">
          <span className="member-eyebrow">TRAINER-APPROVED WORKOUT</span>
          <h1>Your program is ready, {workout.memberFirstName}.</h1>
          <p>{workout.programName} — {workout.goal}</p>
          {workout.description && <p>{workout.description}</p>}
          <div className="member-welcome-points">
            <span><Dumbbell size={15}/> {workout.daysPerWeek} days/week</span>
            <span><Clock3 size={15}/> About {workout.sessionMinutes} minutes/session</span>
          </div>
          <a className="member-pdf-download" href={`${base}/pdf`} download="mygym-workout.pdf"><Download size={17}/> Download workout PDF</a>
        </section>
        <section className="member-results">
          <article className="member-program-card">
            <h2>Your exercises</h2>
            <ol className="member-exercise-list">{workout.exercises.map((exercise, i) => <li key={`${exercise.name}-${i}`}>
              <span>{exercise.name}</span><small>{exercise.sets} sets · {exercise.repetitions ? `${exercise.repetitions} reps` : `${exercise.durationSeconds ?? 0}s`} · {exercise.restSeconds ?? 0}s rest</small>
            </li>)}</ol>
          </article>
          {workout.trainerNotes && <article className="member-program-card"><h3>Trainer notes</h3><p>{workout.trainerNotes}</p></article>}
          <div className="member-trainer-cta"><UsersRound size={20}/><div><b>Your trainers are here to help</b><p>{workout.trainerGuidance}</p></div></div>
        </section>
      </>}
    </div>
  </main>;
}
