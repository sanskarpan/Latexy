/** Move one stable sibling while preserving the full server permutation. */
export function moveResumeSibling(order: string[], child: string, direction: -1 | 1, visibleOrder = order): string[] | null {
  if (new Set(order).size !== order.length || new Set(visibleOrder).size !== visibleOrder.length
    || visibleOrder.some((id) => !order.includes(id))) return null
  const position = visibleOrder.indexOf(child)
  const neighbor = visibleOrder[position + direction]
  if (position < 0 || !neighbor) return null
  const result = order.filter((id) => id !== child)
  const target = result.indexOf(neighbor) + (direction === 1 ? 1 : 0)
  result.splice(target, 0, child)
  return result
}
