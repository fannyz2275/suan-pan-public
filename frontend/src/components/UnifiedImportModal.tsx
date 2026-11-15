import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import api, { accountsApi } from '@/lib/api'
import {
  type BankPreview,
  type ConfirmGroup,
  type InvestmentPreview,
  type PreviewGroup,
  confirmStatements,
  detectStatements,
  previewStatements,
} from '@/lib/imports'
import { useImportToast } from '../contexts/ImportToastContext'
import PlaidConnectButton from './PlaidConnectButton'

interface Account {
  id: string
  name: string
  type: string
  account_number_last4?: string | null
}

const ACCOUNT_TYPES = [
  { value: 'checking', label: 'Checking' },
  { value: 'savings', label: 'Savings' },
  { value: 'brokerage', label: 'Brokerage' },
  { value: 'retirement', label: 'Retirement' },
  { value: 'debt', label: 'Debt' },
]

const TXN_CATEGORIES = ['income', 'food', 'transport', 'housing', 'utilities',
  'healthcare', 'entertainment', 'shopping', 'transfer', 'other']

const MAX_ROWS = 10
const MAX_FILES_PER_ROW = 5
const MAX_FILE_MB = 10
const SUPPORTED_EXT = ['.pdf', '.csv', '.txt']

interface Row {
  rowId: string
  accountId: string | ''
  files: File[]
}

interface Props {
  onClose: () => void
  onImported: () => void
  onRequestReview: () => void
  initialAccountId?: string
}

function newRowId(): string {
  return `r_${Math.random().toString(36).slice(2, 9)}`
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export default function UnifiedImportModal({
  onClose, onImported, onRequestReview, initialAccountId,
}: Props) {
  const { showImportToast } = useImportToast()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [accountsError, setAccountsError] = useState(false)
  const [accountLoadAttempt, setAccountLoadAttempt] = useState(0)
  const [rows, setRows] = useState<Row[]>(() => [
    { rowId: newRowId(), accountId: initialAccountId ?? '', files: [] },
  ])
  const [stage, setStage] = useState<'upload' | 'match' | 'preview'>('upload')
  const [confirmedMatches, setConfirmedMatches] = useState<Record<string, boolean>>({})
  const [excludedSections, setExcludedSections] = useState<Record<string, boolean>>({})
  const [sharedReviewed, setSharedReviewed] = useState(false)
  const [multipleAccounts, setMultipleAccounts] = useState(false)
  const [groups, setGroups] = useState<PreviewGroup[]>([])
  const [busy, setBusy] = useState(false)
  const [globalError, setGlobalError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setAccountsLoading(true)
    setAccountsError(false)
    api.get<Account[]>('/finance/accounts', { timeout: 15000 }).then((r) => {
      if (!cancelled) setAccounts(r.data)
    }).catch(() => {
      if (!cancelled) setAccountsError(true)
    }).finally(() => {
      if (!cancelled) setAccountsLoading(false)
    })
    return () => { cancelled = true }
  }, [accountLoadAttempt])

  const validRows = useMemo(
    () => rows.filter((r) => r.files.length > 0),
    [rows],
  )

  const handleAddRow = () => {
    if (rows.length >= MAX_ROWS) return
    setRows((prev) => [...prev, { rowId: newRowId(), accountId: '', files: [] }])
  }
  const handleRemoveRow = (rowId: string) => {
    setRows((prev) => prev.length === 1 ? prev : prev.filter((r) => r.rowId !== rowId))
  }
  const updateRow = (rowId: string, patch: Partial<Row>) => {
    setRows((prev) => prev.map((r) => r.rowId === rowId ? { ...r, ...patch } : r))
  }

  const handlePreview = async () => {
    setGlobalError(null)
    if (validRows.length === 0) {
      setGlobalError('Select at least one file.')
      return
    }
    setBusy(true)
    try {
      const files = validRows.flatMap((row) => row.files)
      if (files.length > MAX_FILES_PER_ROW) throw new Error('Upload at most 5 files at a time.')
      if (!multipleAccounts && validRows.some((row) => !row.accountId)) throw new Error('Choose an account for each statement first.')
      const res = multipleAccounts ? await detectStatements(files) : await previewStatements(validRows)
      setGroups(res.groups)
      setConfirmedMatches(multipleAccounts ? {} : Object.fromEntries(res.groups.map((g) => [g.row_id, true])))
      setExcludedSections({})
      setSharedReviewed(false)
      setStage(multipleAccounts ? 'match' : 'preview')
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setGlobalError(msg ?? (e instanceof Error ? e.message : 'Failed to parse. Try again or check the files.'))
    } finally {
      setBusy(false)
    }
  }

  const updateGroupBank = (rowId: string, updater: (p: BankPreview) => BankPreview) => {
    setGroups((prev) => prev.map((g) => {
      if (g.row_id !== rowId || g.kind !== 'bank' || !g.preview) return g
      return { ...g, preview: updater(g.preview as BankPreview) }
    }))
  }
  const updateGroupInv = (rowId: string, updater: (p: InvestmentPreview) => InvestmentPreview) => {
    setGroups((prev) => prev.map((g) => {
      if (g.row_id !== rowId || g.kind !== 'investment' || !g.preview) return g
      return { ...g, preview: updater(g.preview as InvestmentPreview) }
    }))
  }
  const handleRemoveGroup = (rowId: string) => {
    setGroups((prev) => prev.filter((g) => g.row_id !== rowId))
  }

  const handleSave = async () => {
    setGlobalError(null)
    if (groups.some((g) => !excludedSections[g.row_id] && (g.error || !g.account_id || !confirmedMatches[g.row_id]))) {
      setGlobalError('Confirm the destination for every account section first.')
      return
    }
    const payload: ConfirmGroup[] = []
    for (const g of groups) {
      if (excludedSections[g.row_id] || g.error || !g.preview) continue
      if (g.kind === 'bank') {
        const p = g.preview as BankPreview
        payload.push({
          row_id: g.row_id, account_id: g.account_id, kind: 'bank',
          detected_type: g.account_type, destination_confirmed: confirmedMatches[g.row_id],
          balance: p.balance, statement_date: p.statement_date,
          transactions: p.transactions,
        })
      } else {
        const p = g.preview as InvestmentPreview
        payload.push({
          row_id: g.row_id, account_id: g.account_id, kind: 'investment',
          detected_type: g.account_type, destination_confirmed: confirmedMatches[g.row_id],
          statement_date: p.statement_date, cash_value: p.cash_value,
          holdings: p.holdings, investment_transactions: p.investment_transactions,
        })
      }
    }
    if (payload.length === 0) {
      setGlobalError('Nothing to save — every group has an error or was removed.')
      return
    }
    setBusy(true)
    try {
      // Apply older statements first so the latest dated balance wins.
      payload.sort((a, b) => (a.statement_date ?? '').localeCompare(b.statement_date ?? ''))
      const res = await confirmStatements(payload)
      const failed = res.saved.filter((row) => row.error)
      if (failed.length || !res.ok) {
        const failedIds = new Set(failed.map((row) => row.row_id))
        setGroups((previous) => previous.filter((g) => failedIds.has(g.row_id)))
        setGlobalError('Some sections could not be saved. Successfully saved sections were removed; review the remaining sections before retrying.')
        onImported()
        return
      }
      const totalTxns = res.saved.reduce((s, r) => s + (r.transactions_created ?? 0), 0)
      const snaps = res.saved.filter((r) => r.snapshot_id).length
      const parts: string[] = []
      if (totalTxns > 0) parts.push(`${totalTxns} transaction${totalTxns === 1 ? '' : 's'}`)
      if (snaps > 0) parts.push(`${snaps} snapshot${snaps === 1 ? '' : 's'}`)
      const what = parts.length > 0 ? parts.join(' and ') : 'changes'
      showImportToast({
        message: `Saved ${what}.`,
        transferCount: res.transfer_candidates_added,
        onReview: res.transfer_candidates_added > 0 ? onRequestReview : undefined,
      })
      onImported()
      onClose()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setGlobalError(msg ?? 'Failed to save. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      data-testid="unified-import-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="bg-background rounded-xl border shadow-xl w-full max-w-3xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="font-semibold text-lg">Import statements</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto min-h-0 flex-1 px-6 py-4 space-y-4">
          {accountsLoading && <p role="status" className="text-sm text-muted-foreground">Loading accounts...</p>}
          {accountsError && (
            <div role="alert" className="text-sm text-destructive">
              <p>Could not load accounts. Check your connection and try again.</p>
              <Button variant="outline" onClick={() => setAccountLoadAttempt((value) => value + 1)}>Retry accounts</Button>
            </div>
          )}
          {stage === 'upload' ? (
            <>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={multipleAccounts} disabled={busy} onChange={(e) => setMultipleAccounts(e.target.checked)} />This file contains multiple accounts</label>
            <UploadStage
              rows={rows}
              accounts={accounts}
              multipleAccounts={multipleAccounts}
              onAddRow={handleAddRow}
              onRemoveRow={handleRemoveRow}
              onUpdateRow={updateRow}
              onAccountCreated={(a) => setAccounts((prev) => [...prev, a])}
            />
            </>
          ) : stage === 'match' ? (
            <div className="space-y-4">
              <h3 className="font-medium">Review account matches</h3>
              {groups.some((g) => g.document_notices?.length) && <div className="space-y-2 border-b pb-3">
                <p className="text-sm font-medium">Shared document content excluded from account entries</p>
                <ul className="text-xs text-muted-foreground">
                  {[...new Set(groups.flatMap((g) => (g.document_notices ?? []).map((n) => `${g.source_file}: ${n.role}, lines ${n.ranges.map((r) => r.join('-')).join(', ')}${n.excerpt ? ` — ${n.excerpt}` : ''}`)))].map((notice) => <li className="whitespace-pre-wrap break-words" key={notice}>{notice}</li>)}
                </ul>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sharedReviewed} onChange={(e) => setSharedReviewed(e.target.checked)} />I reviewed the shared content exclusions</label>
              </div>}
              {groups.map((group) => (
                <section key={group.row_id} className="border-b pb-4 space-y-2">
                  <p className="font-medium">{group.account_name} · {group.account_type}{group.detected_last4 ? ` · **${group.detected_last4}` : ' · Number unavailable'}</p>
                  <p className="text-xs text-muted-foreground">{group.source_file}</p>
                  {group.error ? <div className="space-y-2">
                    <p className="text-sm font-medium">Needs review</p>
                    <p role="alert" className="text-sm text-destructive">{group.error} <button className="underline" onClick={() => window.dispatchEvent(new Event('open-ai-providers'))}>AI provider settings</button></p>
                    {group.source_ranges && <p className="text-xs">Source lines: {group.source_ranges.map((r) => r.join('-')).join(', ')}</p>}
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!excludedSections[group.row_id]} onChange={(e) => setExcludedSections((previous) => ({ ...previous, [group.row_id]: e.target.checked }))} />Exclude this unresolved section from this import</label>
                  </div> : <>
                  <RowEditor
                    row={{ rowId: group.row_id, accountId: group.account_id, files: [] }}
                    accounts={accounts.filter((a) => a.type === group.account_type)}
                    removable={false} mappingOnly detectedLast4={group.detected_last4}
                    detectedType={group.account_type}
                    onRemove={() => {}}
                    onChange={(patch) => {
                      setGroups((previous) => previous.map((g) => g.row_id === group.row_id ? { ...g, account_id: patch.accountId ?? '' } : g))
                      setConfirmedMatches((previous) => ({ ...previous, [group.row_id]: false }))
                    }}
                    onAccountCreated={(account) => {
                      setAccounts((previous) => [...previous, account])
                      setGroups((previous) => previous.map((g) => g.row_id === group.row_id ? { ...g, account_id: account.id } : g))
                      setConfirmedMatches((previous) => ({ ...previous, [group.row_id]: false }))
                    }}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" disabled={!group.account_id} checked={!!confirmedMatches[group.row_id]}
                      onChange={(event) => setConfirmedMatches((previous) => ({ ...previous, [group.row_id]: event.target.checked }))} />
                    Confirm this account destination
                  </label>
                  </>}
                </section>
              ))}
            </div>
          ) : (
            <PreviewStage
              groups={groups.filter((g) => !excludedSections[g.row_id]).map((g) => ({ ...g, account_name: accounts.find((a) => a.id === g.account_id)?.name ?? g.account_name }))}
              onBack={() => setStage('match')}
              onRemoveGroup={handleRemoveGroup}
              onBankPreviewChange={updateGroupBank}
              onInvPreviewChange={updateGroupInv}
            />
          )}
          {globalError && (
            <p className="text-sm text-destructive" role="alert">{globalError} <button className="underline" onClick={() => window.dispatchEvent(new Event('open-ai-providers'))}>AI provider settings</button></p>
          )}
        </div>

        <div className="shrink-0 px-6 py-4 border-t flex justify-end gap-2">
          {stage === 'upload' ? (
            <>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button
                data-testid="unified-preview-btn"
                onClick={handlePreview}
                disabled={busy || accountsLoading || accountsError || validRows.length === 0 || (!multipleAccounts && validRows.some((row) => !row.accountId))}
              >
                {busy ? 'Parsing statements...' : multipleAccounts ? 'Match accounts' : 'Preview statements'}
              </Button>
            </>
          ) : stage === 'match' ? (
            <>
              <Button variant="outline" onClick={() => setStage('upload')}>Back</Button>
              <Button disabled={!groups.some((g) => !g.error && g.preview && !excludedSections[g.row_id]) || groups.some((g) => !excludedSections[g.row_id] && (g.error || !g.account_id || !confirmedMatches[g.row_id])) || (groups.some((g) => g.document_notices?.length) && !sharedReviewed)}
                onClick={() => setStage('preview')}>Preview statements</Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => setStage(multipleAccounts ? 'match' : 'upload')}>← Back</Button>
              <Button
                data-testid="unified-save-btn"
                onClick={handleSave}
                disabled={busy || groups.filter((g) => !g.error && g.preview).length === 0}
              >
                {busy ? 'Saving…' : 'Save all'}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

interface UploadStageProps {
  multipleAccounts: boolean
  rows: Row[]
  accounts: Account[]
  onAddRow: () => void
  onRemoveRow: (rowId: string) => void
  onUpdateRow: (rowId: string, patch: Partial<Row>) => void
  onAccountCreated: (a: Account) => void
}

function UploadStage({
  rows, accounts, onAddRow, onRemoveRow, onUpdateRow, onAccountCreated, multipleAccounts,
}: UploadStageProps) {
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Statements
      </p>

      <div className="space-y-3">
        {rows.map((row) => (
          <RowEditor
            key={row.rowId}
            row={row}
            accounts={accounts}
            showAccount={!multipleAccounts}
            removable={rows.length > 1}
            onChange={(patch) => onUpdateRow(row.rowId, patch)}
            onRemove={() => onRemoveRow(row.rowId)}
            onAccountCreated={(a) => {
              onAccountCreated(a)
              onUpdateRow(row.rowId, { accountId: a.id })
            }}
          />
        ))}
      </div>

      <Button
        variant="outline"
        size="sm"
        onClick={onAddRow}
        disabled={rows.length >= MAX_ROWS}
        data-testid="unified-add-row"
      >
        + Add more files
      </Button>

      <div className="pt-2 border-t">
        <p className="text-sm text-muted-foreground mb-2">— or —</p>
        <p className="text-sm mb-2">Connect a bank or brokerage automatically:</p>
        <PlaidConnectButton onConnected={() => { /* parent refreshes on close */ }} />
      </div>
    </>
  )
}

interface RowEditorProps {
  row: Row
  accounts: Account[]
  removable: boolean
  onChange: (patch: Partial<Row>) => void
  onRemove: () => void
  onAccountCreated: (a: Account) => void
  mappingOnly?: boolean
  showAccount?: boolean
  detectedLast4?: string | null
  detectedType?: string
}

function RowEditor({ row, accounts, removable, onChange, onRemove, onAccountCreated, mappingOnly = false, showAccount = false, detectedLast4, detectedType }: RowEditorProps) {
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState(detectedType ?? 'checking')
  const [savingNew, setSavingNew] = useState(false)
  const [createErr, setCreateErr] = useState<string | null>(null)
  const [fileErr, setFileErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const fileInputId = useId()

  const addFiles = (incoming: FileList | File[]) => {
    const list = Array.from(incoming)
    if (list.length === 0) return
    const merged: File[] = [...row.files]
    const seen = new Set(merged.map((f) => `${f.name}::${f.size}`))
    const rejected: string[] = []
    for (const f of list) {
      const key = `${f.name}::${f.size}`
      if (seen.has(key)) continue
      const name = f.name.toLowerCase()
      if (!SUPPORTED_EXT.some((e) => name.endsWith(e))) {
        rejected.push(`${f.name} — only PDF, CSV, or TXT supported`)
        continue
      }
      if (f.size > MAX_FILE_MB * 1024 * 1024) {
        rejected.push(`${f.name} — exceeds ${MAX_FILE_MB} MB limit`)
        continue
      }
      if (merged.length >= MAX_FILES_PER_ROW) {
        rejected.push(`${f.name} — row is full (max ${MAX_FILES_PER_ROW} files)`)
        continue
      }
      merged.push(f); seen.add(key)
    }
    setFileErr(rejected.length > 0 ? rejected.join('; ') : null)
    onChange({ files: merged })
  }
  const removeFile = (idx: number) => onChange({ files: row.files.filter((_, i) => i !== idx) })

  const handleCreate = async () => {
    setCreateErr(null)
    if (!newName.trim()) { setCreateErr('Name is required.'); return }
    setSavingNew(true)
    try {
      const created = await accountsApi.create({
        name: newName.trim(),
        type: newType,
        balance: 0,
        account_number_last4: detectedLast4 ?? null,
      } as Partial<Account>) as unknown as Account
      onAccountCreated(created)
      setCreating(false)
      setNewName('')
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateErr(msg ?? 'Could not create account.')
    } finally {
      setSavingNew(false)
    }
  }

  return (
    <div data-testid="unified-row" className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2">
        {(mappingOnly || showAccount) && (
        <select
          data-testid="unified-row-account"
          aria-label="Destination account"
          value={row.accountId}
          onChange={(e) => {
            if (e.target.value === '__new__') { setCreating(true); return }
            onChange({ accountId: e.target.value })
          }}
          className="min-w-0 w-full flex-1 text-sm border rounded px-2 py-1 bg-background"
        >
          <option value="">Select account…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.type}){a.account_number_last4 ? ` **${a.account_number_last4}` : ''}
            </option>
          ))}
          <option value="__new__">+ New account…</option>
        </select>
        )}
        {removable && (
          <button
            onClick={onRemove}
            className="text-muted-foreground hover:text-destructive text-sm"
            aria-label="Remove row"
            data-testid="unified-row-remove"
          >×</button>
        )}
      </div>

      {creating && (
        <div className="border-l-2 border-primary pl-3 space-y-2">
          <div className="flex gap-2">
            <Input
              placeholder="Account name (e.g. Chase Checking)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              data-testid="unified-new-name"
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="text-sm border rounded px-2 bg-background"
              data-testid="unified-new-type"
              disabled={!!detectedType}
            >
              {ACCOUNT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          {createErr && <p className="text-xs text-destructive">{createErr}</p>}
          <div className="flex gap-2 justify-end">
            <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={savingNew} data-testid="unified-new-save">
              {savingNew ? 'Creating…' : 'Create account'}
            </Button>
          </div>
        </div>
      )}

      {/*
        Use <label htmlFor> so the browser opens the file picker natively
        when the dropzone is clicked. A div + programmatic .click() on a
        nested <input> creates a click-event loop (the input's bubbling
        click re-triggers the wrapper's onClick), causing the picker to
        be requested multiple times in a row.
      */}
      {!mappingOnly && <>
      <label
        htmlFor={fileInputId}
        className="block border-2 border-dashed rounded-lg px-4 py-3 text-center cursor-pointer hover:border-primary transition-colors"
      >
        <p className="text-xs text-muted-foreground">
          {row.files.length === 0 ? 'Click to select statement(s)' : 'Click to add more files'} — PDF, CSV, TXT · max {MAX_FILE_MB}MB each · up to {MAX_FILES_PER_ROW}
        </p>
      </label>
      <input
        id={fileInputId}
        ref={fileRef}
        type="file"
        accept=".pdf,.csv,.txt"
        multiple
        data-testid="unified-row-files"
        style={{
          position: 'absolute', width: 1, height: 1,
          padding: 0, margin: -1, overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)', whiteSpace: 'nowrap', borderWidth: 0,
        }}
        onChange={(e) => {
          if (e.target.files) addFiles(e.target.files)
          e.target.value = ''
        }}
      />
      {fileErr && (
        <p
          role="alert"
          data-testid="unified-row-file-error"
          className="text-xs text-destructive"
        >
          {fileErr}
        </p>
      )}

      {row.files.length > 0 && (
        <div className="space-y-1">
          {row.files.map((f, i) => (
            <div key={`${f.name}-${i}`} className="flex items-center gap-2 border rounded px-3 py-1.5 text-xs">
              <span className="flex-1 truncate">{f.name}</span>
              <span className="text-muted-foreground">{(f.size / 1024).toFixed(0)} KB</span>
              <button onClick={() => removeFile(i)} className="text-muted-foreground hover:text-destructive">×</button>
            </div>
          ))}
        </div>
      )}
      </>}
    </div>
  )
}

interface PreviewStageProps {
  groups: PreviewGroup[]
  onBack: () => void
  onRemoveGroup: (rowId: string) => void
  onBankPreviewChange: (rowId: string, updater: (p: BankPreview) => BankPreview) => void
  onInvPreviewChange: (rowId: string, updater: (p: InvestmentPreview) => InvestmentPreview) => void
}

function PreviewStage({
  groups, onRemoveGroup, onBankPreviewChange, onInvPreviewChange,
}: PreviewStageProps) {
  if (groups.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to preview.</p>
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Review each statement below. Sort, edit, or remove rows before saving.
      </p>
      {groups.map((g) => (
        <PreviewCard
          key={g.row_id}
          group={g}
          onRemove={() => onRemoveGroup(g.row_id)}
          onBankChange={(updater) => onBankPreviewChange(g.row_id, updater)}
          onInvChange={(updater) => onInvPreviewChange(g.row_id, updater)}
        />
      ))}
    </div>
  )
}

interface PreviewCardProps {
  group: PreviewGroup
  onRemove: () => void
  onBankChange: (updater: (p: BankPreview) => BankPreview) => void
  onInvChange: (updater: (p: InvestmentPreview) => InvestmentPreview) => void
}

function PreviewCard({ group, onRemove, onBankChange, onInvChange }: PreviewCardProps) {
  return (
    <div data-testid="preview-card" className="border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-muted/40 border-b">
        <div>
          <p className="text-sm font-semibold">{group.account_name}</p>
          <p className="text-xs text-muted-foreground">{group.account_type} · {group.kind}</p>
          {group.source_file && <p className="text-xs text-muted-foreground break-all">{group.source_file}{group.detected_last4 ? ` · **${group.detected_last4}` : ''}</p>}
        </div>
        <button
          onClick={onRemove}
          className="text-xs underline text-muted-foreground hover:text-destructive"
          data-testid="preview-card-remove"
        >Remove</button>
      </div>
      <div className="p-3 space-y-3">
        {group.error ? (
          <p className="text-sm text-destructive">{group.error} <button className="underline" onClick={() => window.dispatchEvent(new Event('open-ai-providers'))}>AI provider settings</button></p>
        ) : group.kind === 'bank' && group.preview ? (
          <BankCardBody
            preview={group.preview as BankPreview}
            onChange={onBankChange}
          />
        ) : group.kind === 'investment' && group.preview ? (
          <InvestmentCardBody
            preview={group.preview as InvestmentPreview}
            onChange={onInvChange}
          />
        ) : null}
      </div>
    </div>
  )
}

type BankSort = 'date-desc' | 'date-asc' | 'amount-desc' | 'amount-asc'

function BankCardBody({
  preview, onChange,
}: { preview: BankPreview; onChange: (updater: (p: BankPreview) => BankPreview) => void }) {
  const [sort, setSort] = useState<BankSort>('date-desc')

  const sorted = useMemo(() => {
    const indexed = preview.transactions.map((t, i) => ({ t, i }))
    const cmp: Record<BankSort, (a: typeof indexed[number], b: typeof indexed[number]) => number> = {
      'date-desc': (a, b) => b.t.date.localeCompare(a.t.date),
      'date-asc': (a, b) => a.t.date.localeCompare(b.t.date),
      'amount-desc': (a, b) => b.t.amount - a.t.amount,
      'amount-asc': (a, b) => a.t.amount - b.t.amount,
    }
    return [...indexed].sort(cmp[sort])
  }, [preview.transactions, sort])

  const removeTxn = (idx: number) => onChange((p) => ({
    ...p, transactions: p.transactions.filter((_, i) => i !== idx),
  }))
  const updateTxn = (idx: number, patch: Partial<BankPreview['transactions'][number]>) => onChange((p) => ({
    ...p,
    transactions: p.transactions.map((t, i) => i === idx ? { ...t, ...patch } : t),
  }))

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted-foreground">Statement balance:</span>
        <input
          type="number"
          value={preview.balance ?? ''}
          onChange={(e) => onChange((p) => ({ ...p, balance: e.target.value === '' ? null : parseFloat(e.target.value) }))}
          className="w-32 border rounded px-2 py-1 bg-background text-right"
          data-testid="bank-balance"
        />
        {preview.statement_date && (
          <Badge variant="secondary">as of {preview.statement_date}</Badge>
        )}
      </div>
      <div className="flex flex-wrap gap-2 items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Transactions ({preview.transactions.length})
        </h4>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as BankSort)}
          className="text-xs border rounded px-1.5 py-0.5 bg-background"
          data-testid="bank-txn-sort"
        >
          <option value="date-desc">Date (newest first)</option>
          <option value="date-asc">Date (oldest first)</option>
          <option value="amount-desc">Amount (high → low)</option>
          <option value="amount-asc">Amount (low → high)</option>
        </select>
      </div>
      <div className="space-y-1 max-h-72 overflow-y-auto pr-1">
        {sorted.map(({ t, i }) => (
          <div key={i} className="flex flex-wrap items-center gap-2 border rounded px-2 py-1 text-xs">
            <span className="w-20 text-muted-foreground">{t.date}</span>
            <span className="flex-1 min-w-24 truncate">{t.description}</span>
            <select
              value={t.category ?? 'other'}
              onChange={(e) => updateTxn(i, { category: e.target.value })}
              className="border rounded px-1 py-0.5 bg-background"
            >
              {TXN_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
            <input
              type="number"
              value={t.amount}
              onChange={(e) => updateTxn(i, { amount: parseFloat(e.target.value) || 0 })}
              className={`w-24 text-right border rounded px-1 py-0.5 bg-background ${t.amount < 0 ? 'text-destructive' : 'text-green-700'}`}
            />
            <button onClick={() => removeTxn(i)} className="text-muted-foreground hover:text-destructive">×</button>
          </div>
        ))}
      </div>
    </>
  )
}

type HoldingsSort = 'ticker' | 'mv-desc' | 'mv-asc'
type InvTxnSort = 'date-desc' | 'date-asc' | 'amount-desc' | 'amount-asc'

function InvestmentCardBody({
  preview, onChange,
}: { preview: InvestmentPreview; onChange: (updater: (p: InvestmentPreview) => InvestmentPreview) => void }) {
  const [hSort, setHSort] = useState<HoldingsSort>('mv-desc')
  const [tSort, setTSort] = useState<InvTxnSort>('date-desc')

  const totalMV = preview.holdings.reduce((s, h) => s + h.market_value, 0)
  const computed = preview.cash_value + totalMV
  const reported = preview.total_value_reported ?? null
  const tol = reported != null ? Math.max(Math.abs(reported) * 0.01, 1) : 0
  const tieOut: 'match' | 'mismatch' | null =
    reported == null ? null : Math.abs(computed - reported) <= tol ? 'match' : 'mismatch'

  const holdings = useMemo(() => {
    const indexed = preview.holdings.map((h, i) => ({ h, i }))
    const cmp: Record<HoldingsSort, (a: typeof indexed[number], b: typeof indexed[number]) => number> = {
      ticker: (a, b) => a.h.ticker.localeCompare(b.h.ticker),
      'mv-desc': (a, b) => b.h.market_value - a.h.market_value,
      'mv-asc': (a, b) => a.h.market_value - b.h.market_value,
    }
    return [...indexed].sort(cmp[hSort])
  }, [preview.holdings, hSort])

  const txns = useMemo(() => {
    const indexed = preview.investment_transactions.map((t, i) => ({ t, i }))
    const cmp: Record<InvTxnSort, (a: typeof indexed[number], b: typeof indexed[number]) => number> = {
      'date-desc': (a, b) => b.t.date.localeCompare(a.t.date),
      'date-asc': (a, b) => a.t.date.localeCompare(b.t.date),
      'amount-desc': (a, b) => b.t.amount - a.t.amount,
      'amount-asc': (a, b) => a.t.amount - b.t.amount,
    }
    return [...indexed].sort(cmp[tSort])
  }, [preview.investment_transactions, tSort])

  return (
    <>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <Cell label="Statement date" value={preview.statement_date} />
        <label className="text-sm">Cash outside holdings
          <input aria-label="Cash outside holdings" type="number" step="0.01"
            className="block w-full min-w-0 border rounded px-2 py-1 bg-background"
            value={preview.cash_value}
            onChange={(e) => { const value = Number(e.target.value); if (Number.isFinite(value)) onChange((p) => ({ ...p, cash_value: value })) }} />
        </label>
        <Cell label="Total (computed)" value={fmtUsd(computed)} />
        {preview.account_hint && (
          <div className="col-span-3 text-xs text-muted-foreground">Hint: {preview.account_hint}</div>
        )}
      </div>
      {!!preview.cash_in_holdings && <p className="text-xs text-muted-foreground">Reported cash: {fmtUsd(preview.reported_cash_value)}. Already included in holdings: {fmtUsd(preview.cash_in_holdings)}.</p>}
      {tieOut === 'mismatch' && reported != null && (
        <div className="bg-amber-50 border border-amber-300 rounded p-2 text-xs text-amber-900" data-testid="tie-out-banner">
          ⚠ Tie-out mismatch: statement reports <b>{fmtUsd(reported)}</b>, computed <b>{fmtUsd(computed)}</b>.
        </div>
      )}
      {tieOut === 'match' && (
        <div className="text-xs text-green-700" data-testid="tie-out-match">✓ Tie-out matches statement total.</div>
      )}

      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Holdings ({preview.holdings.length})
        </h4>
        <select
          value={hSort}
          onChange={(e) => setHSort(e.target.value as HoldingsSort)}
          className="text-xs border rounded px-1.5 py-0.5 bg-background"
          data-testid="inv-holdings-sort"
        >
          <option value="mv-desc">Market value (high → low)</option>
          <option value="mv-asc">Market value (low → high)</option>
          <option value="ticker">Ticker (A → Z)</option>
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground border-b">
            <tr><th className="py-1 text-left">Ticker</th><th className="py-1 text-right">Qty</th><th className="py-1 text-right">Price</th><th className="py-1 text-right">Market value</th></tr>
          </thead>
          <tbody>
            {holdings.map(({ h, i }) => (
              <tr key={`${h.ticker}-${i}`} className="border-b last:border-0">
                <td className="py-1 font-mono">{h.ticker}</td>
                <td className="py-1 text-right">{h.quantity.toFixed(4)}</td>
                <td className="py-1 text-right">{fmtUsd(h.price)}</td>
                <td className="py-1 text-right">{fmtUsd(h.market_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {preview.investment_transactions.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Investment transactions ({preview.investment_transactions.length})
            </h4>
            <select
              value={tSort}
              onChange={(e) => setTSort(e.target.value as InvTxnSort)}
              className="text-xs border rounded px-1.5 py-0.5 bg-background"
              data-testid="inv-txn-sort"
            >
              <option value="date-desc">Date (newest first)</option>
              <option value="date-asc">Date (oldest first)</option>
              <option value="amount-desc">Amount (high → low)</option>
              <option value="amount-asc">Amount (low → high)</option>
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground border-b">
                <tr><th className="py-1 text-left">Date</th><th className="py-1 text-left">Type</th><th className="py-1 text-left">Ticker</th><th className="py-1 text-right">Qty</th><th className="py-1 text-right">Amount</th></tr>
              </thead>
              <tbody>
                {txns.map(({ t, i }) => (
                  <tr key={`${t.date}-${i}`} className="border-b last:border-0">
                    <td className="py-1">{t.date}</td>
                    <td className="py-1">{t.type}</td>
                    <td className="py-1 font-mono">{t.ticker ?? ''}</td>
                    <td className="py-1 text-right">{t.quantity != null ? t.quantity.toFixed(4) : '—'}</td>
                    <td className={`py-1 text-right ${t.amount < 0 ? 'text-destructive' : 'text-green-700'}`}>
                      {fmtUsd(t.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  )
}
