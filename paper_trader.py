import csv, json, os, sqlite3
from datetime import datetime, timezone
import requests

GAMMA="https://gamma-api.polymarket.com/markets"
OR_URL="https://openrouter.ai/api/v1/chat/completions"
DB="paper_trader.db"; STATE="state.json"; TRADES="trades.csv"
START=float(os.getenv("STARTING_BANKROLL","50")); MIN_EDGE=float(os.getenv("MIN_EDGE","0.08")); MAX_RISK=float(os.getenv("MAX_RISK_PCT","0.06")); MAX_OPEN=int(os.getenv("MAX_OPEN_POSITIONS","5")); MIN_LIQ=float(os.getenv("MIN_LIQUIDITY","5000")); MODEL=os.getenv("OPENROUTER_MODEL","openrouter/free")

def now(): return datetime.now(timezone.utc).isoformat()
def num(x):
    try:return float(x)
    except:return None
def prices(m):
    x=m.get("outcomePrices")
    if isinstance(x,str):
        try:x=json.loads(x)
        except:x=None
    return [num(v) for v in x] if isinstance(x,list) else []
def mprice(m):
    p=prices(m); return p[0] if p and p[0] is not None else num(m.get("lastTradePrice"))
def hours(m):
    d=m.get("endDate")
    if not d:return None
    try:return (datetime.fromisoformat(d.replace("Z","+00:00"))-datetime.now(timezone.utc)).total_seconds()/3600
    except:return None
def get_markets():
    r=requests.get(GAMMA,params={"active":"true","closed":"false","limit":1000},timeout=30);r.raise_for_status();x=r.json();return x if isinstance(x,list) else x.get("data",[])
def get_market(i):
    r=requests.get(GAMMA+"/"+str(i),timeout=20);return r.json() if r.status_code==200 else None
def init_db():
    c=sqlite3.connect(DB);c.execute("CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,market_id TEXT,question TEXT,side TEXT,entry REAL,fair REAL,edge REAL,size REAL,status TEXT,pnl REAL,settled_at TEXT)");c.commit();return c
def load_state():
    if os.path.exists(STATE):return json.load(open(STATE))
    return {"bankroll":START,"peak":START,"open":[],"runs":0,"halted":False}
def save_state(s):json.dump(s,open(STATE,"w"),indent=2)
def candidates(ms):
    a=[]
    for m in ms:
        if not m.get("active") or m.get("closed") or (num(m.get("liquidity")) or 0)<MIN_LIQ:continue
        p=mprice(m);h=hours(m)
        if p is None or p<=.02 or p>=.98 or (h is not None and h<2):continue
        a.append(m)
    a.sort(key=lambda m:num(m.get("liquidity")) or 0,reverse=True);return a[:20]

def parse_ai_response(text):
    """Safely parse JSON from an LLM response. A malformed response skips the cycle."""
    if not isinstance(text,str): return {"markets":[]}
    text=text.strip()
    if text.startswith("```"):
        text=text.replace("```json","",1).replace("```","",1).strip()
    try:
        data=json.loads(text)
        return data if isinstance(data,dict) else {"markets":[]}
    except json.JSONDecodeError:
        start=text.find("{"); end=text.rfind("}")
        if start>=0 and end>start:
            try:
                data=json.loads(text[start:end+1])
                return data if isinstance(data,dict) else {"markets":[]}
            except json.JSONDecodeError:
                pass
    print("AI returned malformed JSON; skipping this cycle instead of failing the workflow.")
    return {"markets":[]}

def ask_ai(ms):
    key=os.getenv("OPENROUTER_API_KEY")
    if not key:raise RuntimeError("OPENROUTER_API_KEY missing")
    data=[{"id":str(m.get("id")),"question":m.get("question",""),"description":(m.get("description") or "")[:1800],"resolution_source":m.get("resolutionSource",""),"prices":prices(m),"liquidity":num(m.get("liquidity")) or 0,"end":m.get("endDate"),"hours":hours(m)} for m in ms]
    prompt=("You are a cautious prediction-market paper trader. Use ONLY the supplied market information. Do not invent facts, news, sources, or certainty. Choose YES, NO, or SKIP. Only trade when you can justify a fair probability. A trade requires at least 0.08 edge. Return ONLY JSON with key markets, where each item has id, decision, fair_probability, confidence, reason. MARKETS:\n"+json.dumps(data,ensure_ascii=False))
    r=requests.post(OR_URL,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json={"model":MODEL,"messages":[{"role":"system","content":"Return only valid JSON."},{"role":"user","content":prompt}],"temperature":0.1},timeout=90);r.raise_for_status()
    return parse_ai_response(r.json()["choices"][0]["message"]["content"])
def half_kelly(prob,price):
    if price<=0 or price>=1:return 0
    b=(1-price)/price;return max(0,(((b*prob)-(1-prob))/b)/2)
def settle(s,c):
    keep=[]
    for p in s["open"]:
        m=get_market(p["market_id"])
        if not m or m.get("active") or not m.get("closed"):keep.append(p);continue
        z=prices(m)
        if not z or z[0] is None or not(z[0]>=.99 or z[0]<=.01):keep.append(p);continue
        yes=z[0]>=.99;won=(p["side"]=="YES" and yes) or (p["side"]=="NO" and not yes);pnl=(p["size"]/p["entry"] if won else 0)-p["size"];s["bankroll"]+=pnl
        c.execute("UPDATE trades SET status='SETTLED',pnl=?,settled_at=? WHERE id=?",(pnl,now(),p["trade_id"]))
    s["open"]=keep
def open_trades(s,c,ms,a):
    by={str(m.get("id")):m for m in ms};ids={p["market_id"] for p in s["open"]}
    for x in a.get("markets",[]):
        if len(s["open"])>=MAX_OPEN:break
        mid=str(x.get("id"));m=by.get(mid);dec=str(x.get("decision","SKIP")).upper();fair=num(x.get("fair_probability"));conf=num(x.get("confidence")) or 0
        if not m or mid in ids or dec not in ("YES","NO") or fair is None or not 0<=fair<=1 or conf<.55:continue
        yp=mprice(m)
        if yp is None:continue
        entry=yp if dec=="YES" else 1-yp;fp=fair if dec=="YES" else 1-fair;edge=fp-entry
        if edge<MIN_EDGE:continue
        size=min(s["bankroll"]*half_kelly(fp,entry),s["bankroll"]*MAX_RISK)
        if size<.50:continue
        s["bankroll"]-=size
        tid=c.execute("INSERT INTO trades(created_at,market_id,question,side,entry,fair,edge,size,status) VALUES(?,?,?,?,?,?,?,?,?)",(now(),mid,m.get("question",""),dec,entry,fp,edge,size,"OPEN")).lastrowid
        s["open"].append({"trade_id":tid,"market_id":mid,"side":dec,"entry":entry,"size":size});ids.add(mid)
def export_csv(c):
    rows=c.execute("SELECT * FROM trades ORDER BY id").fetchall();cols=[x[1] for x in c.execute("PRAGMA table_info(trades)").fetchall()]
    with open(TRADES,"w",newline="") as f:w=csv.writer(f);w.writerow(cols);w.writerows(rows)
def main():
    c=init_db();s=load_state();settle(s,c)
    if not s.get("halted"):
        ms=get_markets();cs=candidates(ms);a=ask_ai(cs);open_trades(s,c,cs,a);s["runs"]+=1;s["last_run"]=now();s["peak"]=max(s["peak"],s["bankroll"]);dd=1-s["bankroll"]/s["peak"] if s["peak"] else 0;s["halted"]=dd>=.40
    save_state(s);c.commit();export_csv(c);print(json.dumps(s,indent=2));c.close()
if __name__=="__main__":main()
