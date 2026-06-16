import React from 'react'
import { Box, Text } from 'ink'
import { ProgressBar } from './ProgressBar.js'

interface Props {
  pages: number | null
  sizeBytes: number | null
  compilationTimeMs: number
  pdfUrl: string | null
  atsScore: number | null
}

export function CompileResultCard({ pages, sizeBytes, compilationTimeMs, pdfUrl, atsScore }: Props): React.ReactElement {
  const sizeStr = sizeBytes != null ? `${(sizeBytes / 1024).toFixed(1)} KB` : null
  const timeStr = compilationTimeMs.toLocaleString() + ' ms'

  const atsLabel = atsScore == null ? null
    : atsScore >= 80 ? 'Excellent'
    : atsScore >= 60 ? 'Good'
    : atsScore >= 40 ? 'Fair'
    : 'Poor'

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="green"
      paddingX={1}
      marginY={1}
    >
      <Text bold color="green">─ Compilation Complete ──────────────────────────────</Text>
      <Box marginTop={1} flexDirection="column">
        <Text color="green">✓ PDF ready</Text>
      </Box>
      <Box marginTop={1} gap={4}>
        {pages != null && (
          <Box flexDirection="column">
            <Text dimColor>Pages</Text>
            <Text bold>{pages}</Text>
          </Box>
        )}
        {sizeStr != null && (
          <Box flexDirection="column">
            <Text dimColor>Size</Text>
            <Text bold>{sizeStr}</Text>
          </Box>
        )}
        <Box flexDirection="column">
          <Text dimColor>Compiler</Text>
          <Text bold>pdflatex</Text>
        </Box>
        <Box flexDirection="column">
          <Text dimColor>Time</Text>
          <Text bold>{timeStr}</Text>
        </Box>
      </Box>
      {atsScore != null && (
        <Box marginTop={1} flexDirection="column">
          <Box gap={2}>
            <Text dimColor>ATS Score</Text>
            <Text bold>{atsScore}/100</Text>
            <ProgressBar value={atsScore} width={12} showPercent={false} />
            <Text color={atsScore >= 75 ? 'green' : atsScore >= 50 ? 'yellow' : 'red'}>
              {atsLabel}
            </Text>
          </Box>
        </Box>
      )}
      {pdfUrl != null && (
        <Box marginTop={1}>
          <Text dimColor>Run /pdf to open · /ats for full analysis</Text>
        </Box>
      )}
    </Box>
  )
}
