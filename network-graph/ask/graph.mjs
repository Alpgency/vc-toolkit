/* Graph tools for /api/ask.
   Loads the network-data.js file once at import (GRAPH_FILE, default
   ../data/network-data.js), builds lookup indexes, and exposes pure,
   deterministic functions. No I/O after load. If the file is missing,
   graphLoaded stays false and the server answers 503. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const GRAPH_FILE = process.env.GRAPH_FILE ||
  fileURLToPath(new URL("../data/network-data.js", import.meta.url));

export let graphLoaded = false;

let data = { nodes: [], edges: [], employerIndex: {}, advisorySeats: [], companies: [] };
const byId = new Map();
const employerKeys = [];
const employerKeyByLower = new Map();
const inboundByTarget = new Map();
const edgesByNode = new Map();
/* (advisor_id + " " + lowercased company) -> the seat record */
const seatByAdvisorCompany = new Map();
/* sector word -> company names, so "logistics" finds companies without naming them */
const aliases = {};

/* Common question words that would otherwise substring-match employer names. */
const STOP = new Set([
  "the", "and", "who", "can", "get", "into", "our", "for", "with", "from",
  "that", "this", "what", "which", "does", "have", "has", "are", "was", "were",
  "about", "they", "them", "their", "how", "why", "when", "would", "could",
  "should", "will", "want", "need", "know", "knows", "anyone", "someone",
  "deal", "path", "warm", "door", "doors", "open", "reach", "talk", "best",
  "person", "people", "partner", "partners", "company", "companies", "contact",
  "intro", "introduction", "help", "you", "not", "any"
]);

try {
  const raw = readFileSync(GRAPH_FILE, "utf8");
  const marker = raw.indexOf("window.NETWORK_DATA");
  if (marker < 0) throw new Error("window.NETWORK_DATA marker not found");
  data = JSON.parse(raw.slice(raw.indexOf("=", marker) + 1).trim().replace(/;\s*$/, ""));

  for (const node of data.nodes) byId.set(node.id, node);
  for (const key of Object.keys(data.employerIndex)) {
    employerKeys.push(key);
    employerKeyByLower.set(key.toLowerCase(), key);
  }
  for (const edge of data.edges) {
    if (!inboundByTarget.has(edge.target)) inboundByTarget.set(edge.target, []);
    inboundByTarget.get(edge.target).push(edge);
    for (const id of [edge.source, edge.target]) {
      if (!edgesByNode.has(id)) edgesByNode.set(id, []);
      edgesByNode.get(id).push(edge);
    }
  }
  for (const seat of data.advisorySeats || []) {
    seatByAdvisorCompany.set(seat.advisor_id + " " + String(seat.company).toLowerCase(), seat);
  }
  for (const c of data.companies || []) {
    if (!c.sector) continue;
    const word = c.sector.toLowerCase();
    (aliases[word] ||= []).push(c.name.toLowerCase());
  }

  graphLoaded = true;
  console.log(`[graph] loaded: ${data.nodes.length} nodes, ${data.edges.length} edges, ${(data.advisorySeats || []).length} seats`);
} catch (err) {
  console.warn(`[graph] not loaded from ${GRAPH_FILE}: ${err.message}`);
}

export const fundName = data.nodes.find((n) => n.kind === "fund")?.name || "the fund";

/* Match employer names by substring of each word (>= 3 chars) of the text,
   plus sector expansions. Returns up to 12 {company, people_count}. */
export function findCompanies(text) {
  if (!graphLoaded) return [];
  const words = String(text || "").toLowerCase().match(/[a-z0-9][a-z0-9.&'-]*/g) || [];
  const terms = new Set();
  for (const word of words) {
    if (word.length >= 3 && !STOP.has(word)) terms.add(word);
    for (const term of aliases[word] || []) terms.add(term);
  }
  if (!terms.size) return [];

  const hits = [];
  for (const key of employerKeys) {
    const lower = key.toLowerCase();
    for (const term of terms) {
      if (lower.includes(term)) {
        hits.push({ company: key, people_count: (data.employerIndex[key] || []).length });
        break;
      }
    }
  }
  hits.sort((a, b) => b.people_count - a.people_count || a.company.localeCompare(b.company));
  return hits.slice(0, 12);
}

/* Ranked people who can open a door at one company (exact employer-index key,
   matched case-insensitively). Current employees first, then by edge weight. */
export function doorsTo(company) {
  if (!graphLoaded) return [];
  const key = employerKeyByLower.get(String(company || "").toLowerCase().trim());
  if (!key) return [];
  const keyLower = key.toLowerCase();

  const rows = [];
  for (const id of data.employerIndex[key] || []) {
    const node = byId.get(id);
    if (!node || node.kind === "fund") continue;

    let best = null;
    for (const edge of inboundByTarget.get(id) || []) {
      if (!best || edge.weight > best.weight) best = edge;
    }

    const employerLower = String(node.employer || "").toLowerCase();
    const current = Boolean(employerLower) &&
      (employerLower.includes(keyLower) || keyLower.includes(employerLower));

    /* A partner's own board or advisory seat AT the queried company is the
       real, confirmed, present-day reason, not the generic fund tie. */
    const seat = node.kind === "op" ? seatByAdvisorCompany.get(node.id + " " + keyLower) : null;

    rows.push({
      person_id: node.id,
      person: node.name,
      kind: node.kind,
      via_op: node.kind === "op" ? "direct" : (byId.get(best?.source)?.name || null),
      weight: seat ? 0.97 : (best ? best.weight : null),
      tier: seat ? "confirmed" : (best ? best.tier : node.tier),
      company: key,
      /* where the person and the partner actually overlapped; often NOT the
         queried company (someone met at one employer can be the door into another) */
      overlap_company: best?.basis?.company || null,
      window: best?.basis?.window || null,
      overlap_years: best?.basis?.overlap_years ?? null,
      current_role: node.title || null,
      current_employer: node.employer || null,
      advisory_seat: seat ? { title: seat.title, since: seat.since } : null,
      status: (seat || current) ? "current" : "era"
    });
  }

  rows.sort((a, b) => {
    if (a.status !== b.status) return a.status === "current" ? -1 : 1;
    if ((b.weight || 0) !== (a.weight || 0)) return (b.weight || 0) - (a.weight || 0);
    return a.person.localeCompare(b.person);
  });
  return rows.slice(0, 8);
}

/* Full node record plus every edge that touches it, with basis. */
export function personInfo(personId) {
  if (!graphLoaded) return null;
  const node = byId.get(String(personId || ""));
  if (!node) return null;
  const edges = (edgesByNode.get(node.id) || []).map((edge) => ({
    source: edge.source,
    source_name: byId.get(edge.source)?.name || edge.source,
    target: edge.target,
    target_name: byId.get(edge.target)?.name || edge.target,
    weight: edge.weight,
    tier: edge.tier,
    basis: edge.basis || null
  }));
  return { ...node, edges };
}

/* The fund's partners. */
export function listPartners() {
  if (!graphLoaded) return [];
  return data.nodes
    .filter((node) => node.kind === "op")
    .map((node) => ({ person_id: node.id, name: node.name, title: node.title, employer: node.employer }));
}
