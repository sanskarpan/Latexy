/**
 * Pure Sankey layout helpers for the admin path-analysis view.
 *
 * The layouts are derived only from the aggregate section payload returned by
 * `/admin/analytics/paths`. No user, document, token or query value can enter a
 * node or link because the server has already canonicalized every route.
 */

import type {
    AdminPathAnalysisEdge,
    AdminPathAnalysisNode,
    AdminPathAnalysisPath,
    AdminPathAnalysisSection,
} from '@/lib/api-client'

export const SANKEY_WIDTH = 960
export const SANKEY_HEIGHT = 440
export const SANKEY_NODE_WIDTH = 150
export const SANKEY_PADDING = 20
export const SANKEY_NODE_GAP = 12
export const SANKEY_MIN_NODE_HEIGHT = 14

export type SankeyTone = 'route' | 'upgrade' | 'churn' | 'missing'

export interface SankeyNodeLayout extends AdminPathAnalysisNode {
    x: number
    y: number
    width: number
    height: number
    depth: number
    tone: SankeyTone
}

export interface SankeyLinkLayout {
    edge: AdminPathAnalysisEdge
    path: string
    thickness: number
    tone: SankeyTone
}

export interface SankeyLayout {
    width: number
    height: number
    nodes: SankeyNodeLayout[]
    links: SankeyLinkLayout[]
    maxDepth: number
}

export function nodeTone(
    node: Pick<AdminPathAnalysisNode, 'kind'>,
    sectionKey: 'upgrade' | 'churn' = 'upgrade',
): SankeyTone {
    if (node.kind === 'outcome') return sectionKey === 'churn' ? 'churn' : 'upgrade'
    if (node.kind === 'missing') return 'missing'
    return 'route'
}

function toneForEdge(edge: AdminPathAnalysisEdge, nodes: Map<string, AdminPathAnalysisNode>): SankeyTone {
    const target = nodes.get(edge.target)
    if (target?.kind === 'outcome') {
        return target.label.toLowerCase().includes('churn') ? 'churn' : 'upgrade'
    }
    if (target?.kind === 'missing' || edge.target.startsWith('missing:')) return 'missing'
    return 'route'
}

function computeDepths(nodes: AdminPathAnalysisNode[], edges: AdminPathAnalysisEdge[]): Map<string, number> {
    const depths = new Map<string, number>()
    const indegree = new Map<string, number>()
    const outgoing = new Map<string, AdminPathAnalysisEdge[]>()
    for (const node of nodes) {
        depths.set(node.id, 0)
        indegree.set(node.id, 0)
        outgoing.set(node.id, [])
    }
    for (const edge of edges) {
        if (!depths.has(edge.source) || !depths.has(edge.target)) continue
        outgoing.get(edge.source)?.push(edge)
        indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1)
    }
    const queue = nodes
        .filter((node) => (indegree.get(node.id) ?? 0) === 0)
        .map((node) => node.id)
    const visited = new Set<string>()
    while (queue.length > 0) {
        const nodeId = queue.shift() as string
        if (visited.has(nodeId)) continue
        visited.add(nodeId)
        for (const edge of outgoing.get(nodeId) ?? []) {
            depths.set(edge.target, Math.max(depths.get(edge.target) ?? 0, (depths.get(nodeId) ?? 0) + 1))
            indegree.set(edge.target, (indegree.get(edge.target) ?? 1) - 1)
            if ((indegree.get(edge.target) ?? 0) === 0) queue.push(edge.target)
        }
    }
    return depths
}

export function layoutSankey(
    section: AdminPathAnalysisSection,
    options: { width?: number; height?: number } = {},
): SankeyLayout {
    const width = options.width ?? SANKEY_WIDTH
    const height = options.height ?? SANKEY_HEIGHT
    const nodes = section.nodes
    const edges = section.edges
    if (nodes.length === 0) {
        return { width, height, nodes: [], links: [], maxDepth: 0 }
    }

    const nodeMap = new Map(nodes.map((node) => [node.id, node]))
    const depths = computeDepths(nodes, edges)
    const maxDepth = Math.max(...Array.from(depths.values()), 0)
    const columns = new Map<number, AdminPathAnalysisNode[]>()
    for (const node of nodes) {
        const depth = depths.get(node.id) ?? 0
        const column = columns.get(depth) ?? []
        column.push(node)
        columns.set(depth, column)
    }
    for (const column of columns.values()) {
        column.sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
    }

    const columnTotals = new Map<number, number>()
    for (const [depth, column] of columns) {
        columnTotals.set(depth, column.reduce((total, node) => total + Math.max(1, node.count), 0))
    }
    const maxColumnTotal = Math.max(...Array.from(columnTotals.values()), 1)
    const usableHeight = height - SANKEY_PADDING * 2
    const xStep = maxDepth === 0 ? 0 : (width - SANKEY_PADDING * 2 - SANKEY_NODE_WIDTH) / maxDepth

    const layoutNodes: SankeyNodeLayout[] = []
    const nodeById = new Map<string, SankeyNodeLayout>()
    for (let depth = 0; depth <= maxDepth; depth += 1) {
        const column = columns.get(depth) ?? []
        if (column.length === 0) continue
        const scale = usableHeight / maxColumnTotal
        const heights = column.map((node) => Math.max(SANKEY_MIN_NODE_HEIGHT, node.count * scale))
        const totalHeight = heights.reduce((total, value) => total + value, 0)
        const gaps = Math.max(0, column.length - 1) * SANKEY_NODE_GAP
        const offset = SANKEY_PADDING + Math.max(0, (usableHeight - totalHeight - gaps) / 2)
        let y = offset
        column.forEach((node, index) => {
            const layoutNode: SankeyNodeLayout = {
                ...node,
                x: SANKEY_PADDING + depth * xStep,
                y,
                width: SANKEY_NODE_WIDTH,
                height: heights[index],
                depth,
                tone: nodeTone(node, section.key),
            }
            layoutNodes.push(layoutNode)
            nodeById.set(node.id, layoutNode)
            y += heights[index] + SANKEY_NODE_GAP
        })
    }

    const outgoing = new Map<string, AdminPathAnalysisEdge[]>()
    const incoming = new Map<string, AdminPathAnalysisEdge[]>()
    for (const edge of edges) {
        if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) continue
        outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge])
        incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge])
    }
    const sourceCursor = new Map<string, number>()
    const targetCursor = new Map<string, number>()
    for (const node of layoutNodes) {
        sourceCursor.set(node.id, node.y)
        targetCursor.set(node.id, node.y)
    }

    const links: SankeyLinkLayout[] = []
    for (const edge of edges) {
        const source = nodeById.get(edge.source)
        const target = nodeById.get(edge.target)
        if (!source || !target) continue
        const sourceTotal = (outgoing.get(source.id) ?? []).reduce((total, item) => total + item.count, 0)
        const targetTotal = (incoming.get(target.id) ?? []).reduce((total, item) => total + item.count, 0)
        const sourceThickness = Math.max(
            1.5,
            (edge.count / Math.max(1, sourceTotal)) * source.height,
        )
        const targetThickness = Math.max(
            1.5,
            (edge.count / Math.max(1, targetTotal)) * target.height,
        )
        const thickness = Math.min(sourceThickness, targetThickness)
        const sy = sourceCursor.get(source.id) ?? source.y
        const ty = targetCursor.get(target.id) ?? target.y
        sourceCursor.set(source.id, sy + sourceThickness)
        targetCursor.set(target.id, ty + targetThickness)
        const sx = source.x + source.width
        const tx = target.x
        const midX = (sx + tx) / 2
        const path = [
            `M ${sx.toFixed(2)} ${sy.toFixed(2)}`,
            `C ${midX.toFixed(2)} ${sy.toFixed(2)}, ${midX.toFixed(2)} ${ty.toFixed(2)}, ${tx.toFixed(2)} ${ty.toFixed(2)}`,
            `L ${tx.toFixed(2)} ${(ty + thickness).toFixed(2)}`,
            `C ${midX.toFixed(2)} ${(ty + thickness).toFixed(2)}, ${midX.toFixed(2)} ${(sy + thickness).toFixed(2)}, ${sx.toFixed(2)} ${(sy + thickness).toFixed(2)}`,
            'Z',
        ].join(' ')
        links.push({
            edge,
            path,
            thickness,
            tone: toneForEdge(edge, nodeMap),
        })
    }

    return { width, height, nodes: layoutNodes, links, maxDepth }
}

export interface FilteredPathView {
    edges: AdminPathAnalysisEdge[]
    paths: AdminPathAnalysisPath[]
    nodeIds: Set<string>
}

export function filterSectionByNode(
    section: AdminPathAnalysisSection,
    nodeId: string | null,
): FilteredPathView {
    if (!nodeId) {
        return {
            edges: section.edges,
            paths: section.top_paths,
            nodeIds: new Set(section.nodes.map((node) => node.id)),
        }
    }
    const edges = section.edges.filter((edge) => edge.source === nodeId || edge.target === nodeId)
    const nodeIds = new Set<string>([nodeId])
    for (const edge of edges) {
        nodeIds.add(edge.source)
        nodeIds.add(edge.target)
    }
    return {
        edges,
        paths: section.top_paths.filter((path) => path.node_ids.includes(nodeId)),
        nodeIds,
    }
}

/** Deterministic test/accessibility description of a rendered path. */
export function describePath(path: AdminPathAnalysisPath): string {
    return `${path.label} — ${path.count} transitions, ${path.users} distinct users`
}
