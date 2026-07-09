"""
server.py — Tata Steel Chatbot Backend
Multi-LLM router: Groq → Gemini → OpenRouter → Ollama (auto-failover)
Run: uvicorn server:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, re, json, uuid, psycopg2
from dotenv import load_dotenv

from llm_router import router   # ← replaces direct Groq client

load_dotenv()

app = FastAPI(title="Tata Steel Ops Chatbot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict = {}

# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPT  (unchanged from fixed version)
# ══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """
You are the Tata Steel Operations Intelligence Assistant — an enterprise AI
connected to a live PostgreSQL database with real machine sensor data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MACHINE TYPES & MACHINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GMAW  — 14 welding machines: D&H-1 to D&H-14
   Fixed thresholds: high_weld_cur=270A, low_weld_cur=220A,
                     high_weld_volt=30V, low_weld_volt=20V,
                     high_weld_gas=30 L/min, low_weld_gas=20 L/min
2. CLAD  — 2 cladding rectifiers: Rectifier1, Rectifier2
3. GASCUTTING — 1 torch: GasCutting1

SHIFTS: A, B, C  (stored exactly as 'A', 'B', 'C' — NOT 'Shift A')

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERIFIED DATABASE SCHEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TABLE: reference.dim_machines
  mid, name, hardware_id, machine_type_name, is_gmaw, is_clad, is_gascutting, deleted

TABLE: gmaw.fact_periodic_gmaw
  pdid, business_date (date), shift_name ('A','B','C'),
  machine_type, machine_name, hardware_id, job_name, tm (timestamptz),
  weld_cur (float, A), weld_volt (float, V), weld_gas (float, L/min),
  hs_temp (float, °C), amb_temp (float, °C), rpm (float, RPM),
  is_idle (boolean), is_welding (boolean), mstatus (varchar),
  current_deviation_flag (varchar: '0'/'1'/'2'),
  voltage_deviation_flag (varchar: '0'/'1'/'2'),
  gas_deviation_flag (varchar: '0'/'1'/'2'),
  network (float, dBm),
  high_weld_cur_threshold (float, A), low_weld_cur_threshold (float, A),
  high_weld_volt_threshold (float, V), low_weld_volt_threshold (float, V),
  high_weld_gas_threshold (float, L/min), low_weld_gas_threshold (float, L/min),
  thickness (float, mm), oid
  ⚠ MANDATORY: WHERE is_welding = TRUE

TABLE: gmaw.fact_machine_derived_gmaw
  business_date, shift_name ('A','B','C'), machine_type, machine_name, oid,
  active (float, MINUTES), idle (float, MINUTES),
  breakdown (float, MINUTES), inrepair (float, MINUTES),
  target_arc_time (float, MINUTES),
  deposit (float, GRAMS), target_deposit (float, GRAMS),
  arc_efficiency_pct (float, %), deposit_efficiency_pct (float, %), mid

TABLE: gmaw.fact_deviation
  hardware_id, mid, machine_name, machine_type,
  oid, shid, start_tm (timestamptz), end_tm (timestamptz),
  span_seconds (float, seconds), type ('high'/'low'),
  parameter ('weld_cur','weld_volt','weld_gas','hs_temp','amb_temp'),
  deviation_label (e.g.'weld_cur_high'),
  parameter_unit ('A','V','L/min','°C'),
  is_gmaw (boolean), is_clad (boolean)

TABLE: gascutting.fact_summarize_gascutting
  business_date, shift_name ('A','B'),
  machine_type, machine_name,
  on_time (timestamptz), off_time (timestamptz),
  time_span (varchar), time_span_seconds (float),
  timer_overflow (boolean), travel_outlier (boolean), no_cutting (boolean),
  net_travel_in_mm (float, mm), mm_per_min (float, mm/min), speed_valid (boolean),
  thickness (float, mm — NULL for 34% rows), thickness_recorded (boolean),
  cut_mm_mtr (float),
  net_lpg_consumption (float, litres — 87% rows=0, below detection),
  lpg_below_detection (boolean),
  net_o2_consumption_meter1 (float, litres — 73% rows=0),
  net_o2_consumption_meter2 (float, litres — 93% rows=0),
  total_o2_consumption (float, litres)
  ⚠ MANDATORY: WHERE timer_overflow = FALSE AND travel_outlier = FALSE

TABLE: gascutting.fact_summarize_gascutting_noncutting
  business_date, shift_name ('A','B'),
  machine_type, machine_name, operation_category,
  on_time, off_time, time_span, time_span_seconds,
  is_instantaneous (boolean), timer_overflow (boolean), no_movement (boolean),
  net_travel_in_mm (float, mm), mm_per_min (float, mm/min),
  speed_unreliable (boolean),
  total_lpg_cons (float, litres — 99% nonzero, mean=106L),
  lpg_below_detection (boolean),
  total_heating_o2 (float, litres — 98% nonzero, mean=28.6L)
  ⚠ MANDATORY: WHERE speed_unreliable = FALSE

TABLE: gascutting.fact_periodic_gascutting
  pdid, business_date, shift_name, machine_type, machine_name, hardware_id,
  job_name, tm (timestamptz), mstatus,
  lpg_flow (float, L/min), o2_flow_meter1 (float, L/min), o2_flow_meter2 (float, L/min),
  total_lpg_consumption (float, litres — CUMULATIVE RUNNING COUNTER per row, NOT per-session total — NEVER SUM this column),
  total_o2_consumption_meter1 (float, litres — CUMULATIVE RUNNING COUNTER — NEVER SUM),
  total_o2_consumption_meter2 (float, litres — CUMULATIVE RUNNING COUNTER — NEVER SUM),
  travel_in_mm (float, mm), position_x (float, mm), position_y (float, mm),
  is_cutting (boolean), lpg_below_detection (boolean), thickness (float, mm)
  ⚠ WARNING: This table has NO timer_overflow, NO travel_outlier columns — NEVER add those filters here.
  ⚠ Use lpg_flow for instantaneous flow rates. For LPG totals use fact_summarize_gascutting_noncutting.total_lpg_cons.

TABLE: clad.fact_summarize_clad
  business_date, shift_name ('A','B','C'),
  machine_type, machine_name (Rectifier1/Rectifier2), oid,
  ontime (timestamptz), offtime (timestamptz),
  time_span (varchar), time_span_seconds (float), computed_duration_sec (float),
  is_instantaneous (boolean — TRUE for 32% rows),
  avg_weld_cur (float, A — all rows have data, mean=85.6A),
  cur_range ('zero','low','normal','high','very_high'),
  avg_weld_volt (float, V — all rows have data, mean=7.9V),
  volt_range (varchar),
  loss_weight (float, GRAMS — only 3.3% rows nonzero; sensor intermittent)
  ⚠ MANDATORY: WHERE is_instantaneous = FALSE

VIEWS (prefer these):
  gmaw.v_gmaw_shift_efficiency     — business_date, shift_name, machine_name, active_minutes, idle_minutes, arc_efficiency_pct, deposit, deposit_efficiency_pct
  gmaw.v_gmaw_sensor_averages      — business_date, shift_name, machine_name, avg_weld_cur_a, avg_weld_volt_v, avg_weld_gas_lmin, avg_hs_temp_c, avg_amb_temp_c
  gascutting.v_gascutting_productivity — business_date, shift_name, machine_name, total_cuts, avg_cut_speed_mm_per_min, avg_thickness_mm, total_travel_metres, total_lpg_litres, total_o2_litres
  clad.v_clad_session_summary      — business_date, shift_name, machine_name, total_sessions, valid_sessions, avg_current_a, avg_voltage_v, total_loss_weight_grams, total_arc_time_minutes
  reference.v_deviation_summary    — machine_type, machine_name, parameter, parameter_unit, deviation_direction, event_count, avg_duration_seconds

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SQL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Always schema-qualify: gmaw., gascutting., clad., reference.
2. Always include mandatory filters (⚠ above)
3. ROUND(col::NUMERIC, 2) for all floats
4. LIMIT 100 unless aggregating
5. shift_name values: 'A','B','C' — NEVER 'Shift A'
6. NEVER use window functions (LAG/ROW_NUMBER) inside UNION ALL — use CTEs
7. arc_efficiency_pct exists ONLY in gmaw.fact_machine_derived_gmaw — never reference in CLAD/GASCUTTING
8. Output raw SQL only — no markdown, no explanation
9. arc_efficiency_pct sanity: always add WHERE arc_efficiency_pct BETWEEN 0 AND 200 when querying this column
10. NEVER apply timer_overflow or travel_outlier filters to gascutting.fact_periodic_gascutting — those columns only exist in fact_summarize_gascutting
11. CLAD efficiency = ROUND(valid_sessions::NUMERIC / NULLIF(total_sessions,0) * 100, 2) — use NULLIF to avoid divide-by-zero; result is a percentage
12. For LPG/O2 consumption totals always use fact_summarize_gascutting (net_lpg_consumption) or fact_summarize_gascutting_noncutting (total_lpg_cons) — NEVER sum total_lpg_consumption from fact_periodic_gascutting

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Always name machine type and machine name
2. Units after every number: A, V, L/min, °C, mm, mm/min, g, %, minutes, litres, dBm
3. GMAW weld averages → "during active welding (idle excluded)"
4. GASCUTTING → "excluding timer overflow and outlier rows"
5. CLAD → "valid sessions only (instantaneous events excluded)"
6. LPG/O2 = 0 → "below meter detection limit — actual consumption may be higher"
7. loss_weight = 0 → "loss weight sensor was not recording this session"
8. 0 rows returned → "No data found for [date/filter] — check available date range"
9. End with one specific follow-up suggestion
"""

EDGE_CASES = """
EDGE CASES — handle these explicitly:
- "current consumption": use AVG(weld_cur) for GMAW (is_welding=TRUE), AVG(avg_weld_cur) for CLAD.
  Never calculate weld_cur × time — no time-delta col exists.
- "efficiency": GMAW → arc_efficiency_pct from fact_machine_derived_gmaw only, always filtered WHERE arc_efficiency_pct BETWEEN 0 AND 200.
  CLAD → ROUND(valid_sessions::NUMERIC / NULLIF(total_sessions,0) * 100, 2) from clad.v_clad_session_summary.
  GASCUTTING → avg_cut_speed_mm_per_min from gascutting.v_gascutting_productivity.
  NEVER UNION arc_efficiency_pct across machine types.
- LPG totals: ALWAYS use gascutting.fact_summarize_gascutting_noncutting.total_lpg_cons (99% nonzero, per-session value).
  fact_summarize_gascutting.net_lpg_consumption is 87% zero (below detection limit).
  NEVER use fact_periodic_gascutting.total_lpg_consumption for totals — it is a cumulative running counter and will give astronomically wrong results when summed.
- gascutting.fact_periodic_gascutting: has NO timer_overflow column, NO travel_outlier column.
  NEVER add WHERE timer_overflow = FALSE or WHERE travel_outlier = FALSE to queries against this table.
  Use it only for: lpg_flow (instantaneous rate), position_x/y, travel_in_mm, is_cutting.
- loss_weight in CLAD: only 3.3% nonzero — always state caveat.
- "last shift" / "today": do NOT assume date — use MAX(business_date) from the table.
- Window functions + UNION ALL = PostgreSQL error. Use WITH cte AS (...) instead.
- Arc efficiency > 200% or < 0% is a data artifact — always filter WHERE arc_efficiency_pct BETWEEN 0 AND 200.
"""

OUT_OF_SCOPE = [
    "salary","payroll","hr ","human resources","leave","holiday",
    "recruitment","appraisal","finance","stock market","share price",
    "weather","news","sports","politics","recipe","joke",
]

# ══════════════════════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════════════════════
def get_conn():
    return psycopg2.connect(
        host=os.getenv("PG_HOST","localhost"),
        port=int(os.getenv("PG_PORT","5432")),
        dbname=os.getenv("PG_DATABASE","tata_steel_ops"),
        user=os.getenv("PG_USER","postgres"),
        password=os.getenv("PG_PASSWORD",""),
    )

BLOCK_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE
)

def execute_sql(sql: str) -> dict:
    sql = sql.strip()
    if BLOCK_RE.search(sql):
        return {"error":"Only SELECT queries are allowed.","rows":[],"row_count":0}
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        return {"error":"Only SELECT queries are allowed.","rows":[],"row_count":0}
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SET search_path TO gmaw,gascutting,clad,reference,public;")
        cur.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchmany(200)]
            res  = {"columns":cols,"rows":rows,"row_count":len(rows),"error":None}
        else:
            res  = {"columns":[],"rows":[],"row_count":0,"error":None}
        cur.close(); conn.close()
        return res
    except Exception as e:
        try: conn.rollback(); conn.close()
        except: pass
        return {"error":str(e),"rows":[],"row_count":0}

# ══════════════════════════════════════════════════════════════
# LLM WRAPPERS  (use router instead of direct Groq)
# ══════════════════════════════════════════════════════════════
def strip_fences(t: str) -> str:
    t = re.sub(r"```(?:sql|json)?\s*","",t)
    t = re.sub(r"\s*```","",t)
    return t.strip()

def classify(question: str):
    if any(k in question.lower() for k in OUT_OF_SCOPE):
        return "out_of_scope", []
    prompt = (
        'Classify this Tata Steel operations question. Reply with JSON only.\n'
        'Categories: "data_query","general","out_of_scope","ambiguous"\n'
        'Format: {"category":"...","machine_types":["GMAW","CLAD","GASCUTTING","ALL"]}\n'
        f'Question: {question}'
    )
    try:
        raw = router.call(
            system="You are a classifier for a Tata Steel chatbot. Reply valid JSON only.",
            user=prompt, max_tokens=120, mode="fast"
        )
        raw = strip_fences(raw)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        d = json.loads(m.group(0)) if m else {}
        return d.get("category","data_query"), d.get("machine_types",["ALL"])
    except:
        return "data_query", ["ALL"]

def gen_sql(question: str, machine_types: list) -> str:
    sql = router.call(
        system=SYSTEM_PROMPT + "\n" + EDGE_CASES,
        user=(
            f"Question: {question}\n"
            f"Machine types: {', '.join(machine_types)}\n"
            "Generate ONLY raw PostgreSQL SELECT. No markdown. No explanation.\n"
            "Use CTE (WITH) if you need window functions. shift_name='A'/'B'/'C'."
        ),
        max_tokens=700, mode="smart"
    )
    sql = strip_fences(sql)
    m = re.search(r'((?:WITH|SELECT)\b.*)', sql, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else sql

def fix_sql(bad_sql: str, error: str) -> str:
    fixed = router.call(
        system=SYSTEM_PROMPT + "\n" + EDGE_CASES,
        user=(
            f"Fix this PostgreSQL query:\n{bad_sql}\n\n"
            f"Error: {error}\n\n"
            "Return ONLY corrected SQL. No markdown.\n"
            "Remember: no window functions in UNION ALL — use CTEs."
        ),
        max_tokens=700, mode="smart"
    )
    fixed = strip_fences(fixed)
    m = re.search(r'((?:WITH|SELECT)\b.*)', fixed, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else fixed

def format_answer(question: str, sql: str, result: dict, history: list) -> str:
    preview = json.dumps(result["rows"][:20], indent=2, default=str)
    if result["row_count"] > 20:
        preview += f"\n... and {result['row_count']-20} more rows"
    no_data = (
        "\nIMPORTANT: Zero rows returned. Likely cause: date not in dataset. "
        "Data covers 2024-2026. Tell user to check the date range."
        if result["row_count"] == 0 else ""
    )
    return router.call(
        system=SYSTEM_PROMPT + "\n" + EDGE_CASES,
        user=(
            f"User asked: {question}\n\n"
            f"SQL:\n{sql}\n\n"
            f"Results ({result['row_count']} rows):\n{preview}{no_data}\n\n"
            "Write a professional response following ALL RESPONSE RULES."
        ),
        max_tokens=1000, mode="smart", history=history
    )

# ══════════════════════════════════════════════════════════════
# MODELS & ENDPOINTS
# ══════════════════════════════════════════════════════════════
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    show_sql: Optional[bool] = False

@app.get("/health")
def health():
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gmaw.fact_periodic_gmaw")
        count = cur.fetchone()[0]
        conn.close(); db_ok = True
    except Exception as e:
        db_ok = False; count = 0

    return {
        "status":        "ok" if db_ok else "db_error",
        "db_connected":  db_ok,
        "gmaw_rows":     count,
        "llm_providers": router.status(),   # ← shows which providers are active/cooling
    }

@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    sid      = req.session_id or str(uuid.uuid4())
    history  = sessions.get(sid, [])
    question = req.message.strip()

    category, machine_types = classify(question)
    sql_used = None

    if category == "out_of_scope":
        answer = (
            "I'm the Tata Steel Operations Intelligence Assistant. "
            "I can only help with machine performance, sensor readings, shift efficiency, "
            "deviation events, and operational data for GMAW, CLAD, and GasCutting1.\n\n"
            "Could you rephrase in terms of machine operations?"
        )

    elif category == "ambiguous":
        answer = router.call(
            system=SYSTEM_PROMPT,
            user=(
                f"User asked: '{question}'\n"
                "Ask one short clarifying question: which machine type "
                "(GMAW/CLAD/GASCUTTING) or time period?"
            ),
            max_tokens=200, mode="fast", history=history
        )

    elif category == "general":
        answer = router.call(
            system=SYSTEM_PROMPT, user=question,
            max_tokens=500, mode="smart", history=history
        )

    else:
        sql_used = gen_sql(question, machine_types)
        result   = execute_sql(sql_used)

        if result.get("error"):
            print(f"[SQL ERR] {result['error']}\n[SQL] {sql_used}")
            sql_used = fix_sql(sql_used, result["error"])
            result   = execute_sql(sql_used)

        if result.get("error"):
            answer = (
                f"Database error: `{result['error']}`\n"
                "Please try rephrasing your question."
            )
        else:
            answer = format_answer(question, sql_used, result, history)

    history.append({"role":"user",      "content": question})
    history.append({"role":"assistant", "content": answer})
    sessions[sid] = history[-40:]

    return {
        "response":   answer,
        "session_id": sid,
        "sql_used":   sql_used if req.show_sql else None,
        "category":   category,
    }

@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"status": "cleared"}
