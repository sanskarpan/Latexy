/**
 * Latexy Resume Importer — Figma Plugin
 *
 * Reads a FigmaResumeExport JSON (downloaded from /export/{id}/figma)
 * and populates a Figma frame with structured text nodes per section/entry.
 *
 * Usage:
 *  1. Export resume JSON from Latexy workspace (Export → Figma JSON)
 *  2. Open this plugin in Figma
 *  3. Paste or load the JSON file → click "Import"
 *  4. A new frame named "Latexy Resume" is created with all sections populated
 */

figma.showUI(__html__, { width: 360, height: 480, title: 'Latexy Resume Importer' })

// ── Types (mirrors FigmaResumeExport from api-client.ts) ───────────────────

interface FigmaEntry {
  heading: string
  subheading: string
  date: string
  bullets: string[]
}

interface FigmaSection {
  title: string
  entries: FigmaEntry[]
}

interface FigmaResumeExport {
  sections: FigmaSection[]
}

// ── Message handler ─────────────────────────────────────────────────────────

figma.ui.onmessage = async (msg: { type: string; payload?: FigmaResumeExport }) => {
  if (msg.type === 'import-resume' && msg.payload) {
    try {
      await importResume(msg.payload)
      figma.ui.postMessage({ type: 'done' })
    } catch (err) {
      figma.ui.postMessage({ type: 'error', message: String(err) })
    }
  }

  if (msg.type === 'close') {
    figma.closePlugin()
  }
}

// ── Import logic ─────────────────────────────────────────────────────────────

async function importResume(data: FigmaResumeExport): Promise<void> {
  // Load fonts we'll use
  await figma.loadFontAsync({ family: 'Inter', style: 'Regular' })
  await figma.loadFontAsync({ family: 'Inter', style: 'Bold' })
  await figma.loadFontAsync({ family: 'Inter', style: 'Italic' })

  // Create a root frame
  const frame = figma.createFrame()
  frame.name = 'Latexy Resume'
  frame.resize(595, 842)  // A4 at 72 dpi (portrait)
  frame.layoutMode = 'VERTICAL'
  frame.itemSpacing = 16
  frame.paddingTop = 48
  frame.paddingBottom = 48
  frame.paddingLeft = 56
  frame.paddingRight = 56
  frame.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }]

  for (const section of data.sections) {
    // Section heading
    const headingNode = figma.createText()
    headingNode.fontName = { family: 'Inter', style: 'Bold' }
    headingNode.fontSize = 13
    headingNode.characters = section.title.toUpperCase()
    headingNode.fills = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.1 } }]
    frame.appendChild(headingNode)

    // Separator line (thin rectangle)
    const rule = figma.createRectangle()
    rule.resize(frame.width - 112, 1)
    rule.fills = [{ type: 'SOLID', color: { r: 0.7, g: 0.7, b: 0.7 } }]
    frame.appendChild(rule)

    for (const entry of section.entries) {
      if (entry.heading) {
        const hNode = figma.createText()
        hNode.fontName = { family: 'Inter', style: 'Bold' }
        hNode.fontSize = 11
        hNode.characters = entry.heading
        frame.appendChild(hNode)
      }

      if (entry.subheading) {
        const shNode = figma.createText()
        shNode.fontName = { family: 'Inter', style: 'Italic' }
        shNode.fontSize = 10
        shNode.characters = entry.subheading
        shNode.fills = [{ type: 'SOLID', color: { r: 0.35, g: 0.35, b: 0.35 } }]
        frame.appendChild(shNode)
      }

      if (entry.date) {
        const dateNode = figma.createText()
        dateNode.fontName = { family: 'Inter', style: 'Regular' }
        dateNode.fontSize = 9
        dateNode.characters = entry.date
        dateNode.fills = [{ type: 'SOLID', color: { r: 0.5, g: 0.5, b: 0.5 } }]
        frame.appendChild(dateNode)
      }

      for (const bullet of entry.bullets) {
        const bNode = figma.createText()
        bNode.fontName = { family: 'Inter', style: 'Regular' }
        bNode.fontSize = 10
        bNode.characters = `• ${bullet}`
        frame.appendChild(bNode)
      }
    }
  }

  figma.currentPage.appendChild(frame)
  figma.viewport.scrollAndZoomIntoView([frame])
}
