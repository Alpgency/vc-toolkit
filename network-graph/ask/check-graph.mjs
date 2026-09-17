/* Assert-based check of the graph tools against the synthetic data.
   No network, no API key. Run: node ask/check-graph.mjs */

import assert from "node:assert/strict";
import { graphLoaded, fundName, findCompanies, doorsTo, personInfo, listPartners } from "./graph.mjs";
import { runTool, citationsFrom } from "./ask.mjs";

assert.ok(graphLoaded, "graph loads");
assert.equal(fundName, "Example Ventures");

const partners = listPartners();
assert.equal(partners.length, 4);
assert.ok(partners.some((p) => p.name === "Maren Okafor"));

// sector word resolves to companies without naming them
const logistics = findCompanies("who can help with a logistics deal").map((c) => c.company);
assert.ok(logistics.includes("Harborline Logistics") && logistics.includes("Kestrelway Freight"), logistics.join());

// unknown company: no match, no doors
assert.deepEqual(findCompanies("Globex Megacorp"), []);
assert.deepEqual(doorsTo("Globex Megacorp"), []);

// a partner's board seat is the confirmed door
const kestrel = doorsTo("kestrelway freight");
assert.equal(kestrel[0].person, "Maren Okafor");
assert.equal(kestrel[0].tier, "confirmed");
assert.equal(kestrel[0].advisory_seat.since, "2023");

// planted colleague: overlap at one company, door into another
const sunmesa = doorsTo("Sunmesa Energy");
assert.equal(sunmesa[0].person, "Imogen Thrale");
assert.equal(sunmesa[0].via_op, "Tobias Reinholt");
assert.equal(sunmesa[0].overlap_company, "Ledgerloom");
assert.equal(sunmesa[0].status, "current");
assert.ok(sunmesa.slice(1).every((r) => r.status === "era"));

// shared colleague has edges from two partners
const bastian = personInfo("cs-100002");
assert.equal(bastian.name, "Bastian Coldmere");
assert.deepEqual(new Set(bastian.edges.map((e) => e.source_name)), new Set(["Priya Castellano", "Tobias Reinholt"]));

// tool dispatch plus citations only for names the answer uses
const rows = [];
runTool("doors_to", { company: "Sunmesa Energy" }, rows);
const cites = citationsFrom("Imogen Thrale likely knows Tobias Reinholt from Ledgerloom.", rows);
assert.equal(cites.length, 1);
assert.equal(cites[0].person, "Imogen Thrale");
assert.deepEqual(runTool("nope", {}, []), { error: "unknown tool" });

console.log("check-graph: all assertions passed");
