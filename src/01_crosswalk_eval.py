"""CSF 2.0 subcategory -> SP 800-53 Rev 5 control mapping: baselines, embeddings, LLM re-rank.

Ground truth = NIST's own crosswalk (no hand labels).
  python src\\01_crosswalk_eval.py --split dev  --methods random,prior,embed
  python src\\01_crosswalk_eval.py --split dev  --methods embed,rerank --tag v1
  python src\\01_crosswalk_eval.py --split test --methods random,prior,embed,rerank --tag final   (ONCE)
Options: --model NAME  --examples  --pool all|base  --topn 15
"""
import argparse, json, re, time, zlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA, REP = ROOT / "data", ROOT / "reports"
REP.mkdir(exist_ok=True)
KS = (5, 10)

def load(pool):
    subs = json.load(open(DATA / "subcategories.json", encoding="utf-8"))
    ctrls = json.load(open(DATA / "controls.json", encoding="utf-8"))
    if pool == "base": ctrls = [c for c in ctrls if not c["enhancement"]]
    ids = {c["id"] for c in ctrls}
    for s in subs: s["targets_pool"] = [t for t in s["targets"] if t in ids]
    return subs, ctrls

def ctrl_text(c): return f"{c['full_title']}. {c['statement']}"[:1500]

class Embedder:
    def __init__(self, name):
        self.name = name
        if name != "fake":
            from sentence_transformers import SentenceTransformer
            self.m = SentenceTransformer(name)
    def enc(self, texts):
        if self.name == "fake":
            out = []
            for t in texts:
                r = np.random.default_rng(zlib.crc32(t.encode())); v = r.normal(size=64); out.append(v / np.linalg.norm(v))
            return np.array(out)
        return self.m.encode(texts, normalize_embeddings=True, batch_size=32)

def metrics(rank, T):
    T = set(T); out = {}
    for k in KS:
        top = set(rank[:k]); inter = len(T & top)
        out[f"hit@{k}"] = float(inter > 0); out[f"recall@{k}"] = inter / len(T); out[f"prec@{k}"] = inter / k
    pos = [i + 1 for i, c in enumerate(rank) if c in T]
    out["mrr"] = 1 / pos[0] if pos else 0.0
    fam = {t.split("-")[0] for t in T}
    out["famhit@5"] = float(any(c.split("-")[0] in fam for c in rank[:5]))
    return out

def boot(vals, n=2000, seed=0):
    v = np.array(vals); r = np.random.default_rng(seed)
    m = [v[r.integers(0, len(v), len(v))].mean() for _ in range(n)]
    return v.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

# ---------- methods ----------
def rank_random(subs, ctrls, seed=15):
    r = np.random.default_rng(seed); ids = [c["id"] for c in ctrls]
    return {s["id"]: list(r.permutation(ids)) for s in subs}

def rank_prior(subs, ctrls, all_subs):
    """Most frequently mapped controls, counted from DEV subcategories of OTHER CSF categories only."""
    ids = [c["id"] for c in ctrls]; out = {}
    for s in subs:
        cnt = {i: 0 for i in ids}
        for o in all_subs:
            if o["split"] == "dev" and o["id"][:5] != s["id"][:5]:
                for t in o["targets_pool"]: cnt[t] += 1
        out[s["id"]] = sorted(ids, key=lambda i: (-cnt[i], i))
    return out

def query_of(s, examples):
    q = s["text"]
    if examples and s["examples"]: q += ". Examples: " + " ".join(s["examples"][:2])[:400]
    return q

def rank_embed(subs, ctrls, emb, examples):
    C = emb.enc([ctrl_text(c) for c in ctrls]); Q = emb.enc([query_of(s, examples) for s in subs])
    S = Q @ C.T; ids = [c["id"] for c in ctrls]
    return {s["id"]: [ids[j] for j in np.argsort(-S[i])] for i, s in enumerate(subs)}, S

SYS = "You are a cybersecurity compliance analyst who maps NIST CSF 2.0 outcomes to NIST SP 800-53 Rev 5 controls."
def rerank_prompt(s, cands, cmap):
    lines = "\n".join(f"[{c}] {cmap[c]['full_title']}: {cmap[c]['statement'][:220]}" for c in cands)
    return (f"CSF 2.0 subcategory {s['id']}: {s['text']}\n\nCandidate SP 800-53 controls:\n{lines}\n\n"
            "Which candidates implement or directly support this subcategory? "
            'Reply as JSON: {"controls": ["id", ...]} with up to 5 candidate ids, best first.')

class LLM:
    def __init__(self, tag, model="llama3.2"):
        import ollama
        self.o, self.model = ollama, model
        self.path = REP / f"rerank_cache_{tag}.jsonl"; self.cache = {}
        if self.path.exists():
            for l in open(self.path, encoding="utf-8"):
                try: r = json.loads(l); self.cache[r["k"]] = r["v"]
                except Exception: pass
    def ask(self, key, user):
        if key in self.cache: return self.cache[key]
        last = None
        for a in range(4):
            try:
                r = self.o.chat(model=self.model, format="json", options={"temperature": 0, "num_ctx": 4096},
                                messages=[{"role": "system", "content": SYS}, {"role": "user", "content": user}])
                try: v = json.loads(r["message"]["content"])
                except Exception: v = {"controls": [], "parse_error": True}
                self.cache[key] = v
                open(self.path, "a", encoding="utf-8").write(json.dumps({"k": key, "v": v}) + "\n")
                return v
            except Exception as e: last = e; time.sleep(3 * (a + 1))
        raise RuntimeError(f"ollama failed: {last}")

def rank_rerank(subs, base_rank, cmap, llm, topn):
    out, invalid = {}, 0
    for s in subs:
        cands = base_rank[s["id"]][:topn]
        v = llm.ask(f"{s['id']}|{topn}|v1", rerank_prompt(s, cands, cmap))
        picked = []
        for c in (v.get("controls") or []):
            c = re.sub(r"^\s*id\s*:\s*", "", str(c), flags=re.I).strip(" []\"'").lower()
            if c in cands and c not in picked: picked.append(c)
            elif c not in cands: invalid += 1
        out[s["id"]] = picked + [c for c in base_rank[s["id"]] if c not in picked]
    return out, invalid

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--methods", default="random,prior,embed")
    ap.add_argument("--model", default="all-MiniLM-L6-v2")
    ap.add_argument("--examples", action="store_true")
    ap.add_argument("--pool", choices=["all", "base"], default="all")
    ap.add_argument("--topn", type=int, default=15)
    ap.add_argument("--tag", default="v1")
    a = ap.parse_args()
    all_subs, ctrls = load(a.pool); cmap = {c["id"]: c for c in ctrls}
    subs = [s for s in all_subs if s["split"] == a.split and s["targets_pool"]]
    print(f"split={a.split} pool={a.pool} ({len(ctrls)} controls) subcategories={len(subs)} model={a.model} examples={a.examples}")
    methods = a.methods.split(","); ranks = {}
    if "random" in methods: ranks["random"] = rank_random(subs, ctrls)
    if "prior" in methods: ranks["prior"] = rank_prior(subs, ctrls, all_subs)
    base = None
    if "embed" in methods or "rerank" in methods:
        base, _ = rank_embed(subs, ctrls, Embedder(a.model), a.examples)
        if "embed" in methods: ranks["embed"] = base
    if "rerank" in methods:
        ranks["embed+LLM rerank"], inv = rank_rerank(subs, base, cmap, LLM(a.tag), a.topn)
        print(f"LLM answers not in the candidate list (discarded): {inv}")
    cols = ["hit@5", "hit@10", "recall@10", "mrr", "famhit@5"]
    print("\n95% bootstrap intervals over subcategories (correlated: related subcategories share controls)\n")
    print(f"{'method':18s} " + " ".join(f"{c:>20s}" for c in cols))
    res = {}
    for name, rk in ranks.items():
        per = [metrics(rk[s["id"]], s["targets_pool"]) for s in subs]
        res[name] = {c: boot([p[c] for p in per]) for c in cols}
        print(f"{name:18s} " + " ".join(f"{res[name][c][0]*100:5.0f}% ({res[name][c][1]*100:3.0f}-{res[name][c][2]*100:3.0f})" for c in cols))
    json.dump({"args": vars(a), "n": len(subs), "results": {k: {c: list(map(float, v)) for c, v in d.items()} for k, d in res.items()},
               "ranks_top10": {n: {s["id"]: rk[s["id"]][:10] for s in subs} for n, rk in ranks.items()}},
              open(REP / f"results_{a.split}_{a.tag}.json", "w"), indent=1)
    print(f"\nSaved reports/results_{a.split}_{a.tag}.json")

if __name__ == "__main__":
    main()
