"""Build the crosswalk dataset from NIST files.

Inputs (in data/):
  csf2.xlsx                                      CSF 2.0 Reference Tool export (subcategory text, examples, refs)
  Cybersecurity_Framework_v2-0_Concept_Crosswalk_800-53_5_2_0_draft.xlsx   CSF 2.0 -> SP 800-53 Rev 5 mapping
  NIST_SP-800-53_rev5_catalog.json               OSCAL catalog (control titles and statements)
Outputs: data/subcategories.json, data/controls.json
"""
import json, re, sys, collections
from pathlib import Path
from openpyxl import load_workbook

D = Path(__file__).resolve().parent.parent / "data"
SUB = re.compile(r"^([A-Z]{2}\.[A-Z]{2}-\d{2})")
CTRL = re.compile(r"^\s*([A-Za-z]{2})-(\d+)(?:\s*\((\d+)\))?")

def norm_ctrl(s):
    """'SR-03' -> 'sr-3', 'AC-02(03)' -> 'ac-2.3' (OSCAL style)."""
    m = CTRL.match(str(s))
    if not m: return None
    fam, n, e = m.groups()
    return f"{fam.lower()}-{int(n)}" + (f".{int(e)}" if e else "")

def clean(t):
    t = re.sub(r"\{\{\s*insert:\s*param,\s*[^}]*\}\}", "[parameter]", t or "")
    return re.sub(r"\s+", " ", t).strip()

def part_text(parts, name):
    out = []
    for p in parts or []:
        if p.get("name") == name:
            def walk(x):
                if x.get("prose"): out.append(clean(x["prose"]))
                for c in x.get("parts", []): walk(c)
            walk(p)
    return " ".join(out)

def load_controls(path):
    cat = json.load(open(path, encoding="utf-8"))["catalog"]
    ctrls = {}
    def add(c, parent_title=""):
        props = {p.get("name"): p.get("value") for p in c.get("props", [])}
        withdrawn = props.get("status") == "withdrawn" or any(
            l.get("rel") == "moved-to" for l in c.get("links", []))
        if not withdrawn:
            title = c["title"]
            full = f"{parent_title}: {title}" if parent_title else title
            ctrls[c["id"]] = {"id": c["id"], "title": title, "full_title": full,
                              "statement": part_text(c.get("parts"), "statement"),
                              "guidance": part_text(c.get("parts"), "guidance")[:500],
                              "enhancement": bool(parent_title)}
        for e in c.get("controls", []): add(e, c["title"])
    for g in cat.get("groups", []):
        for c in g.get("controls", []): add(c)
    return ctrls

def main():
    cw = load_workbook(D / "Cybersecurity_Framework_v2-0_Concept_Crosswalk_800-53_5_2_0_draft.xlsx", read_only=True, data_only=True)
    rel = list(cw["Relationships"].iter_rows(values_only=True))[1:]
    targets, desc = collections.defaultdict(set), {}
    bad = 0
    for r in rel:
        if r[0] and re.match(r"^[A-Z]{2}\.[A-Z]{2}-\d{2}$", str(r[0]).strip()) and r[2]:
            sid = str(r[0]).strip(); c = norm_ctrl(r[2])
            if c: targets[sid].add(c); desc[sid] = " ".join(str(r[1]).split())
            else: bad += 1
    wb = load_workbook(D / "csf2.xlsx", read_only=True, data_only=True)
    rows = list(wb["CSF 2.0"].iter_rows(values_only=True))[2:]
    examples, ref_sets, full_text = collections.defaultdict(list), collections.defaultdict(set), {}
    for r in rows:
        m = SUB.match(str(r[2] or ""))
        if not m: continue
        sid = m.group(1)
        full_text.setdefault(sid, " ".join(str(r[2]).split(":", 1)[-1].split()))
        if r[3]: examples[sid].append(" ".join(str(r[3]).split()))
        for line in str(r[4] or "").split("\n"):
            if line.startswith("SP 800-53 Rev 5.2.0"):
                c = norm_ctrl(line.split(":", 1)[-1])
                if c: ref_sets[sid].add(c)
    ctrls = load_controls(D / "NIST_SP-800-53_rev5_catalog.json")
    all_t = set().union(*targets.values())
    enh = [t for t in all_t if "." in t]
    missing = sorted(t for t in all_t if t not in ctrls)
    # agreement between the two NIST files
    same = sum(1 for s in targets if ref_sets.get(s) == targets[s])
    print(f"subcategories with targets: {len(targets)}; unparsed control ids: {bad}")
    print(f"distinct target controls: {len(all_t)} (enhancements: {len(enh)}); not found in OSCAL catalog: {len(missing)} {missing[:10]}")
    print(f"crosswalk vs reference tool: identical control sets for {same}/{len(targets)} subcategories")
    print(f"controls in catalog (non-withdrawn): {len(ctrls)} (base: {sum(not c['enhancement'] for c in ctrls.values())})")
    cats = sorted({s[:5] for s in targets})
    split_of = {c: ("dev" if i % 2 == 0 else "test") for i, c in enumerate(cats)}
    subs = []
    for sid in sorted(targets):
        subs.append({"id": sid, "split": split_of[sid[:5]], "text": full_text.get(sid) or desc[sid],
                     "examples": examples.get(sid, []), "targets": sorted(t for t in targets[sid] if t in ctrls),
                     "targets_missing": sorted(t for t in targets[sid] if t not in ctrls)})
    json.dump(subs, open(D / "subcategories.json", "w", encoding="utf-8"), indent=1)
    json.dump(list(ctrls.values()), open(D / "controls.json", "w", encoding="utf-8"), indent=1)
    nd = sum(s["split"] == "dev" for s in subs)
    print(f"split by CSF category: dev {nd} subcategories, test {len(subs) - nd}")
    print("targets per subcategory: min/median/max =",
          min(len(s["targets"]) for s in subs), sorted(len(s["targets"]) for s in subs)[len(subs)//2],
          max(len(s["targets"]) for s in subs))
    print("example:", subs[0]["id"], subs[0]["text"][:90], subs[0]["targets"][:6])

if __name__ == "__main__":
    main()
