import os
import requests
from flask import Flask, request, jsonify, g
from functools import wraps
from datetime import datetime
from flask_cors import CORS

# Import database-related tools
from models import db, User

# Import prompts from our dedicated file
from prompts import (
    JOB_EXTRACTOR_SYSTEM_PROMPT,
    RESUME_CHECKER_SYSTEM_PROMPT,
    JOB_LOCATION_MATCH_SYSTEM_PROMPT
)

# --- App Initialization ---
app = Flask(__name__)
CORS(app)

if os.environ.get("DB_USER"):
    # Production environment (Cloud Run)
    DB_USER = os.environ.get("DB_USER")
    DB_PASS = os.environ.get("DB_PASS")
    DB_NAME = os.environ.get("DB_NAME")
    INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME")
    # The Cloud SQL Python Connector provides the best security practices
    # by using IAM authentication and encrypting traffic.
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@/"
        f"{DB_NAME}?host=/cloudsql/{INSTANCE_CONNECTION_NAME}"
    )
else:
    # Local development environment
    project_dir = os.path.dirname(os.path.abspath(__file__))
    database_file = f"sqlite:///{os.path.join(project_dir, 'users.db')}"
    app.config["SQLALCHEMY_DATABASE_URI"] = database_file

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
 

# --- Database Configuration ---
project_dir = os.path.dirname(os.path.abspath(__file__))
database_file = f"sqlite:///{os.path.join(project_dir, 'users.db')}"
app.config["SQLALCHEMY_DATABASE_URI"] = database_file
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# --- Model and LLM API Configuration ---
JOB_EXTRACTOR_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
LOCATION_FINDER_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
RESUME_CHECKER_LLM = "openai/gpt-oss-120b"
API_URL = "https://api.groq.com/openai/v1/chat/completions"

# --- Google Token Authentication Decorator (No changes here) ---
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # ... (This function is correct and remains the same)
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"error": "Malformed Bearer token"}), 401
        if not token:
            return jsonify({"error": "Authorization token is missing"}), 401
        try:
            validation_url = f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={token}"
            response = requests.get(validation_url)
            response.raise_for_status()
            token_info = response.json()
            google_id = token_info.get('sub')
            if not google_id:
                return jsonify({"error": "Invalid token: 'sub' claim missing"}), 401
            user = User.query.filter_by(google_id=google_id).first()
            if not user:
                print(f"Creating new user for Google ID: {google_id}")
                user = User(
                    google_id=google_id,
                    email=token_info.get('email'),
                    name=token_info.get('name')
                )
                db.session.add(user)
                db.session.commit()
            g.current_user = user
        except requests.exceptions.HTTPError as e:
            print(f"Token validation failed: {e.response.text}")
            return jsonify({"error": "Invalid or expired token"}), 401
        except Exception as e:
            print(f"An unexpected error occurred during auth: {e}")
            return jsonify({"error": "Authentication failed"}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- Helper functions for LLM API (CORRECTED) ---

# Global cache for the API key
LLM_API_KEY_CACHE = None

def get_api_key():
    """
    Retrieves the LLM API key. For now, it only reads from an environment variable.
    Caches the key in a global variable to avoid reading the env var on every call.
    """
    global LLM_API_KEY_CACHE
    if LLM_API_KEY_CACHE:
        return LLM_API_KEY_CACHE

    api_key = os.environ.get('LLM_API_KEY')
    if not api_key:
        raise Exception("LLM_API_KEY environment variable not set.")
    
    LLM_API_KEY_CACHE = api_key
    return api_key

def call_llm_api(prompt, system_prompt, model):
    """Generic function to call an OpenAI-compatible LLM API."""
    api_key = get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        error_body = e.response.text if e.response else "No response body"
        print(f"API Call failed: Status {e.response.status_code if e.response else 'N/A'}. Body: {error_body}")
        raise Exception("Failed to communicate with LLM API.")

# --- API Endpoints (No changes here, already correct) ---

@app.route('/hello', methods=['POST'])
@token_required
def hello_world():
    # ... (remains the same)
    pass

@app.route('/analyze', methods=['POST'])
@token_required
def analyze_resume():
    # ... (This function is already correct from the last fix)
    print(f"Analysis request from user: {g.current_user.email}")
    try:
        request_json = request.get_json()
        if not request_json:
            return jsonify({"error": "Invalid JSON in request body"}), 400
        resume_text = request_json.get('resume_text')
        job_post_text = request_json.get('job_post_text')
        if not resume_text or not job_post_text:
            return jsonify({"error": "Missing 'resume_text' or 'job_post_text' in request body"}), 400
        
        print("Step 1: Extracting relevant job details...")
        extracted_job_details = call_llm_api(job_post_text, JOB_EXTRACTOR_SYSTEM_PROMPT, JOB_EXTRACTOR_LLM)
        
        print("Step 2: Extracting job location...")
        job_location = call_llm_api(job_post_text, JOB_LOCATION_MATCH_SYSTEM_PROMPT, LOCATION_FINDER_LLM)
        
        print("Step 3: Performing the final resume analysis...")
        analysis_prompt = f"JOB DETAILS:\n{extracted_job_details}\n\nUSER RESUME:\n{resume_text}"
        final_analysis = call_llm_api(analysis_prompt, RESUME_CHECKER_SYSTEM_PROMPT, RESUME_CHECKER_LLM)
        
        response_data = {
            "job_location": job_location,
            "resume_analysis": final_analysis
        }
        return jsonify(response_data), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# --- Database Initialization (No changes here) ---
def init_db():
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Database tables created.")

if __name__ == "__main__":
    if not os.path.exists('users.db'):
        init_db()
    if not os.environ.get('LLM_API_KEY'):
        print("\nWARNING: LLM_API_KEY is not set. Calls to the AI will fail.")
        print("Please run: export LLM_API_KEY='your-llm-provider-key'\n")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))