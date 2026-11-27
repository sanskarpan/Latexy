'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    apiClient,
    type AdminExperiment,
    type AdminExperimentComparison,
    type AdminExperimentListResponse,
    type AdminExperimentMetric,
    type AdminExperimentResults,
} from '@/lib/api-client'

const numberFormatter = new Intl.NumberFormat('en-IN')

const STATUS_TONE: Record<AdminExperiment['status'], string> = {
    preregistered: 'border-line bg-surface-2 text-fg-3',
    running: 'border-ok/30 bg-ok/10 text-ok',
    stopped: 'border-err/30 bg-err/10 text-err',
}

const FALLBACK_METRIC_LABELS: Record<string, string> = {
    activation: 'Activation',
    compile_success: 'Compile success',
    checkout_started: 'Checkout started',
    retention_7d: '7-day return',
    compile_error_rate: 'Compile error rate',
    checkout_abandonment_rate: 'Checkout abandonment',
}

function formatCount(value: number | null | undefined): string {
    return Number.isFinite(value ?? NaN) ? numberFormatter.format(Number(value)) : '—'
}

function formatPct(value: number | null | undefined): string {
    return Number.isFinite(value ?? NaN) ? `${Number(value).toFixed(1)}%` : '—'
}

function formatSigned(value: number | null | undefined): string {
    if (!Number.isFinite(value ?? NaN)) return '—'
    const numeric = Number(value)
    return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(1)} pp`
}

function sampleText(experiment: AdminExperiment): string {
    return experiment.sample.variants
        .map(variant =>
            variant.suppressed
                ? `${variant.label}: hidden (<5)`
                : `${variant.label}: ${formatCount(variant.sample_size)}`
        )
        .join(' · ')
}

function claimMetricLabel(
    catalog: AdminExperimentListResponse['catalog'] | undefined,
    key: string
): string {
    return (
        catalog?.metric_definitions.find(metric => metric.key === key)?.label ??
        FALLBACK_METRIC_LABELS[key] ??
        key
    )
}

function MetricTable({
    metric,
    variantOrder,
}: {
    metric: AdminExperimentMetric
    variantOrder: AdminExperiment['variants']
}) {
    const comparisons = new Map<string, AdminExperimentComparison>(
        metric.comparisons.map(comparison => [comparison.variant, comparison])
    )
    return (
        <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-xs">
                <caption className="sr-only">
                    {metric.label} by variant with sample sizes and confidence
                </caption>
                <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="py-2 pr-3 text-left font-semibold">
                            Variant
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Rate
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Sample
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Lift vs control
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            95% CI
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {variantOrder.map(variant => {
                        const cell = metric.cells[variant.key]
                        const comparison = comparisons.get(variant.key)
                        return (
                            <tr key={variant.key} className="border-t border-line align-top">
                                <th scope="row" className="py-2 pr-3 text-left font-normal">
                                    <span className="font-medium text-fg">{variant.label}</span>
                                    <span className="block font-mono text-[10px] text-fg-3">
                                        {variant.key}
                                    </span>
                                </th>
                                <td className="px-3 py-2 text-fg-2">
                                    <span className="font-medium text-fg">
                                        {formatPct(cell?.rate_pct)}
                                    </span>
                                    <span className="block text-[10px] text-fg-3">
                                        {cell
                                            ? `${formatCount(cell.numerator)} of ${formatCount(cell.denominator)}`
                                            : 'No observations'}
                                    </span>
                                </td>
                                <td className="px-3 py-2 text-fg-2">
                                    {cell?.suppressed
                                        ? 'Hidden (<5)'
                                        : formatCount(cell?.denominator)}
                                </td>
                                <td className="px-3 py-2 text-fg-2">
                                    {comparison ? formatSigned(comparison.lift_pp) : 'Reference'}
                                    {comparison?.relative_lift_pct != null ? (
                                        <span className="block text-[10px] text-fg-3">
                                            {comparison.relative_lift_pct >= 0 ? '+' : ''}
                                            {comparison.relative_lift_pct.toFixed(1)}% relative
                                        </span>
                                    ) : null}
                                </td>
                                <td className="px-3 py-2 text-fg-2">
                                    {comparison?.ci_low_pp != null && comparison?.ci_high_pp != null
                                        ? `${comparison.ci_low_pp.toFixed(1)} to ${comparison.ci_high_pp.toFixed(1)} pp`
                                        : '—'}
                                    {comparison?.comparable ? (
                                        <span className="block text-[10px] text-fg-3">
                                            Approximate Wald
                                        </span>
                                    ) : null}
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

function ResultsPanel({
    results,
    loading,
}: {
    results: AdminExperimentResults | null
    loading: boolean
}) {
    if (loading) {
        return <p className="mt-4 text-xs text-fg-3">Loading aggregate results…</p>
    }
    if (!results) return null
    const experiment = results.experiment
    return (
        <section
            aria-live="polite"
            className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4"
        >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold text-fg">Results · {experiment.name}</h4>
                <span className="text-[10px] text-fg-3">
                    {experiment.status} · as of {new Date(results.generated_at).toLocaleString()}
                </span>
            </div>
            <p className="mt-1 text-xs text-fg-2">{results.message}</p>

            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {results.sample.variants.map(variant => (
                    <div
                        key={variant.variant}
                        className="rounded border border-line bg-surface px-3 py-2"
                    >
                        <p className="text-[10px] uppercase tracking-wider text-fg-3">
                            {variant.label}
                        </p>
                        <p className="mt-0.5 text-lg font-semibold text-fg">
                            {variant.suppressed ? '—' : formatCount(variant.sample_size)}
                        </p>
                        <p className="text-[10px] text-fg-3">
                            {variant.suppressed
                                ? 'Hidden under the five-user rule'
                                : 'exposed subjects'}
                        </p>
                    </div>
                ))}
            </div>

            <div className="mt-3 rounded border border-line bg-surface px-3 py-2 text-[11px] text-fg-3">
                {results.sample.minimum_sample_met
                    ? `Minimum sample met (${formatCount(results.sample.minimum_sample_per_variant)} per variant).`
                    : `Minimum sample not met (${formatCount(results.sample.minimum_sample_per_variant)} per variant). No lift or confidence interval is published.`}
            </div>

            <div className="mt-4 rounded border border-line bg-surface p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h5 className="text-xs font-semibold text-fg">
                        Pre-registered primary metric · {results.primary_metric.label}
                    </h5>
                    <span className="text-[10px] text-fg-3">
                        {results.primary_metric.ready ? 'Fixed horizon' : 'Not ready'}
                    </span>
                </div>
                <p className="mt-1 text-[10px] text-fg-3">{results.primary_metric.definition}</p>
                <MetricTable metric={results.primary_metric} variantOrder={experiment.variants} />
            </div>

            {results.guardrails.map(metric => (
                <div key={metric.key} className="mt-3 rounded border border-line bg-surface p-3">
                    <h5 className="text-xs font-semibold text-fg">
                        Guardrail · {metric.label}
                        <span className="ml-2 rounded bg-surface-2 px-1 py-0.5 text-[9px] uppercase tracking-wide text-fg-3">
                            {metric.direction === 'down' ? 'lower is better' : 'higher is better'}
                        </span>
                    </h5>
                    <p className="mt-1 text-[10px] text-fg-3">{metric.definition}</p>
                    <MetricTable metric={metric} variantOrder={experiment.variants} />
                </div>
            ))}

            <div className="mt-4 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
                <p className="font-medium">Claim policy</p>
                <p className="mt-1">{results.claim.peeking}</p>
                <p className="mt-1">{results.claim.winner}</p>
                <p className="mt-1">
                    No automatic rollout. Randomized assignment is fixed-horizon; multiple looks are
                    not corrected.
                </p>
            </div>

            {results.notes.length > 0 ? (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-[10px] text-fg-3">
                    {results.notes.map(note => (
                        <li key={note}>{note}</li>
                    ))}
                </ul>
            ) : null}
        </section>
    )
}

export default function AdminExperiments() {
    const [data, setData] = useState<AdminExperimentListResponse | null>(null)
    const [statusFilter, setStatusFilter] = useState<'all' | AdminExperiment['status']>('all')
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [results, setResults] = useState<AdminExperimentResults | null>(null)
    const [resultsLoading, setResultsLoading] = useState(false)
    const [actionReason, setActionReason] = useState('')
    const [stopRevert, setStopRevert] = useState(true)

    const [key, setKey] = useState('')
    const [name, setName] = useState('')
    const [hypothesis, setHypothesis] = useState('')
    const [primaryMetric, setPrimaryMetric] = useState('checkout_started')
    const [guardrail, setGuardrail] = useState('compile_error_rate')
    const [flagKey, setFlagKey] = useState('')
    const [minimumSample, setMinimumSample] = useState(100)
    const [controlLabel, setControlLabel] = useState('Current experience')
    const [treatmentLabel, setTreatmentLabel] = useState('Variant')
    const [insightUrl, setInsightUrl] = useState('')
    const [createReason, setCreateReason] = useState('')

    const catalog = data?.catalog
    const metricLabels = useMemo(
        () => ({
            primary:
                catalog?.primary_metrics.map(metric => ({
                    key: metric.key,
                    label: metric.label,
                })) ??
                Object.entries(FALLBACK_METRIC_LABELS).map(([metricKey, label]) => ({
                    key: metricKey,
                    label,
                })),
            guardrails:
                catalog?.guardrail_metrics.map(metric => ({
                    key: metric.key,
                    label: metric.label,
                })) ?? [],
        }),
        [catalog]
    )

    const load = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminExperiments({
                status: statusFilter === 'all' ? undefined : statusFilter,
                limit: 100,
            })
            setData(next)
            if (!selectedId && next.experiments.length > 0) setSelectedId(next.experiments[0].id)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load experiments')
        } finally {
            setLoading(false)
        }
    }, [selectedId, statusFilter])

    useEffect(() => {
        void load()
    }, [load])

    const openResults = useCallback(async (experimentId: string) => {
        setSelectedId(experimentId)
        setResults(null)
        setResultsLoading(true)
        setError(null)
        try {
            setResults(await apiClient.getAdminExperimentResults(experimentId))
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load experiment results')
            setResults(null)
        } finally {
            setResultsLoading(false)
        }
    }, [])

    const createExperiment = async () => {
        if (createReason.trim().length < 3) {
            setError('Enter a reason of at least 3 characters before pre-registering.')
            return
        }
        setBusy('create')
        setError(null)
        setNotice(null)
        try {
            const created = await apiClient.createAdminExperiment({
                key: key.trim(),
                name: name.trim(),
                hypothesis: hypothesis.trim(),
                primary_metric: primaryMetric,
                guardrail_metrics: [guardrail],
                variants: [
                    {
                        key: 'control',
                        label: controlLabel.trim() || 'Control',
                        weight: 50,
                        flag_enabled: flagKey ? false : null,
                    },
                    {
                        key: 'treatment',
                        label: treatmentLabel.trim() || 'Treatment',
                        weight: 50,
                        flag_enabled: flagKey ? true : null,
                    },
                ],
                flag_key: flagKey || null,
                posthog_insight_url: insightUrl.trim() || null,
                minimum_sample_per_variant: minimumSample,
                reason: createReason.trim(),
            })
            setNotice(`Pre-registered ${created.key}. Registration is immutable.`)
            setKey('')
            setName('')
            setHypothesis('')
            setInsightUrl('')
            setCreateReason('')
            setSelectedId(created.id)
            setResults(null)
            await load()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not pre-register the experiment')
        } finally {
            setBusy(null)
        }
    }

    const transition = async (experiment: AdminExperiment, action: 'start' | 'stop' | 'revert') => {
        if (actionReason.trim().length < 3) {
            setError('Enter a reason of at least 3 characters for this lifecycle change.')
            return
        }
        setBusy(`${action}:${experiment.id}`)
        setError(null)
        setNotice(null)
        try {
            if (action === 'start') {
                await apiClient.startAdminExperiment(experiment.id, actionReason.trim())
                setNotice(`Started ${experiment.key}. Assignment and exposure are now live.`)
            } else if (action === 'stop') {
                await apiClient.stopAdminExperiment(experiment.id, actionReason.trim(), stopRevert)
                setNotice(
                    `Stopped ${experiment.key}. ${
                        stopRevert ? 'Open assignments were reverted. ' : ''
                    }No flag was changed.`
                )
            } else {
                const reverted = await apiClient.revertAdminExperimentAssignments(
                    experiment.id,
                    actionReason.trim()
                )
                setNotice(
                    `Reverted ${formatCount(reverted.reverted_assignments)} remaining assignment(s) for ${experiment.key}. No flag was changed.`
                )
            }
            await load()
            if (selectedId === experiment.id) await openResults(experiment.id)
        } catch (err) {
            setError(err instanceof Error ? err.message : `Could not ${action} the experiment`)
        } finally {
            setBusy(null)
        }
    }

    return (
        <div className="space-y-5">
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <h3 className="text-sm font-semibold text-fg">Pre-register an experiment</h3>
                <p className="mt-1 text-xs text-fg-3">
                    One primary metric, one or two guardrails and a fixed variant list are frozen at
                    registration. Results are descriptive, require the minimum sample and never roll
                    out a winning variant automatically.
                </p>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <label className="text-[11px] text-fg-2">
                        Experiment key
                        <input
                            value={key}
                            onChange={event => setKey(event.target.value)}
                            placeholder="upgrade_cta_copy"
                            maxLength={64}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Name
                        <input
                            value={name}
                            onChange={event => setName(event.target.value)}
                            placeholder="Upgrade CTA copy"
                            maxLength={160}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2 md:col-span-2">
                        Hypothesis (at least 20 characters)
                        <textarea
                            value={hypothesis}
                            onChange={event => setHypothesis(event.target.value)}
                            rows={3}
                            maxLength={4000}
                            placeholder="A clearer call to action increases checkout starts without raising compile errors."
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Primary metric
                        <select
                            value={primaryMetric}
                            onChange={event => setPrimaryMetric(event.target.value)}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        >
                            {metricLabels.primary.map(metric => (
                                <option key={metric.key} value={metric.key}>
                                    {metric.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Guardrail metric
                        <select
                            value={guardrail}
                            onChange={event => setGuardrail(event.target.value)}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        >
                            {metricLabels.guardrails.map(metric => (
                                <option key={metric.key} value={metric.key}>
                                    {metric.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Linked operational flag (optional)
                        <select
                            value={flagKey}
                            onChange={event => setFlagKey(event.target.value)}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        >
                            <option value="">No flag override</option>
                            {(catalog?.operational_flags ?? []).map(flag => (
                                <option key={flag} value={flag}>
                                    {flag}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Minimum sample per variant
                        <input
                            type="number"
                            min={5}
                            max={1000000}
                            value={minimumSample}
                            onChange={event => setMinimumSample(Number(event.target.value))}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Control label
                        <input
                            value={controlLabel}
                            onChange={event => setControlLabel(event.target.value)}
                            maxLength={80}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Treatment label
                        <input
                            value={treatmentLabel}
                            onChange={event => setTreatmentLabel(event.target.value)}
                            maxLength={80}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2 md:col-span-2">
                        PostHog insight URL (optional, standard PostHog host only)
                        <input
                            value={insightUrl}
                            onChange={event => setInsightUrl(event.target.value)}
                            placeholder="https://us.posthog.com/project/123/insights/abc"
                            maxLength={500}
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2 md:col-span-2">
                        Registration reason
                        <input
                            value={createReason}
                            onChange={event => setCreateReason(event.target.value)}
                            maxLength={1000}
                            placeholder="Ticket or planning reference (required)"
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                </div>

                <button
                    type="button"
                    onClick={() => void createExperiment()}
                    disabled={busy === 'create'}
                    className="mt-4 rounded bg-accent px-3 py-2 text-xs font-medium text-bg disabled:opacity-50"
                >
                    {busy === 'create' ? 'Pre-registering…' : 'Pre-register experiment'}
                </button>
            </div>

            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                        <h3 className="text-sm font-semibold text-fg">Experiment registry</h3>
                        <p className="mt-0.5 text-xs text-fg-3">
                            {data ? `${numberFormatter.format(data.total)} registered` : 'Loading…'}{' '}
                            · five-user suppression applies to every sample
                        </p>
                    </div>
                    <label className="text-[11px] text-fg-2">
                        Status
                        <select
                            value={statusFilter}
                            onChange={event =>
                                setStatusFilter(
                                    event.target.value as 'all' | AdminExperiment['status']
                                )
                            }
                            className="ml-2 rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        >
                            <option value="all">All</option>
                            <option value="preregistered">Pre-registered</option>
                            <option value="running">Running</option>
                            <option value="stopped">Stopped</option>
                        </select>
                    </label>
                </div>

                <div className="mt-3 rounded border border-line bg-surface-2/40 p-3">
                    <label className="block text-[11px] text-fg-2">
                        Lifecycle reason (required to start or stop)
                        <input
                            value={actionReason}
                            onChange={event => setActionReason(event.target.value)}
                            maxLength={1000}
                            placeholder="Ticket, incident or planning reference"
                            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="mt-2 flex items-center gap-2 text-[11px] text-fg-3">
                        <input
                            type="checkbox"
                            checked={stopRevert}
                            onChange={event => setStopRevert(event.target.checked)}
                        />
                        On stop, mark open assignments reverted (no feature flag is changed)
                    </label>
                </div>

                {error ? (
                    <p
                        role="alert"
                        className="mt-3 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"
                    >
                        {error}
                    </p>
                ) : null}
                {notice ? (
                    <p
                        role="status"
                        className="mt-3 rounded border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok"
                    >
                        {notice}
                    </p>
                ) : null}

                {loading ? (
                    <p className="mt-4 text-xs text-fg-3">Loading experiments…</p>
                ) : data && data.experiments.length === 0 ? (
                    <p className="mt-4 text-xs text-fg-3">No experiments registered yet.</p>
                ) : (
                    <div className="mt-4 space-y-3">
                        {data?.experiments.map(experiment => (
                            <article
                                key={experiment.id}
                                className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4"
                            >
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <h4 className="text-sm font-semibold text-fg">
                                                {experiment.name}
                                            </h4>
                                            <span
                                                className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_TONE[experiment.status]}`}
                                            >
                                                {experiment.status}
                                            </span>
                                            {!experiment.registration_intact ? (
                                                <span className="rounded-full border border-err/30 bg-err/10 px-2 py-0.5 text-[10px] text-err">
                                                    Registration hash mismatch
                                                </span>
                                            ) : null}
                                        </div>
                                        <p className="mt-0.5 font-mono text-[11px] text-fg-3">
                                            {experiment.key}
                                        </p>
                                        <p className="mt-1 text-xs text-fg-2">
                                            {experiment.hypothesis}
                                        </p>
                                        <p className="mt-1 text-[10px] text-fg-3">
                                            Primary:{' '}
                                            {claimMetricLabel(catalog, experiment.primary_metric)} ·
                                            Guardrails:{' '}
                                            {experiment.guardrail_metrics
                                                .map(guardrailKey =>
                                                    claimMetricLabel(catalog, guardrailKey)
                                                )
                                                .join(', ')}
                                            {experiment.flag_key
                                                ? ` · Flag: ${experiment.flag_key}`
                                                : ''}
                                        </p>
                                        <p className="mt-1 text-[10px] text-fg-3">
                                            {sampleText(experiment)}
                                        </p>
                                        {experiment.posthog_insight_url ? (
                                            <a
                                                href={experiment.posthog_insight_url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="mt-1 inline-block text-[10px] text-accent underline"
                                            >
                                                Open linked PostHog insight
                                            </a>
                                        ) : null}
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        <button
                                            type="button"
                                            onClick={() => void openResults(experiment.id)}
                                            className="rounded border border-line bg-surface px-3 py-1.5 text-[11px] text-fg-2"
                                        >
                                            Results
                                        </button>
                                        {experiment.status === 'preregistered' ? (
                                            <button
                                                type="button"
                                                onClick={() => void transition(experiment, 'start')}
                                                disabled={busy === `start:${experiment.id}`}
                                                className="rounded border border-ok/30 bg-ok/10 px-3 py-1.5 text-[11px] text-ok disabled:opacity-50"
                                            >
                                                Start
                                            </button>
                                        ) : null}
                                        {experiment.status === 'running' ? (
                                            <button
                                                type="button"
                                                onClick={() => void transition(experiment, 'stop')}
                                                disabled={busy === `stop:${experiment.id}`}
                                                className="rounded border border-err/30 bg-err/10 px-3 py-1.5 text-[11px] text-err disabled:opacity-50"
                                            >
                                                Stop
                                            </button>
                                        ) : null}
                                        {experiment.status === 'stopped' ? (
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    void transition(experiment, 'revert')
                                                }
                                                disabled={busy === `revert:${experiment.id}`}
                                                className="rounded border border-line bg-surface px-3 py-1.5 text-[11px] text-fg-2 disabled:opacity-50"
                                            >
                                                Revert assignments
                                            </button>
                                        ) : null}
                                    </div>
                                </div>
                                {selectedId === experiment.id ? (
                                    <ResultsPanel results={results} loading={resultsLoading} />
                                ) : null}
                            </article>
                        ))}
                    </div>
                )}

                {catalog ? (
                    <details className="mt-4 rounded border border-line bg-surface-2/30 p-3">
                        <summary className="cursor-pointer text-[11px] font-medium text-fg-2">
                            Metric definitions and claim policy
                        </summary>
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-[10px] text-fg-3">
                            {catalog.metric_definitions.map(metric => (
                                <li key={metric.key}>
                                    <span className="font-medium text-fg-2">{metric.label}</span> (
                                    {metric.kind},{' '}
                                    {metric.direction === 'down'
                                        ? 'lower is better'
                                        : 'higher is better'}
                                    ): {metric.definition}
                                </li>
                            ))}
                        </ul>
                        <p className="mt-2 text-[10px] text-fg-3">{catalog.claim.peeking}</p>
                        <p className="mt-1 text-[10px] text-fg-3">{catalog.claim.winner}</p>
                    </details>
                ) : null}
            </div>
        </div>
    )
}
