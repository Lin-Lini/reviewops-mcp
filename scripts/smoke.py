import json, urllib.request

def g(u):
    with urllib.request.urlopen(u, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def p(u, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(u, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

print("api", g("http://localhost:8000/health"))
print("orch", g("http://localhost:9000/health"))
out = p("http://localhost:9000/chat", {"message": "Разбери негатив по кафе в Москве: причины, примеры, что улучшить", "mode": "insights"})
print("chat", {"trace_id": out.get("trace_id"), "tool_used": out.get("tool_used"), "mcp_used": out.get("mcp_used")})
tid = out.get("trace_id")
if tid:
    try:
        print("logs", g(f"http://localhost:9100/traces/{tid}"))
    except Exception as e:
        print("logs_error", str(e))