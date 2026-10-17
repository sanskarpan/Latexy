'use client'

import * as Tabs from '@radix-ui/react-tabs'
import { motion, useReducedMotion } from 'framer-motion'

export const reviewStages = ['Write', 'Review', 'Tailor', 'Export'] as const
export type ReviewStage = (typeof reviewStages)[number]

/**
 * Animated selection adapted from Manu Arora's free Aceternity Tabs component:
 * https://ui.aceternity.com/components/tabs
 * Radix supplies tab semantics, roving focus and keyboard activation. A single
 * active panel avoids the original stacked panels' hidden focusable content.
 */
export function ReviewStageList({ selected }: { selected: ReviewStage }) {
    const reducedMotion = useReducedMotion()
    return (
        <Tabs.List className="rd-stages" aria-label="Explore the résumé workflow">
            {reviewStages.map(stage => (
                <Tabs.Trigger className="rd-stage" key={stage} value={stage}>
                    <span className="rd-stage-dot" aria-hidden="true">
                        {selected === stage && (
                            <motion.span
                                layoutId="review-stage-indicator"
                                transition={
                                    reducedMotion
                                        ? { duration: 0 }
                                        : { type: 'spring', stiffness: 380, damping: 32 }
                                }
                            />
                        )}
                    </span>
                    <span>{stage}</span>
                </Tabs.Trigger>
            ))}
        </Tabs.List>
    )
}
