from __future__ import annotations

import os, time
import jwt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
ROOT_API_KEY = os.getenv("ROOT_API_KEY", "")

app = FastAPI(title="reviewops-security", version="0.1.0")

class TokenOut(BaseModel):
    token: str
    exp: int

class VerifyIn(BaseModel):
    token: str

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/token", response_model=TokenOut)
def issue_token(x_api_key: str | None = Header(default=None)):
    if not ROOT_API_KEY:
        raise HTTPException(status_code=500, detail="ROOT_API_KEY not set")
    if not x_api_key or x_api_key != ROOT_API_KEY:
        raise HTTPException(status_code=401, detail="bad api key")
    exp = int(time.time()) + 60*60*24
    payload = {"sub": "root", "iat": int(time.time()), "exp": exp}
    t = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {"token": t, "exp": exp}

@app.post("/verify")
def verify(v: VerifyIn):
    try:
        payload = jwt.decode(v.token, JWT_SECRET, algorithms=["HS256"])
        return {"ok": True, "payload": payload}
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
