import os
import requests
from flask import Flask, request, jsonify
from google.cloud import secretmanager
from functools import wraps

from prompts import (
    JOB_EXTRACTOR_SYSTEM_PROMPT,
    RESUME_CHECKER_SYSTEM_PROMPT,
    JOB_LOCATION_MATCH_SYSTEM_PROMPT
)

# --- Model and API Endpoint Configuration ---
# These are hardcoded for simplicity, but could also be environment variables.
JOB_EXTRACTOR_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
LOCATION_FINDER_LLM = "meta-llama/llama-4-scout-17b-16e-instruct"
RESUME_CHECKER_LLM = "openai/gpt-oss-120b"
# Using Groq as an example endpoint, change if you use another provider
API_URL = "https://api.groq.com/openai/v1/chat/completions"

# --- Initialize Flask App ---
app = Flask(__name__)

def require_api_key(f):
    """A decorator to protect routes with an API key."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get the expected API key from environment variables
        expected_api_key = os.environ.get('INTERNAL_API_KEY')
        if not expected_api_key:
            # This is a server configuration error
            return jsonify({"error": "API key not configured on server."}), 500

        # Get the provided API key from the request header
        provided_key = request.headers.get('X-API-Key')
        if not provided_key or provided_key != expected_api_key:
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)
    return decorated_function



# --- Helper function to get API Key securely ---
API_KEY = None
def get_api_key():
    """
    Retrieves the API key. For Cloud Run, it fetches from Secret Manager.
    For local development, it reads from an environment variable.
    Caches the key in a global variable to avoid multiple lookups.
    """
    global API_KEY
    if API_KEY:
        return API_KEY

    # Check for local environment variable first
    local_key = os.environ.get('LLM_API_KEY')
    if local_key:
        API_KEY = local_key
        return API_KEY

    # If not local, try fetching from Google Secret Manager (for Cloud Run)
    try:
        project_id = os.environ.get("GCP_PROJECT")
        if not project_id:
            # Attempt to get project ID from gcloud config if not in env
            import subprocess
            project_id = subprocess.check_output(['gcloud', 'config', 'get-value', 'project']).strip().decode('utf-8')

        client = secretmanager.SecretManagerServiceClient()
        secret_name = "llm-api-key"  # The name of your secret
        resource_name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": resource_name})
        API_KEY = response.payload.data.decode("UTF-8")
        return API_KEY
    except Exception as e:
        print(f"Could not fetch secret from Secret Manager: {e}")
        raise Exception("API Key not found. Set LLM_API_KEY env var for local dev or configure Secret Manager for Cloud Run.")


# --- Helper function to call the LLM API ---
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
        response = requests.post(API_URL, headers=headers, json=payload)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        print(f"API Call failed: {e}")
        # Include API response body in the error if available
        error_body = e.response.text if e.response else "No response body"
        raise Exception(f"Failed to communicate with LLM API. Status: {e.response.status_code if e.response else 'N/A'}. Body: {error_body}")


# --- Original /hello endpoint ---
@app.route('/hello', methods=['POST'])
@require_api_key # <<< APPLY THE DECORATOR
def hello_world():
    request_json = request.get_json()
    if not request_json or 'name' not in request_json:
        return jsonify({'error': 'Missing "name" in request body'}), 400
    name = request_json['name']
    return jsonify({'message': f'Hello, {name}!'})


# --- NEW /analyze endpoint ---
@app.route('/analyze', methods=['POST'])
@require_api_key # <<< APPLY THE DECORATOR
def analyze_resume():
    """
    The main endpoint for the resume analysis agent.
    Expects a JSON body with "resume_text" and "job_post_text".
    """
    try:
        # 1. Get input from the request
        request_json = request.get_json()
        if not request_json:
            return jsonify({"error": "Invalid JSON in request body"}), 400

        resume_text = request_json.get('resume_text')
        job_post_text = request_json.get('job_post_text')

        if not resume_text or not job_post_text:
            return jsonify({"error": "Missing 'resume_text' or 'job_post_text' in request body"}), 400


        # 2. Execute the multi-step AI workflow
        print("Step 1: Extracting relevant job details...")
        extracted_job_details = call_llm_api(job_post_text, JOB_EXTRACTOR_SYSTEM_PROMPT, JOB_EXTRACTOR_LLM)

        print("Step 2: Extracting job location...")
        job_location = call_llm_api(job_post_text, JOB_LOCATION_MATCH_SYSTEM_PROMPT, LOCATION_FINDER_LLM)

        print("Step 3: Performing the final resume analysis...")
        analysis_prompt = f"JOB DETAILS:\n{extracted_job_details}\n\nUSER RESUME:\n{resume_text}"
        final_analysis = call_llm_api(analysis_prompt, RESUME_CHECKER_SYSTEM_PROMPT, RESUME_CHECKER_LLM)

        # 3. Combine results and send the response
        response_data = {
            "job_location": job_location,
            "resume_analysis": final_analysis
        }
        return jsonify(response_data), 200

    except Exception as e:
        print(f"An error occurred during analysis: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("Starting local server...")
    if not os.environ.get('INTERNAL_API_KEY'):
        print("\nWARNING: INTERNAL_API_KEY is not set. The API will not be accessible.")
        print("Please run: export INTERNAL_API_KEY='your-chosen-secret-key'\n")
    if not os.environ.get('LLM_API_KEY'):
        print("WARNING: LLM_API_KEY is not set. Calls to the AI will fail.")
        print("Please run: export LLM_API_KEY='your-llm-provider-key'\n")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))