'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminPathAnalysisResponse,
    type AdminPathAnalysisSection,
} from '@/lib/api-client'
import {
    filterSectionByNode,
    layoutSankey,
    type SankeyLinkLayout,
    type SankeyNodeLayout,
} from '@/lib/admin/path-sankey'
import { formatNumber } from './admin-format'

const PLAN_OPTIONS = ['', 'free', 'basic', 'pro', 'byok', 'team'] as const
const COHORT_OPTIONS = [
    { value: 'all', label: 'All accounts' },
    { value: 'new', label: 'New (≤30 days)' },
    { value: 'established', label: 'Established (>30 days)' },
] as const

const OUTCOME_TABS = [
    { key: 'upgrade', label: 'Before upgrade' },
    { key: 'churn', label: 'Before churn' },
] as const

const TONES: Record<string, { fill: string; text: string; soft: string }> = {
    route: { fill: '#4f46e5', text: 'text-indigo-600', soft: 'bg-indigo-500/10' },
    upgrade: { fill: '#15803d', text: 'text-emerald-700', soft: 'bg-emerald-500/10' },
    churn: { fill: '#b91c1c', text: 'text-red-700', soft: 'bg-red-500/10' },
    missing: { fill: '#64748b', text: 'text-slate-600', soft: 'bg-slate-500/10' },
}

function count(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : formatNumber(value)
}

function pct(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
    return (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
            {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
        </div>
    )
}

function MissingPathNotice({ section }: { section: AdminPathAnalysisSection }) {
    if (section.status !== 'visible') return null
    if (section.missing_path_outcomes == null) {
        return (
            <p className="rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
                Missing route data for this section is below the five-user floor, so its exact count
                is suppressed. No transition was invented for those outcomes.
            </p>
        )
    }
    if (section.missing_path_outcomes === 0) return null
    return (
        <p className="rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            Path data missing for {formatNumber(section.missing_path_outcomes)} outcome
            {section.missing_path_outcomes === 1 ? '' : 's'}. They are shown as a labelled
            “Path data missing” node and are never given an inferred route.
        </p>
    )
}

function SankeyNode({
    node,
    selected,
    onSelect,
}: {
    node: SankeyNodeLayout
    selected: boolean
    onSelect: (nodeId: string) => void
}) {
    const tone = TONES[node.tone] ?? TONES.route
    const label = node.label.length > 24 ? `${node.label.slice(0, 23)}…` : node.label
    return (
        <g
            role="button"
            tabIndex={0}
            aria-label={`${node.label}: ${node.count} transitions, ${node.users} users. Filter to this node.`}
            aria-pressed={selected}
            onClick={() => onSelect(node.id)}
            onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect(node.id)
                }
            }}
            className="cursor-pointer focus:outline-none"
        >
            <title>
                {node.label}: {node.count} transitions · {node.users} distinct users
            </title>
            <rect
                x={node.x}
                y={node.y}
                width={node.width}
                height={Math.max(10, node.height)}
                rx={4}
                fill={tone.fill}
                opacity={selected ? 1 : 0.86}
                stroke={selected ? '#111827' : 'transparent'}
                strokeWidth={2}
            />
            <text
                x={node.x + 6}
                y={node.y + Math.min(Math.max(12, node.height / 2 + 4), node.height - 3)}
                fontSize={10}
                fill="#ffffff"
                className="pointer-events-none select-none"
            >
                {label}
            </text>
            <text
                x={node.x + node.width - 6}
                y={node.y + Math.min(Math.max(12, node.height / 2 + 4), node.height - 3)}
                fontSize={10}
                fill="#ffffff"
                textAnchor="end"
                className="pointer-events-none select-none"
            >
                {formatNumber(node.count)}
            </text>
        </g>
    )
}

function SankeyGraph({
    section,
    selectedNode,
    onSelectNode,
}: {
    section: AdminPathAnalysisSection
    selectedNode: string | null
    onSelectNode: (nodeId: string) => void
}) {
    const filtered = useMemo(() => filterSectionByNode(section, selectedNode), [section, selectedNode])
    const filteredSection = useMemo<AdminPathAnalysisSection>(
        () => ({
            ...section,
            edges: filtered.edges,
            nodes: section.nodes.filter((node) => filtered.nodeIds.has(node.id)),
        }),
        [filtered.edges, filtered.nodeIds, section],
    )
    const layout = useMemo(() => layoutSankey(filteredSection), [filteredSection])

    if (layout.nodes.length === 0) {
        return (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
                No transitions pass the current suppression and edge-threshold filters.
            </div>
        )
    }

    return (
        <figure className="overflow-x-auto rounded border border-line bg-surface-2/40 p-2">
            <svg
                role="img"
                aria-labelledby={`sankey-title-${section.key}`}
                aria-describedby={`sankey-desc-${section.key}`}
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                className="h-auto w-full min-w-[720px]"
                preserveAspectRatio="xMidYMid meet"
            >
                <title id={`sankey-title-${section.key}`}>
                    {section.label} path transitions
                </title>
                <desc id={`sankey-desc-${section.key}`}>
                    Aggregate route transitions before {section.label.toLowerCase()}. Node widths are
                    proportional to visible transition counts. Select a node to filter the tables.
                </desc>
                {layout.links.map((link: SankeyLinkLayout) => {
                    const tone = TONES[link.tone] ?? TONES.route
                    return (
                        <path
                            key={`${link.edge.source}->${link.edge.target}`}
                            d={link.path}
                            fill={tone.fill}
                            opacity={0.28}
                        >
                            <title>
                                {link.edge.label}: {link.edge.count} transitions · {link.edge.users}{' '}
                                distinct users
                            </title>
                        </path>
                    )
                })}
                {layout.nodes.map((node) => (
                    <SankeyNode
                        key={node.id}
                        node={node}
                        selected={selectedNode === node.id}
                        onSelect={onSelectNode}
                    />
                ))}
            </svg>
            <figcaption className="px-2 pt-2 text-[11px] text-fg-3">
                Select any node to filter the edge and path tables to that route. Missing path data
                is a labelled node, never an inferred transition.
            </figcaption>
        </figure>
    )
}

function PathTable({ section }: { section: AdminPathAnalysisSection }) {
    return (
        <div className="overflow-x-auto rounded border border-line">
            <table className="w-full min-w-[640px] text-left text-xs">
                <caption className="sr-only">
                    Top {section.label.toLowerCase()} paths and counts
                </caption>
                <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
                    <tr>
                        <th className="px-3 py-2 font-semibold">Path before {section.label.toLowerCase()}</th>
                        <th className="px-3 py-2 text-right font-semibold">Transitions</th>
                        <th className="px-3 py-2 text-right font-semibold">Users</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-line">
                    {section.top_paths.map((path) => (
                        <tr key={path.node_ids.join('>')}>
                            <td className="px-3 py-1.5 font-mono text-[11px] text-fg">
                                {path.label}
                                {path.missing && (
                                    <span className="ml-2 rounded bg-warn/10 px-1.5 py-0.5 text-[10px] font-sans font-medium text-warn">
                                        missing route data
                                    </span>
                                )}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {formatNumber(path.count)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(path.users)}
                            </td>
                        </tr>
                    ))}
                    {section.top_paths.length === 0 && (
                        <tr>
                            <td colSpan={3} className="px-3 py-6 text-center text-fg-3">
                                No path reaches the five-user floor and edge threshold in this period.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function EdgeTable({
    section,
    selectedNode,
}: {
    section: AdminPathAnalysisSection
    selectedNode: string | null
}) {
    const edges = useMemo(
        () => filterSectionByNode(section, selectedNode).edges,
        [section, selectedNode],
    )
    return (
        <div className="overflow-x-auto rounded border border-line">
            <table className="w-full min-w-[720px] text-left text-xs">
                <caption className="sr-only">
                    Visible route transitions before {section.label.toLowerCase()}
                </caption>
                <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
                    <tr>
                        <th className="px-3 py-2 font-semibold">From</th>
                        <th className="px-3 py-2 font-semibold">To</th>
                        <th className="px-3 py-2 text-right font-semibold">Transitions</th>
                        <th className="px-3 py-2 text-right font-semibold">Users</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-line">
                    {edges.map((edge) => (
                        <tr key={`${edge.source}->${edge.target}`}>
                            <td className="px-3 py-1.5 font-mono text-[11px] text-fg">
                                {edge.source_label}
                            </td>
                            <td className="px-3 py-1.5 font-mono text-[11px] text-fg">
                                {edge.target_label}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {formatNumber(edge.count)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(edge.users)}
                            </td>
                        </tr>
                    ))}
                    {edges.length === 0 && (
                        <tr>
                            <td colSpan={4} className="px-3 py-6 text-center text-fg-3">
                                No edge is visible for the current node selection and filters.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function NodeChips({
    section,
    selectedNode,
    onSelect,
}: {
    section: AdminPathAnalysisSection
    selectedNode: string | null
    onSelect: (nodeId: string | null) => void
}) {
    const tone = (kind: string) => TONES[kind === 'outcome' ? section.key : kind] ?? TONES.route
    return (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Filter path view by node">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Nodes</span>
            {section.nodes.map((node) => {
                const selected = selectedNode === node.id
                const colors = tone(node.kind)
                return (
                    <button
                        key={node.id}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => onSelect(selected ? null : node.id)}
                        className={`rounded-full border px-2.5 py-1 text-[10px] font-medium transition ${
                            selected
                                ? 'border-fg bg-surface text-fg'
                                : `border-line ${colors.text} ${colors.soft} hover:brightness-95`
                        }`}
                        title={`${node.count} transitions · ${node.users} distinct users`}
                    >
                        {node.label}{' '}
                        <span className="text-fg-3">({formatNumber(node.count)})</span>
                    </button>
                )
            })}
            {selectedNode && (
                <button
                    type="button"
                    onClick={() => onSelect(null)}
                    className="rounded-full border border-line px-2.5 py-1 text-[10px] font-medium text-fg-3 hover:bg-surface-2"
                >
                    Clear node filter
                </button>
            )}
        </div>
    )
}

export function SectionView({ section }: { section: AdminPathAnalysisSection }) {
    const [selectedNode, setSelectedNode] = useState<string | null>(null)
    useEffect(() => {
        setSelectedNode(null)
    }, [section.key, section.total_outcomes, section.status])

    if (section.status === 'suppressed' || section.total_outcomes == null) {
        return (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
                Hidden: fewer than five distinct users had a {section.label.toLowerCase()} outcome
                in this period. Aggregate counts and transitions are suppressed to protect small
                cohorts.
            </div>
        )
    }
    if (section.status === 'empty' || section.total_outcomes === 0) {
        return (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
                No {section.label.toLowerCase()} outcomes were recorded for the selected period and
                filters.
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <MissingPathNotice section={section} />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <Metric
                    label={`${section.label} outcomes`}
                    value={formatNumber(section.total_outcomes)}
                    detail={`${count(section.route_path_outcomes)} with route data`}
                />
                <Metric
                    label="Route coverage"
                    value={pct(section.route_coverage_pct)}
                    detail={`${count(section.missing_path_outcomes)} missing route data`}
                />
                <Metric
                    label="Visible transitions"
                    value={formatNumber(section.edges.length)}
                    detail={`${formatNumber(section.suppressed_edges)} suppressed · ${formatNumber(
                        section.thresholded_edges,
                    )} below threshold`}
                />
                <Metric
                    label="Top paths"
                    value={formatNumber(section.top_paths.length)}
                    detail={`${formatNumber(section.visible_paths)} visible · ${formatNumber(
                        section.suppressed_paths,
                    )} suppressed`}
                />
                <Metric
                    label="Reconciliation"
                    value={section.reconciliation.reconciled ? 'Balanced' : 'Check failed'}
                    detail={`${section.reconciliation.checks.filter((check) => check.ok).length}/${
                        section.reconciliation.checks.length
                    } checks passing`}
                />
            </div>

            <NodeChips section={section} selectedNode={selectedNode} onSelect={setSelectedNode} />
            {selectedNode && (
                <p className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg-3">
                    Filtered to{' '}
                    <span className="font-mono text-fg">
                        {section.nodes.find((node) => node.id === selectedNode)?.label ?? selectedNode}
                    </span>
                    . Tables and Sankey show only transitions touching this node.
                </p>
            )}
            <SankeyGraph
                section={section}
                selectedNode={selectedNode}
                onSelectNode={(nodeId) => setSelectedNode(nodeId === selectedNode ? null : nodeId)}
            />
            <div className="grid gap-4 xl:grid-cols-2">
                <div>
                    <h4 className="mb-2 text-xs font-semibold text-fg">Top paths before {section.label.toLowerCase()}</h4>
                    <PathTable section={section} />
                </div>
                <div>
                    <h4 className="mb-2 text-xs font-semibold text-fg">Visible route transitions</h4>
                    <EdgeTable section={section} selectedNode={selectedNode} />
                </div>
            </div>
            <details className="rounded border border-line bg-surface-2/40 px-3 py-2">
                <summary className="cursor-pointer text-xs font-medium text-fg-2">
                    Reconciliation checks
                </summary>
                <ul className="mt-2 space-y-1 text-[11px] text-fg-3">
                    {section.reconciliation.checks.map((check) => (
                        <li key={check.key} className={check.ok ? 'text-fg-3' : 'text-err'}>
                            <span className="font-semibold">{check.ok ? 'OK' : 'FAIL'}</span>{' '}
                            <span className="font-mono">{check.key}</span> · {check.detail}
                        </li>
                    ))}
                </ul>
            </details>
        </div>
    )
}

export default function AdminPathAnalysis({ days }: { days: number }) {
    const [plan, setPlan] = useState('')
    const [appliedPlan, setAppliedPlan] = useState('')
    const [cohort, setCohort] = useState<'all' | 'new' | 'established'>('all')
    const [appliedCohort, setAppliedCohort] = useState<'all' | 'new' | 'established'>('all')
    const [edgeThreshold, setEdgeThreshold] = useState(1)
    const [appliedEdgeThreshold, setAppliedEdgeThreshold] = useState(1)
    const [outcome, setOutcome] = useState<'upgrade' | 'churn'>('upgrade')
    const [data, setData] = useState<AdminPathAnalysisResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [exporting, setExporting] = useState<'csv' | 'json' | null>(null)
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminPathAnalysis({
                days,
                plan: appliedPlan ? [appliedPlan] : undefined,
                cohort: appliedCohort,
                min_edge_count: appliedEdgeThreshold,
            })
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(err instanceof Error ? err.message : 'Failed to load path analysis')
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [appliedCohort, appliedEdgeThreshold, appliedPlan, days])

    useEffect(() => {
        void load()
        return () => {
            generation.current += 1
        }
    }, [load])

    const applyFilters = () => {
        setAppliedPlan(plan)
        setAppliedCohort(cohort)
        setAppliedEdgeThreshold(Math.max(1, Math.min(10_000, Math.trunc(Number(edgeThreshold) || 1))))
    }

    const exportCsv = async () => {
        setExporting('csv')
        setError(null)
        try {
            const blob = await apiClient.downloadAdminPathAnalysisCsv({
                days,
                plan: appliedPlan ? [appliedPlan] : undefined,
                cohort: appliedCohort,
                min_edge_count: appliedEdgeThreshold,
            })
            downloadBlob(blob, `path-analysis-${data?.start_date ?? 'export'}-${data?.end_date ?? days}.csv`)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Path analysis CSV export failed')
        } finally {
            setExporting(null)
        }
    }

    const exportJson = () => {
        if (!data) return
        setExporting('json')
        try {
            const body = JSON.stringify(data, null, 2)
            downloadBlob(
                new Blob([body], { type: 'application/json;charset=utf-8' }),
                `path-analysis-${data.start_date}-${data.end_date}.json`,
            )
        } finally {
            setExporting(null)
        }
    }

    const section = data ? (outcome === 'upgrade' ? data.upgrade : data.churn) : null

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 className="text-sm font-semibold text-fg">Path analysis before upgrade and churn</h2>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            Aggregate route transitions reconstructed from first-party{' '}
                            <code className="font-mono">page_view</code> sequences and joined to the
                            subscription ledger. Use the 7/30/90-day Analytics range above to change
                            the window. Routes are canonicalized: query strings, share tokens,
                            workspace/document ids and document content never leave the server.
                            Cohorts and edges below five distinct users are suppressed.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <button
                            type="button"
                            onClick={() => void exportCsv()}
                            disabled={loading || exporting !== null}
                            className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            {exporting === 'csv' ? 'Exporting…' : 'Export CSV'}
                        </button>
                        <button
                            type="button"
                            onClick={exportJson}
                            disabled={!data || loading || exporting !== null}
                            className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            {exporting === 'json' ? 'Exporting…' : 'Export JSON'}
                        </button>
                        <button
                            type="button"
                            onClick={() => void load()}
                            disabled={loading}
                            className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            Refresh
                        </button>
                    </div>
                </div>
                <div className="mt-3 flex flex-wrap items-end gap-3">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Plan
                        <select
                            aria-label="Filter path analysis by plan"
                            value={plan}
                            onChange={(event) => setPlan(event.target.value)}
                            className="ml-2 min-h-[30px] rounded border border-line bg-bg px-2 py-1 text-xs font-normal normal-case tracking-normal text-fg"
                        >
                            {PLAN_OPTIONS.map((option) => (
                                <option key={option || 'all'} value={option}>
                                    {option || 'All plans'}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Cohort
                        <select
                            aria-label="Filter path analysis by account cohort"
                            value={cohort}
                            onChange={(event) =>
                                setCohort(event.target.value as 'all' | 'new' | 'established')
                            }
                            className="ml-2 min-h-[30px] rounded border border-line bg-bg px-2 py-1 text-xs font-normal normal-case tracking-normal text-fg"
                        >
                            {COHORT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Edge threshold
                        <input
                            type="number"
                            min={1}
                            max={10_000}
                            aria-label="Minimum transitions per edge"
                            value={edgeThreshold}
                            onChange={(event) => setEdgeThreshold(Number(event.target.value))}
                            className="ml-2 min-h-[30px] w-20 rounded border border-line bg-bg px-2 py-1 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <button
                        type="button"
                        onClick={applyFilters}
                        disabled={loading}
                        className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        Apply filters
                    </button>
                    <span className="text-[10px] text-fg-3">
                        Window: last {days} days · {data?.filters.timezone ?? 'UTC'}
                    </span>
                </div>
            </div>

            {error && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                >
                    {error}
                </p>
            )}

            {loading && !data ? (
                <div role="status" className="px-5 py-10 text-center text-xs text-fg-3">
                    Loading path analysis…
                </div>
            ) : data ? (
                <div className="space-y-5 px-5 py-4">
                    {data.suppressed ? (
                        <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
                            Hidden: fewer than {data.minimum_cohort_size} distinct users had an
                            upgrade or churn outcome in this period. Aggregate counts and route
                            transitions are suppressed to protect small cohorts.
                        </div>
                    ) : (
                        <>
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                                <Metric label="Outcomes" value={count(data.summary.outcomes)} />
                                <Metric label="Upgrades" value={count(data.summary.upgrade_outcomes)} />
                                <Metric label="Churn" value={count(data.summary.churn_outcomes)} />
                                <Metric
                                    label="With route data"
                                    value={count(data.summary.paths_with_route_data)}
                                    detail={`${pct(data.summary.route_coverage_pct)} coverage`}
                                />
                                <Metric
                                    label="Path data missing"
                                    value={count(data.summary.paths_without_route_data)}
                                    detail="labelled, never invented"
                                />
                                <Metric
                                    label="Visible edges"
                                    value={formatNumber(data.summary.visible_edges)}
                                    detail={`${formatNumber(data.suppression.suppressed_edges)} suppressed`}
                                />
                            </div>

                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div
                                    className="inline-flex rounded border border-line bg-surface-2 p-0.5"
                                    role="group"
                                    aria-label="Outcome to inspect"
                                >
                                    {OUTCOME_TABS.map((tab) => (
                                        <button
                                            key={tab.key}
                                            type="button"
                                            aria-pressed={outcome === tab.key}
                                            onClick={() => setOutcome(tab.key)}
                                            className={`rounded px-3 py-1 text-[10px] font-semibold uppercase tracking-wider transition ${
                                                outcome === tab.key
                                                    ? 'bg-surface text-fg shadow-sm'
                                                    : 'text-fg-3 hover:text-fg'
                                            }`}
                                        >
                                            {tab.label}
                                        </button>
                                    ))}
                                </div>
                                <p className="text-[10px] text-fg-3">
                                    {data.data_source.path_lookback_days}-day lookback · last{' '}
                                    {data.data_source.max_route_steps} sanitized routes · edge
                                    threshold {data.filters.min_edge_count}
                                </p>
                            </div>

                            {section && <SectionView section={section} />}

                            <div className="grid gap-3 border-t border-line pt-4 text-[11px] leading-relaxed text-fg-3 sm:grid-cols-2">
                                <p>
                                    <span className="font-semibold text-fg-2">Reconciliation:</span>{' '}
                                    {data.reconciliation.reconciled ? 'balanced' : 'check failed'} ·{' '}
                                    {data.reconciliation.checks
                                        .map((check) => `${check.key}=${check.ok ? 'ok' : 'fail'}`)
                                        .join(' · ')}
                                </p>
                                <p>
                                    <span className="font-semibold text-fg-2">Read-only:</span> no
                                    refund, grant, downgrade or enforcement action is possible from
                                    this view. Routes are first-party; PostHog paths are not queried.
                                    {data.data_quality.pageviews_truncated ||
                                    data.data_quality.outcome_rows_truncated
                                        ? ' This period hit a row cap; treat coverage as partial.'
                                        : ''}
                                </p>
                            </div>
                        </>
                    )}
                </div>
            ) : null}
        </section>
    )
}
