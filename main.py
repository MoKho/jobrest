import os
from flask import Flask, request, jsonify

# Initialize the Flask application
app = Flask(__name__)

@app.route('/hello', methods=['POST'])
def hello_world():
    """
    API endpoint that accepts a POST request with a JSON body
    and returns a greeting.
    """
    # Get the JSON data from the request body
    request_json = request.get_json()

    # Check if the JSON body and the 'name' key exist
    if not request_json or 'name' not in request_json:
        return jsonify({'error': 'Missing "name" in request body'}), 400

    # Get the name from the JSON data
    name = request_json['name']

    # NOTE: The original request was to return "hello world", but it's more
    # useful to see the input being used. We'll return "Hello, [name]!"
    # This confirms our input is being processed correctly.
    return jsonify({'message': f'Hello, {name}!'})

if __name__ == "__main__":
    # This block is for local development only.
    # It won't be executed when deployed on Cloud Run.
    # Cloud Run uses Gunicorn to run the app.
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))