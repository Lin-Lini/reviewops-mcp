import os, re, hashlib
from huggingface_hub import hf_hub_download
import pyarrow.parquet as pq
import psycopg

db = os.environ["DB"]
repo = os.environ["HF_REPO"]
fn = os.environ["HF_FILE"]

def n(s):
    s = (s or "").strip().lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s

def h(s):
    return hashlib.blake2b(s.encode("utf-8"), digest_size=16).hexdigest()

def a01(addr):
    p = [x.strip() for x in (addr or "").split(",")]
    a0 = p[0] if len(p) > 0 and p[0] else None
    a1 = p[1] if len(p) > 1 and p[1] else None
    return a0, a1

def rubs(s):
    if not s:
        return []
    return [x.strip() for x in s.split(";") if x.strip()]

path = hf_hub_download(repo_id=repo, filename=fn, repo_type="dataset")
pf = pq.ParquetFile(path)

con = psycopg.connect(db)
con.execute("SET synchronous_commit=off;")
con.commit()

with con.cursor() as cur:
    for b in pf.iter_batches(batch_size=5000, columns=["address","name_ru","rubrics","rating","text"]):
        d = b.to_pydict()
        o = {}
        rv = []
        for i in range(len(d["text"])):
            addr = d["address"][i] or ""
            name = d["name_ru"][i] or ""
            txt = d["text"][i] or ""
            rt0 = d["rating"][i]

            if rt0 is None:
                continue
            rt = int(rt0)

            if not txt.strip() or not addr.strip():
                continue

            rk = rubs(d["rubrics"][i])

            ok = h(n(name) + "|" + n(addr))
            rid = h(ok + "|" + str(rt) + "|" + n(txt))
            a0, a1 = a01(addr)

            if ok not in o:
                o[ok] = (ok, name, addr, a0, a1, rk)
            rv.append((rid, ok, rt, txt))

        if o:
            cur.executemany(
                "INSERT INTO org(org_key,name_ru,address,a0,a1,rub) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (org_key) DO NOTHING",
                list(o.values())
            )
        if rv:
            cur.executemany(
                "INSERT INTO rev(rev_id,org_key,rating,text) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (rev_id) DO NOTHING",
                rv
            )
        con.commit()

con.close()
print("ok")
