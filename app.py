from flask import Flask, request, render_template, redirect, url_for
from google.cloud import vision
import os
import re
import psycopg2
from urllib.parse import urlparse
import hashlib
from datetime import datetime
import json
import tempfile

# Get the Google Cloud credentials JSON from the Heroku environment variable
credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')  # This assumes you set it as 'GOOGLE_APPLICATION_CREDENTIALS_JSON'

if not credentials_json:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not found")

# Write the credentials JSON to a temporary file
with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as temp_file:
    temp_file.write(credentials_json)
    temp_credentials_path = temp_file.name

# Set the environment variable GOOGLE_APPLICATION_CREDENTIALS to point to this temp file
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_credentials_path



# Initialize the Vision API client
client = vision.ImageAnnotatorClient()

app = Flask(__name__)

# Get the directory where app.py is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Full path to the database file
# DB_PATH = os.path.join(BASE_DIR, 'expenses.db')

# Initialize PostgreSQL connection
def get_db_connection():
    # Get the DATABASE_URL environment variable from Heroku
    database_url = os.environ.get('DATABASE_URL')
    
    # Parse the database URL
    result = urlparse(database_url)

    # Connect to PostgreSQL
    conn = psycopg2.connect(
        dbname=result.path[1:],  # Remove the leading '/' from the path
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    return conn


# Initialize the database (create tables if they don't exist)
def init_db():
    print("Initializing the PostgreSQL database...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date TEXT,
            amount REAL,
            file_hash TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()
    print("PostgreSQL database initialized successfully.")

# Function to store the extracted total and hash in the database
def store_total_in_db(total_amount, file_hash):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO expenses (date, amount, file_hash) VALUES (%s, %s, %s)', 
                   (datetime.now().strftime('%Y-%m-%d'), total_amount, file_hash))
    conn.commit()
    cursor.close()
    conn.close()

# Function to compute the SHA256 hash of the uploaded file
def compute_file_hash(file_path):
    """Compute the SHA256 hash of the uploaded file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_receipt():
    if 'receipt' not in request.files:
        return "No file part"
    file = request.files['receipt']

    if file.filename == '':
        return "No selected file"

    # Save the uploaded file to a relative path (Heroku uses Linux-based paths)
    upload_folder = os.path.join(BASE_DIR, 'uploads')  # Use a relative path
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    filepath = os.path.join(upload_folder, file.filename)
    file.save(filepath)

    # Compute the file hash
    file_hash = compute_file_hash(filepath)

    # Check if the file hash already exists in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM expenses WHERE file_hash = %s', (file_hash,))
    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    if result > 0:
        os.remove(filepath)  # Optionally delete the file
        return "This receipt has already been uploaded."

    # Process with Google Cloud Vision
    with open(filepath, 'rb') as image_file:
        content = image_file.read()

    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    texts = response.text_annotations

    # Extract the full text and print it for debugging
    full_text = texts[0].description if texts else ""
    print("OCR Detected Text:\n", full_text)

    # Call the refined extract_total function
    total_amount = extract_total(full_text)

    if total_amount != "Total amount not found":
        store_total_in_db(float(total_amount), file_hash)

    # Optionally, delete the file after processing
    os.remove(filepath)

    return f'Total amount: {total_amount}'

import re

def extract_total(text):
    """
    Extracts the total amount from a receipt by finding occurrences of 'total' and 'sous-total',
    then looking for numeric values on the same or next line. Supports both commas and periods as
    decimal separators.
    """
    # Convert the text to lowercase for consistent matching
    text_lower = text.lower()

    # Split the text into lines
    lines = text_lower.split('\n')

    # Regular expression to detect numeric values (e.g., 123.45 or 123,45)
    money_pattern = re.compile(r'\b\d{1,3}(?:[.,]?\d{3})*(?:[.,]\d{2})?\b')

    total_amount = None

    # Iterate over lines to find every occurrence of 'total' or 'sous-total'
    for i, line in enumerate(lines):
        if 'total' in line or 'sous-total' in line:
            # Search for a numeric value on the same line
            match = money_pattern.search(line)
            if match:
                total_amount = match.group().replace(',', '.')
                continue  # Move to the next occurrence if any

            # If no match in the same line, check the next line
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                match = money_pattern.search(next_line)
                if match:
                    total_amount = match.group().replace(',', '.')
                    continue  # Move to the next occurrence if any

    # Return the last total amount found
    return total_amount if total_amount else "Total amount not found"


# Route to show monthly report of total expenses
@app.route('/report')
def report():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM expenses WHERE date_trunc(\'month\', date::date) = date_trunc(\'month\', CURRENT_DATE)')
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    # If total is None, set it to 0.00 for display purposes
    report = f'Total spent this month: ${total:.2f}' if total else "No expenses recorded for this month."

    return render_template('report.html', report=report)

if __name__ == '__main__':
    init_db()
    # Get the port from Heroku's environment variable or default to 5000 locally
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
