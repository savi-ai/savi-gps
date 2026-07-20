import type { FlowNode, FlowEdge, ConversionResult, DiagramType, NodeType } from './types';
import { applyLayout } from './useAutoLayout';

/* ------------------------------------------------------------------ */
/*  Regex patterns for C4 Mermaid elements                            */
/* ------------------------------------------------------------------ */

// Person(id, "label", "desc")  or  Person(id, "label")
const PERSON_RE = /^\s*Person\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// System(id, "label", "desc")
const SYSTEM_RE = /^\s*System\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// System_Ext(id, "label", "desc")
const SYSTEM_EXT_RE = /^\s*System_Ext\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// Container(id, "label", "tech", "desc")  — tech and desc optional
const CONTAINER_RE = /^\s*Container\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*(?:,\s*"([^"]*)")?\s*\)/;

// ContainerDb(id, "label", "tech", "desc")
const CONTAINER_DB_RE = /^\s*ContainerDb\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*(?:,\s*"([^"]*)")?\s*\)/;

// Component(id, "label", "desc")
const COMPONENT_RE = /^\s*Component\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// ComponentDb(id, "label", "desc")
const COMPONENT_DB_RE = /^\s*ComponentDb\(\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// Rel(from, to, "label")  or  Rel(from, to, "label", "tech")
const REL_RE = /^\s*Rel\(\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\s*\)/;

// Lines to silently skip (headers, titles, blanks, diagram type declarations)
const SKIP_RE = /^\s*(?:$|C4Context|C4Container|C4Component|title\s|%%|```)/;

/* ------------------------------------------------------------------ */
/*  Element matchers — order matters (most specific first)            */
/* ------------------------------------------------------------------ */

interface ElementMatcher {
  regex: RegExp;
  nodeType: NodeType;
  /** Index of the technology capture group (0-based within match groups), or -1 */
  techGroup: number;
  /** Index of the description capture group, or -1 */
  descGroup: number;
}

const ELEMENT_MATCHERS: ElementMatcher[] = [
  { regex: SYSTEM_EXT_RE,    nodeType: 'external_system', techGroup: -1, descGroup: 2 },
  { regex: CONTAINER_DB_RE,  nodeType: 'database',        techGroup: 2,  descGroup: 3 },
  { regex: CONTAINER_RE,     nodeType: 'container',       techGroup: 2,  descGroup: 3 },
  { regex: COMPONENT_DB_RE,  nodeType: 'database',        techGroup: -1, descGroup: 2 },
  { regex: COMPONENT_RE,     nodeType: 'component',       techGroup: -1, descGroup: 2 },
  { regex: PERSON_RE,        nodeType: 'person',          techGroup: -1, descGroup: 2 },
  { regex: SYSTEM_RE,        nodeType: 'system',          techGroup: -1, descGroup: 2 },
];

/* ------------------------------------------------------------------ */
/*  Public API                                                        */
/* ------------------------------------------------------------------ */

/**
 * Parse a Mermaid C4 diagram string into React Flow nodes and edges.
 * Unparseable lines are collected as warnings.
 * Auto-layout is applied to position the resulting nodes.
 */
export function mermaidToFlowData(
  mermaidCode: string,
  _diagramType: DiagramType = 'context',
): ConversionResult {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const warnings: string[] = [];

  const lines = mermaidCode.split('\n');

  for (const raw of lines) {
    const line = raw.trim();

    // Skip blanks, headers, titles
    if (SKIP_RE.test(line)) continue;

    // Try relationship first
    const relMatch = line.match(REL_RE);
    if (relMatch) {
      edges.push({
        id: `edge-${relMatch[1]}-${relMatch[2]}`,
        source: relMatch[1],
        target: relMatch[2],
        label: relMatch[3] || '',
        animated: true,
      });
      continue;
    }

    // Try each element matcher
    let matched = false;
    for (const m of ELEMENT_MATCHERS) {
      const em = line.match(m.regex);
      if (em) {
        const id = em[1];
        const label = em[2] || id;
        const technology = m.techGroup >= 0 ? em[m.techGroup + 1] || '' : '';
        const description = m.descGroup >= 0 ? em[m.descGroup + 1] || '' : '';

        nodes.push({
          id,
          type: m.nodeType,
          data: { label, description, technology, nodeType: m.nodeType },
          position: { x: 0, y: 0 }, // placeholder — layout applied below
        });
        matched = true;
        break;
      }
    }

    if (!matched) {
      warnings.push(`Could not parse line: ${line}`);
    }
  }

  // Apply auto-layout so nodes get real positions
  const laid = applyLayout(nodes, edges);

  return { nodes: laid.nodes, edges: laid.edges, warnings };
}
