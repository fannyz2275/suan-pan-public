import { useEffect, useState } from 'react'
import MonthlyExpensesChip from './MonthlyExpensesChip'
import Slider15 from './profile/Slider15'
import type { ExpenseStatistic } from '@/lib/api'
import { fetchScales, type ScalesPayload } from '@/lib/profileScales'

export type EmploymentStatus =
  | 'employed' | 'self_employed' | 'unemployed' | 'retired' | 'unknown'

export interface Profile {
  id: string
  age?: number | null
  /** Legacy enum — kept readable for the dual-write window. New writes use _v2. */
  risk_tolerance?: 'conservative' | 'moderate' | 'aggressive' | null
  /** 1-5 scalar; the new source of truth. Anchor sentences live in /profile/scales. */
  risk_tolerance_v2?: number | null
  time_horizon?: 'short' | 'medium' | 'long' | 'unknown' | null
  time_horizon_v2?: number | null
  employment_status?: EmploymentStatus | null
  region?: string | null
  dependents?: number | null
  use_category_baselines?: boolean | null
}

export interface Memory {
  preferences?: string | null
  financial_status?: string | null
  financial_goals?: string | null
}

interface Props {
  profile: Profile
  memory?: Memory | null
  onSave: (patch: Partial<Profile>) => Promise<void>
  onClearMemory?: () => Promise<void>
  statistic?: ExpenseStatistic | null
}

const dash = (v: number | null | undefined, fmt: (n: number) => string = (n) => String(n)) =>
  v == null ? '—' : fmt(v)

const EMPLOYMENT_OPTIONS: { value: EmploymentStatus; label: string }[] = [
  { value: 'unknown', label: 'Prefer not to say' },
  { value: 'employed', label: 'Employed' },
  { value: 'self_employed', label: 'Self-employed' },
  { value: 'unemployed', label: 'Unemployed' },
  { value: 'retired', label: 'Retired' },
]

export default function ProfileCard({ profile, memory, onSave, onClearMemory, statistic = null }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (!expanded) {
    return (
      <div className="border rounded-lg p-4 flex items-center justify-between">
        <div className="text-sm">
          <span>Age {dash(profile.age)}</span>
          <span className="mx-2">·</span>
          <span>Risk {dash(profile.risk_tolerance_v2, (n) => `${n}/5`)}</span>
          <span className="mx-2">·</span>
          <span>Horizon {dash(profile.time_horizon_v2, (n) => `${n}/5`)}</span>
          <span className="mx-2">·</span>
          <span>{dash(profile.dependents, (n) => `${n} dependents`)}</span>
          <span className="mx-2">·</span>
          <MonthlyExpensesChip statistic={statistic} />
          {profile.use_category_baselines === false && (
            <>
              <span className="mx-2">·</span>
              <span className="text-muted-foreground">flat expenses</span>
            </>
          )}
        </div>
        <button className="text-sm underline" onClick={() => setExpanded(true)} aria-label="Edit profile">
          Edit
        </button>
      </div>
    )
  }
  return (
    <ProfileCardForm
      profile={profile}
      memory={memory}
      onSave={onSave}
      onClearMemory={onClearMemory}
      onDone={() => setExpanded(false)}
    />
  )
}

function ProfileCardForm({ profile, memory, onSave, onClearMemory, onDone }: Props & { onDone: () => void }) {
  const [age, setAge] = useState<string>(profile.age?.toString() ?? '')
  // Risk / horizon: track value AND a "dirty" bool. Only include in the patch
  // when the user actually moves the slider, so an untouched slider doesn't
  // implicitly classify the user as "balanced" (3/5) post-save.
  const [risk, setRisk] = useState<number>(profile.risk_tolerance_v2 ?? 3)
  const [riskDirty, setRiskDirty] = useState<boolean>(profile.risk_tolerance_v2 != null)
  const [horizon, setHorizon] = useState<number>(profile.time_horizon_v2 ?? 3)
  const [horizonDirty, setHorizonDirty] = useState<boolean>(profile.time_horizon_v2 != null)
  const [employment, setEmployment] = useState<EmploymentStatus>(profile.employment_status ?? 'unknown')
  const [region, setRegion] = useState<string>(profile.region ?? '')
  const [dep, setDep] = useState<string>(profile.dependents?.toString() ?? '')
  const [useBaselines, setUseBaselines] = useState<boolean>(profile.use_category_baselines ?? true)
  const [scales, setScales] = useState<ScalesPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setAge(profile.age?.toString() ?? '')
    setRisk(profile.risk_tolerance_v2 ?? 3)
    setRiskDirty(profile.risk_tolerance_v2 != null)
    setHorizon(profile.time_horizon_v2 ?? 3)
    setHorizonDirty(profile.time_horizon_v2 != null)
    setEmployment(profile.employment_status ?? 'unknown')
    setRegion(profile.region ?? '')
    setDep(profile.dependents?.toString() ?? '')
    setUseBaselines(profile.use_category_baselines ?? true)
  }, [profile])

  // Best-effort fetch — sliders still work without anchor copy (label is a
  // bare "3/5"), but we surface tooltip sentences when the call succeeds.
  useEffect(() => {
    let alive = true
    fetchScales().then((s) => { if (alive) setScales(s) }).catch(() => { /* ignore; fall back to bare slider */ })
    return () => { alive = false }
  }, [])

  const validate = (): Partial<Profile> | null => {
    const patch: Partial<Profile> = {}
    if (age !== '') {
      const n = Number(age)
      if (!Number.isFinite(n) || n < 0 || n > 120) { setErr('Age must be between 0 and 120'); return null }
      patch.age = n
    }
    if (dep !== '') {
      const n = Number(dep)
      if (!Number.isFinite(n) || n < 0) { setErr('Dependents must be 0 or more'); return null }
      patch.dependents = n
    }
    if (riskDirty) patch.risk_tolerance_v2 = risk
    if (horizonDirty) patch.time_horizon_v2 = horizon
    patch.employment_status = employment
    patch.region = region.trim() || null
    patch.use_category_baselines = useBaselines
    setErr(null)
    return patch
  }

  const submit = async () => {
    const patch = validate()
    if (!patch) return
    setSaving(true)
    try {
      await onSave(patch)
      onDone()
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="border rounded-lg p-4 space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <label className="block text-sm">Age
        <input aria-label="Age" type="number" className="ml-2 border rounded px-2 py-1 w-24" value={age} onChange={(e) => { setAge(e.target.value); setErr(null) }} />
      </label>

      <label className="block text-sm">Employment
        <select
          aria-label="Employment status"
          className="ml-2 border rounded px-2 py-1"
          value={employment}
          onChange={(e) => { setEmployment(e.target.value as EmploymentStatus); setErr(null) }}
        >
          {EMPLOYMENT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>

      <label className="block text-sm">Region
        <input
          aria-label="Region"
          type="text"
          maxLength={120}
          placeholder="e.g. SF Bay Area"
          className="ml-2 border rounded px-2 py-1 w-48"
          value={region}
          onChange={(e) => { setRegion(e.target.value); setErr(null) }}
        />
      </label>

      <label className="block text-sm">Dependents
        <input aria-label="Dependents" type="number" className="ml-2 border rounded px-2 py-1 w-24" value={dep} onChange={(e) => { setDep(e.target.value); setErr(null) }} />
      </label>

      <Slider15
        value={risk}
        anchors={scales?.risk_tolerance ?? null}
        label="Risk tolerance"
        ariaLabel="Risk tolerance"
        onChange={(n) => { setRisk(n); setRiskDirty(true) }}
        dirty={riskDirty}
      />
      <Slider15
        value={horizon}
        anchors={scales?.time_horizon ?? null}
        label="Time horizon"
        ariaLabel="Time horizon"
        onChange={(n) => { setHorizon(n); setHorizonDirty(true) }}
        dirty={horizonDirty}
      />

      <label className="flex items-start gap-2 text-sm">
        <input
          aria-label="Use category baselines"
          type="checkbox"
          className="mt-0.5"
          checked={useBaselines}
          onChange={(e) => { setUseBaselines(e.target.checked); setErr(null) }}
        />
        <span>
          Project monthly expenses from my transaction history
          <span className="block text-xs text-muted-foreground">
            When on, we estimate per-category spending from your past months. Turn off if your history is sparse or unrepresentative.
          </span>
        </span>
      </label>
      {err && <div className="text-sm text-red-600">{err}</div>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className="px-3 py-1 bg-primary text-primary-foreground rounded">
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="px-3 py-1 border rounded" onClick={onDone}>Cancel</button>
      </div>
      {memory && (
        <div className="mt-4 border-t pt-3 text-sm">
          <div className="font-medium mb-1">What the advisor remembers</div>
          <dl className="space-y-1">
            <div>
              <dt className="inline text-muted-foreground">Preferences: </dt>
              <dd className="inline">{memory.preferences || '—'}</dd>
            </div>
            <div>
              <dt className="inline text-muted-foreground">Situation: </dt>
              <dd className="inline">{memory.financial_status || '—'}</dd>
            </div>
            <div>
              <dt className="inline text-muted-foreground">Goals: </dt>
              <dd className="inline">{memory.financial_goals || '—'}</dd>
            </div>
          </dl>
          {onClearMemory && (
            <button
              type="button"
              className="mt-2 px-2 py-1 text-xs border rounded"
              onClick={async () => {
                if (window.confirm("The advisor will forget everything it's learned about you. Continue?")) {
                  await onClearMemory()
                }
              }}
            >
              Clear memory
            </button>
          )}
        </div>
      )}
    </form>
  )
}
