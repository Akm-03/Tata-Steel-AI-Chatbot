import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # <--- ADD THIS
from pydantic import BaseModel
from dotenv import load_dotenv
import snowflake.connector
import firebase_admin
from firebase_admin import credentials, firestore
from langchain_groq import ChatGroq

load_dotenv()

app = FastAPI(title="Industrial AI Brain")

# --- ADD THIS ENTIRE CORS BLOCK ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all frontend domains to connect
    allow_credentials=True,
    allow_methods=["*"],  # Allows POST, GET, etc.
    allow_headers=["*"],
)
# Connect to Firebase
try:
    cred = credentials.Certificate("firebase-credentials.json")
    firebase_admin.initialize_app(cred)
    firestore_db = firestore.client()
    print("Firebase Admin Connection Active.")
except Exception as e:
    print(f"Error initializing Firebase: {e}")

# Helper to fetch data from Snowflake
def query_snowflake(sql_query: str):
    conn = snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA")
    )
    cursor = conn.cursor()
    try:
        cursor.execute(sql_query)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        return f"Database Error: {str(e)}"
    finally:
        cursor.close()
        conn.close()

class ChatRequest(BaseModel):
    message: str

@app.get("/")
async def root():
    return {"message": "The AI Brain is running! Please open index.html in your browser to view the Tata Steel dashboard."}
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    user_input = request.message
    
    schema_context = """
    Table: MACHINES
    Columns: ID (INT), MACHINE_NAME (VARCHAR), HARDWARE_ID (VARCHAR), OPERATION_TYPE (VARCHAR)
    
    Table: DEVIATIONS
    Columns: HARDWARE_ID (VARCHAR), START_TIME (TIMESTAMP), END_TIME (TIMESTAMP), DEVIATION_LEVEL (VARCHAR), PARAMETER_TYPE (VARCHAR)
    """
    
    system_prompt = f"""
    You are an expert industrial AI assistant. Translate the user prompt into a valid Snowflake SQL query.
    Schema: {schema_context}
    Output ONLY the executable SQL string wrapped inside code blocks: ```sql <query> ```. No explanations.
    """
    
    # --- 2. CHANGED THIS LINE TO USE LLAMA-3 ---
    llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)
    
    try:
        ai_response = llm.invoke([("system", system_prompt), ("user", user_input)])
        raw_content = ai_response.content
        sql_query = raw_content.split("```sql")[1].split("```")[0].strip() if "```sql" in raw_content else raw_content.strip()
            
        data_records = query_snowflake(sql_query)
        
        if isinstance(data_records, list) and len(data_records) > 0:
            for record in data_records[:3]:
                if str(record.get("DEVIATION_LEVEL", "")).lower() == "high" or "deviation" in user_input.lower():
                    doc_id = f"alert_{record.get('HARDWARE_ID', 'unknown')}_{record.get('PARAMETER_TYPE', 'metric')}"
                    firestore_db.collection("live_alerts").document(doc_id).set({
                        "hardwareId": record.get("HARDWARE_ID", "Unknown"),
                        "parameterType": record.get("PARAMETER_TYPE", "Metric"),
                        "deviationLevel": record.get("DEVIATION_LEVEL", "High"),
                        "sourceQuery": sql_query,
                        "timestamp": firestore.SERVER_TIMESTAMP
                    }, merge=True)
        
        synthesis_prompt = f"User asked: {user_input}\nSQL: {sql_query}\nData: {data_records}\nProvide a clean, helpful summary of this data for a factory manager."
        final_summary = llm.invoke([("user", synthesis_prompt)])
        
        return {
            "answer": final_summary.content,
            "generated_query": sql_query,
            "data": data_records
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    chart_data = None
    if "deviation" in user_input.lower() or "summary" in user_input.lower():
        # Auto-aggregate data for a chart
        agg_sql = "SELECT PARAMETER_TYPE, COUNT(*) as COUNT FROM DEVIATIONS GROUP BY PARAMETER_TYPE"
        chart_data = query_snowflake(agg_sql)

    return {
        "answer": final_summary.content,
        "generated_query": sql_query,
        "data": data_records,
        "chart_data": chart_data # <--- Add this field
    }