import React from 'react'
import { Box, Text } from 'ink'

interface Props {
  pages: number | null
  sizeBytes: number | null
  compilationTimeMs: number
  pdfUrl: string | null
  atsScore: number | null
}

export function CompileResultCard({ pages, sizeBytes, compilationTimeMs, pdfUrl, atsScore }: Props): React.ReactElement {
  const sizeKb = sizeBytes != null ? Math.round(sizeBytes / 1024) : null
  const timeStr = `${(compilationTimeMs / 1000).toFixed(1)}s`

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1} marginY={1}>
      <Text bold color="green">✓ Compiled successfully</Text>
      <Box gap={3} marginTop={1}>
        {pages != null && (
          <Text>📄 <Text bold>{pages}</Text> page{pages !== 1 ? 's' : ''}</Text>
        )}
        {sizeKb != null && (
          <Text>💾 <Text bold>{sizeKb}</Text> KB</Text>
        )}
        <Text>⏱ <Text bold>{timeStr}</Text></Text>
        {atsScore != null && (
          <Text>📊 ATS: <Text bold color="cyan">{atsScore}%</Text></Text>
        )}
      </Box>
      {pdfUrl != null && (
        <Box marginTop={1}>
          <Text dimColor>Run /pdf to open · /ats for full analysis</Text>
        </Box>
      )}
    </Box>
  )
}
