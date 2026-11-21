// Number and text formatting. AED 47.0m, AED 412k, 6.24%, 1.49x.

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const minus = (s) => s.replace(/^-/, "−");

export function aed(v, { dp } = {}) {
  if (!isNum(v)) return "n/a";
  const a = Math.abs(v);
  let s;
  if (a >= 1e9) s = (v / 1e9).toFixed(dp ?? 2) + "bn";
  else if (a >= 1e6) s = (v / 1e6).toFixed(dp ?? (a >= 1e8 ? 1 : a >= 1e7 ? 1 : 2)) + "m";
  else if (a >= 1e4) s = Math.round(v / 1e3).toLocaleString("en-US") + "k";
  else s = Math.round(v).toLocaleString("en-US");
  return "AED " + minus(s);
}

export function aedFull(v) {
  if (!isNum(v)) return "n/a";
  return "AED " + minus(Math.round(v).toLocaleString("en-US"));
}

// Thousands with parentheses for negatives: institutional cash-flow style.
export function k(v) {
  if (!isNum(v)) return "";
  const r = Math.round(v / 1000);
  if (r === 0) return "–";
  const s = Math.abs(r).toLocaleString("en-US");
  return r < 0 ? `(${s})` : s;
}

export function pct(v, dp = 2) {
  if (!isNum(v)) return "n/a";
  const s = (v * 100).toFixed(dp);
  return (Number(s) === 0 ? s.replace(/^-/, "") : minus(s)) + "%";
}

export function pctPts(v, dp = 2) {
  if (!isNum(v)) return "n/a";
  const s = (v * 100).toFixed(dp);
  return (v > 0 ? "+" : "") + minus(s) + " pts";
}

export function mult(v, dp = 2) {
  if (!isNum(v)) return "n/a";
  return minus(v.toFixed(dp)) + "x";
}

export function int(v) {
  if (!isNum(v)) return "n/a";
  return minus(Math.round(v).toLocaleString("en-US"));
}

export function num(v, dp = 0) {
  if (!isNum(v)) return "n/a";
  return minus(v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }));
}

export function sqft(v) {
  return isNum(v) ? `${int(v)} sq ft` : "n/a";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function date(s) {
  if (!s || typeof s !== "string") return s ?? "n/a";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s;
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}

export function duration(s) {
  if (!isNum(s)) return "n/a";
  if (s < 90) return `${s.toFixed(0)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function usd(v) {
  return isNum(v) ? "$" + v.toFixed(2) : "n/a";
}

export function words(s) {
  if (s == null) return "";
  return String(s).replace(/_/g, " ");
}

export function sentence(s) {
  const w = words(s);
  return w.charAt(0).toUpperCase() + w.slice(1);
}

// Format by the engine / fact-sheet unit vocabulary.
export function byUnit(v, unit, opts = {}) {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map((x) => byUnit(x, unit)).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string") {
    if (unit === "date") return date(v);
    if (/^\{.*\}$/.test(v)) {
      try {
        const o = JSON.parse(v);
        return Object.entries(o).map(([a, b]) => `${words(a)}: ${words(b)}`).join("; ");
      } catch { /* fall through */ }
    }
    return v;
  }
  const u = (unit || "").toLowerCase();
  if (u === "aed" || u === "aed/yr") return opts.full ? aedFull(v) : aed(v);
  if (u === "aed/sqft") return `AED ${num(v, v < 100 ? 2 : 0)} psf`;
  if (u.startsWith("ratio")) return pct(v);
  if (u === "x") return mult(v);
  if (u === "bps") return `${int(v)} bps`;
  if (u === "sqft") return sqft(v);
  if (u === "units") return `${int(v)} units`;
  if (u === "years") return `${num(v, Number.isInteger(v) ? 0 : 1)} years`;
  if (u === "months") return `${int(v)} months`;
  if (u === "year") return String(v);
  if (u === "number") return num(v, Number.isInteger(v) ? 0 : 2);
  return num(v, Number.isInteger(v) ? 0 : 2);
}

// Engine v1 called a hard fail "Pass"; everything on the site says Decline.
export function verdictName(v) {
  return v === "Pass" ? "Decline" : v;
}

export function verdictClass(v) {
  return { Pursue: "pursue", "Needs work": "work", Decline: "decline", Pass: "decline" }[v] || "unknown";
}

export function chip(verdict, lg = false) {
  return `<span class="chip ${verdictClass(verdict)}${lg ? " lg" : ""}">${esc(verdictName(verdict) || "Not screened")}</span>`;
}

const MANDATE_YAML = "https://github.com/ryanfuruness/property-acquisition-deal-screen/blob/main/data/mandate.yaml";
const HV_TEXT = "Rests on the firm's house view (reference rent path, exit yield, vacancy and downtime), not on market evidence for this building.";

// A small "house view" tag next to walk-away prices and IRRs. href: the deal's assumptions section, else mandate.yaml.
export function hv(href) {
  const ext = !href;
  return `<a class="hv" href="${esc(href || MANDATE_YAML)}" title="${esc(HV_TEXT)} Open the assumptions."${ext ? ' target="_blank" rel="noopener"' : ""}>house view</a>`;
}

export function sev(s) {
  return `<span class="sev ${esc(s)}">${esc(sentence(s || ""))}</span>`;
}

export function prov(p) {
  const label = { document: "Document", default: "Default", mandate: "Mandate", market: "Market" }[p] || p;
  return `<span class="prov ${esc(p)}">${esc(label)}</span>`;
}

export function statusMark(s) {
  const map = { pass: ["✓", "Met"], fail: ["✗", "Not met"], unknown: ["?", "Unknown"] };
  const [ico, label] = map[s] || ["?", s];
  return `<span class="status ${esc(s)}"><span class="ico" aria-hidden="true">${ico}</span>${label}</span>`;
}

// Readable names for engine metrics and inputs.
export const METRIC_LABELS = {
  unit_count: "Units on the rent roll", occupancy_by_units: "Occupancy by units", occupancy_by_area: "Occupancy by area",
  in_place_rent_aed: "In-place rent", market_rent_reference_aed: "Market reference rent", over_rent_share_of_income: "Over-rented share of income",
  max_expiry_share_quarter: "Largest quarterly expiry share", potential_rental_income_year1: "Year-1 potential rental income",
  gross_rental_income_year1: "Year-1 gross rental income", master_lease_income_year1: "Year-1 master lease income",
  effective_gross_income_year1: "Year-1 effective gross income", operating_costs_year1: "Year-1 operating costs", noi_year1: "Year-1 NOI",
  opex_ratio_year1: "Year-1 opex ratio", price_aed: "Price", price_per_sqft_nsa: "Price per sq ft (NSA)", price_per_sqft_bua: "Price per sq ft (BUA)",
  acquisition_costs_aed: "Acquisition costs", acquisition_costs_pct_of_price: "Acquisition costs, % of price", total_cost_aed: "Total cost",
  gross_yield_in_place_on_price: "Gross yield on price", going_in_net_yield_on_price: "Net yield on price", going_in_net_yield_on_cost: "Net yield on cost",
  loan_aed: "Loan", interest_rate: "Interest rate", annual_debt_service_aed: "Annual debt service", arrangement_fee_aed: "Arrangement fee",
  equity_aed: "Equity", dscr_year1: "Year-1 DSCR", icr_year1: "Year-1 interest cover", debt_yield_year1: "Year-1 debt yield",
  breakeven_occupancy_dscr_1: "Breakeven occupancy (DSCR 1.0x)", economic_occupancy_year1: "Year-1 economic occupancy", exit_yield: "Exit yield",
  forward_noi_aed: "Forward NOI at exit", gross_exit_value_aed: "Gross exit value", net_sale_proceeds_aed: "Net sale proceeds",
  loan_balance_at_exit_aed: "Loan balance at exit", exit_gain_levered_aed: "Levered gain on exit",
  unlevered_irr_pre_tax: "Unlevered IRR, pre-tax", unlevered_irr_post_tax: "Unlevered IRR, post-tax",
  levered_irr_pre_tax: "Levered IRR, pre-tax", levered_irr_post_tax: "Levered IRR, post-tax",
  unlevered_equity_multiple_pre_tax: "Unlevered equity multiple, pre-tax", unlevered_equity_multiple_post_tax: "Unlevered equity multiple, post-tax",
  levered_equity_multiple_pre_tax: "Equity multiple, pre-tax", levered_equity_multiple_post_tax: "Equity multiple, post-tax",
  walk_away_price_aed: "Walk-away price", entry_yield_on_price: "Entry yield on price", ltv: "Loan to value",
  screen_reference_rent_aed: "Screen reference rent", over_rent_excess_at_expiry_aed: "Over-rent excess at expiry",
  commercial_income_share_year1: "Year-1 commercial income share", input_vat_recovered_year1: "Year-1 input VAT recovered",
  security_deposits_aed: "Security deposits assumed",
};

export function metricLabel(name) {
  return METRIC_LABELS[name] || sentence(String(name).replace(/_aed\b/g, "").replace(/_/g, " "));
}

export function inputLabel(name) {
  let s = String(name);
  const area = s.match(/^market\.areas\.([^.]+)\.(.+)$/);
  if (area) return `${area[1]}: ${words(area[2].replace(/_aed_psf_1br$/, " (1BR, AED psf)"))}`;
  s = s.replace(/^deal\./, "").replace(/^mandate\.(underwriting|buy_box)\./, "").replace(/^market\./, "");
  s = s.replace(/^opex_aed\./, "opex: ").replace(/_aed\b/g, "").replace(/_pct\b/g, " %").replace(/\./g, ": ");
  return sentence(words(s));
}

export const TEST_LABELS = {
  asset_type: "Asset type", title: "Title", areas: "Area", min_units: "Minimum units", max_units: "Maximum units",
  min_price_aed: "Minimum price", max_price_aed: "Maximum price", min_completion_year: "Completed in or after",
  min_dscr_year1: "Year-1 DSCR", no_master_lease_to_related_party: "No related-party master lease",
  min_going_in_net_yield_on_cost: "Net yield on cost", target_levered_irr: "Levered IRR, pre-tax",
  target_equity_multiple: "Equity multiple, pre-tax", min_occupancy: "Occupancy",
  target_unlevered_irr: "Unlevered IRR, pre-tax", target_unlevered_equity_multiple: "Unlevered equity multiple",
  max_lease_expiry_share_in_any_quarter: "Lease expiry in any quarter", max_over_rent_share_of_income: "Over-rented share of income",
};

export function testName(n) {
  return TEST_LABELS[n] || sentence(n);
}

// Replace test ids in engine prose ("3 soft fail(s): target_levered_irr") with readable names.
export function humanReason(text) {
  return String(text || "").replace(/\b[a-z]+(?:_[a-z0-9]+)+\b/g, (m) => (TEST_LABELS[m] ? TEST_LABELS[m].toLowerCase() : m.replace(/_/g, " ")));
}
