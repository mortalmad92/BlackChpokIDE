# Import required modules
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

# File to store comments and articles
data_file = 'finance_media/data.json'

# Ensure data file exists
if not os.path.exists(data_file):
    with open(data_file, 'w') as f:
        json.dump({"comments": [], "articles": []}, f)

# Helper function to load data from file
def load_data():
    with open(data_file, 'r') as f:
        return json.load(f)

# Helper function to save data to file
def save_data(data):
    with open(data_file, 'w') as f:
        json.dump(data, f)

# API Endpoint for adding comments
@app.route('/api/comments', methods=['POST'])
def add_comment():
    data = load_data()
    comment = request.json
    if not comment or 'text' not in comment:
        return jsonify({"error": "Invalid comment format"}), 400
    data["comments"].append(comment)
    save_data(data)
    return jsonify({"success": True})

# API Endpoint for publishing articles
@app.route('/api/articles', methods=['POST'])
def publish_article():
    data = load_data()
    article = request.json
    if not article or 'title' not in article or 'content' not in article:
        return jsonify({"error": "Invalid article format"}), 400
    data["articles"].append(article)
    save_data(data)
    return jsonify({"success": True})

# Run the app
if __name__ == '__main__':
    app.run(debug=True)