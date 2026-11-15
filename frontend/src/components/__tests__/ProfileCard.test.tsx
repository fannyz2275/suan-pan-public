import { fireEvent, render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import ProfileCard from '../ProfileCard'

// fetchScales is fired on form expand. Mock it out — the slider has a
// graceful fallback when the call fails / is in flight, which is what
// these unit tests exercise (they don't assert on tooltip copy).
vi.mock('@/lib/profileScales', () => ({
  fetchScales: vi.fn().mockResolvedValue({
    risk_tolerance: [], time_horizon: [],
  }),
  _resetScalesCache: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})


describe('ProfileCard collapsed', () => {
  it('renders a summary with available identity fields (no $ amounts)', () => {
    render(
      <ProfileCard
        profile={{
          id: 'u1', age: 32,
          risk_tolerance_v2: 3, time_horizon_v2: 5,
          dependents: 2, employment_status: 'employed', region: 'SF',
        }}
        onSave={async () => {}}
      />,
    )
    expect(screen.getByText(/age 32/i)).toBeInTheDocument()
    expect(screen.getByText(/risk 3\/5/i)).toBeInTheDocument()
    expect(screen.getByText(/horizon 5\/5/i)).toBeInTheDocument()
    expect(screen.getByText(/2 dependents/i)).toBeInTheDocument()
    // The dollar-amount rule: T1 must not surface income / expenses inputs.
    expect(screen.queryByText(/\$120,000/)).not.toBeInTheDocument()
  })

  it('renders em-dashes for missing fields', () => {
    render(<ProfileCard profile={{ id: 'u1' }} onSave={async () => {}} />)
    expect(screen.getByText(/age —/i)).toBeInTheDocument()
    expect(screen.getByText(/risk —/i)).toBeInTheDocument()
    expect(screen.getByText(/horizon —/i)).toBeInTheDocument()
  })
})


describe('ProfileCard expanded', () => {
  it('omits untouched sliders from the patch (dirty-tracking)', async () => {
    /** Untouched risk / horizon sliders default to 3, but a user who never
     *  moved them shouldn't be implicitly classified as "balanced" — the
     *  patch should NOT include those fields. The corresponding columns
     *  remain NULL in the DB until the user actually engages the slider. */
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<ProfileCard profile={{ id: 'u1' }} onSave={onSave} />)
    await user.click(screen.getByLabelText(/edit profile/i))

    const ageInput = screen.getByLabelText(/^age$/i) as HTMLInputElement
    await user.clear(ageInput); await user.type(ageInput, '30')

    const region = screen.getByLabelText(/region/i) as HTMLInputElement
    await user.type(region, 'SF Bay Area')

    await user.selectOptions(screen.getByLabelText(/employment status/i), 'employed')

    await user.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledTimes(1)
    const patch = onSave.mock.calls[0][0]
    expect(patch).toMatchObject({
      age: 30,
      employment_status: 'employed',
      region: 'SF Bay Area',
    })
    // Untouched sliders → not in patch.
    expect(patch.risk_tolerance_v2).toBeUndefined()
    expect(patch.time_horizon_v2).toBeUndefined()
    // Legacy dollar fields must not be in the patch.
    expect(patch.annual_income).toBeUndefined()
    expect(patch.monthly_expenses).toBeUndefined()
  })

  it('includes risk slider in patch only when user moves it', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<ProfileCard profile={{ id: 'u1' }} onSave={onSave} />)
    await user.click(screen.getByLabelText(/edit profile/i))

    const slider = screen.getByLabelText(/^risk tolerance$/i) as HTMLInputElement
    // Range inputs in jsdom don't respond to userEvent.keyboard reliably;
    // fireEvent.change directly drives the controlled value, which fires
    // onChange the same way a real drag/keyboard interaction would.
    fireEvent.change(slider, { target: { value: '4' } })

    await user.click(screen.getByRole('button', { name: /save/i }))
    const patch = onSave.mock.calls[0][0]
    expect(patch.risk_tolerance_v2).toBe(4)
    // Untouched horizon stays out.
    expect(patch.time_horizon_v2).toBeUndefined()
  })

  it('starts dirty when profile already has a stored v2 value', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <ProfileCard
        profile={{ id: 'u1', risk_tolerance_v2: 4, time_horizon_v2: 2 }}
        onSave={onSave}
      />,
    )
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.click(screen.getByRole('button', { name: /save/i }))
    const patch = onSave.mock.calls[0][0]
    // Pre-populated values are persisted on save even without further edits.
    expect(patch.risk_tolerance_v2).toBe(4)
    expect(patch.time_horizon_v2).toBe(2)
  })

  it('does not submit when age is invalid', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileCard profile={{ id: 'u1' }} onSave={onSave} />)
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.type(screen.getByLabelText(/^age$/i), '-5')
    await user.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).not.toHaveBeenCalled()
    expect(screen.getByText(/age must be between 0 and 120/i)).toBeInTheDocument()
  })

  it('clears error when user starts correcting the field', async () => {
    const user = userEvent.setup()
    render(<ProfileCard profile={{ id: 'u1' }} onSave={async () => {}} />)
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.type(screen.getByLabelText(/^age$/i), '-5')
    await user.click(screen.getByRole('button', { name: /save/i }))
    expect(screen.getByText(/age must be between 0 and 120/i)).toBeInTheDocument()
    await user.clear(screen.getByLabelText(/^age$/i))
    await user.type(screen.getByLabelText(/^age$/i), '3')
    expect(screen.queryByText(/age must be between 0 and 120/i)).not.toBeInTheDocument()
  })

  it('Cancel button closes form without calling onSave', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileCard profile={{ id: 'u1', age: 40 }} onSave={onSave} />)
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onSave).not.toHaveBeenCalled()
    expect(screen.getByText(/age 40/i)).toBeInTheDocument()  // back to collapsed
  })

  it('empty region submits as null, not empty string', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<ProfileCard profile={{ id: 'u1' }} onSave={onSave} />)
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ region: null }))
  })
})


describe('ProfileCard memory panel', () => {
  it('renders memory fields when expanded and memory is provided', async () => {
    const user = userEvent.setup()
    render(
      <ProfileCard
        profile={{ id: 'u1' }}
        memory={{
          preferences: 'aggressive',
          financial_status: 'NYC',
          financial_goals: 'house',
        }}
        onSave={async () => {}}
        onClearMemory={async () => {}}
      />
    )
    await user.click(screen.getByLabelText(/edit profile/i))
    const dds = Array.from(document.querySelectorAll('dd')).map((el) => el.textContent)
    expect(dds.join(' ')).toMatch(/aggressive/i)
    expect(dds.join(' ')).toMatch(/NYC/i)
    expect(dds.join(' ')).toMatch(/house/i)
  })

  it('calls onClearMemory with confirm', async () => {
    const user = userEvent.setup()
    const onClear = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(
      <ProfileCard
        profile={{ id: 'u1' }}
        memory={{ preferences: 'x' }}
        onSave={async () => {}}
        onClearMemory={onClear}
      />
    )
    await user.click(screen.getByLabelText(/edit profile/i))
    await user.click(screen.getByRole('button', { name: /clear memory/i }))
    expect(onClear).toHaveBeenCalled()
  })
})
