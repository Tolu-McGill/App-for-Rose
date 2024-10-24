from flask import Flask, request, render_template, redirect, url_for
from google.cloud import vision
import os
import re
import sqlite3
import hashlib
from datetime import datetime

app = Flask(__name__)

# Setup Google Cloud Vision
# IMPORTANT: You need to ensure that the GOOGLE_APPLICATION_CREDENTIALS file is available on Heroku
# You can't use a local path like C:\Users\dudeo\... on Heroku
# It's best to upload the credentials to an environment variable in Heroku's settings
# For now, remove the hardcoded path
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r"C:\Users\dudeo\Downloads\Python Project for Rose\bright-drake-439601-i4-bd1026251962.json"
client = vision.ImageAnnotatorClient()

# Get the directory where app.py is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Full path to the database file
DB_PATH = os.path.join(BASE_DIR, 'expenses.db')

# Initialize the database (create tables if they don't exist)
def init_db():
    print("Initializing the database...")  # Debugging statement
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            amount REAL,
            file_hash TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully.")  # Debugging statement

# Function to store the extracted total and hash in the database
def store_total_in_db(total_amount, file_hash):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO expenses (date, amount, file_hash) VALUES (?, ?, ?)', 
                   (datetime.now().strftime('%Y-%m-%d'), total_amount, file_hash))
    conn.commit()
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM expenses WHERE file_hash = ?', (file_hash,))
    result = cursor.fetchone()[0]
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

    # Extract the full text
    full_text = texts[0].description if texts else ""

    # Call the refined extract_total function
    total_amount = extract_total(full_text)

    if total_amount != "Total amount not found":
        store_total_in_db(float(total_amount), file_hash)

    # Optionally, delete the file after processing
    os.remove(filepath)

    return f'Total amount: {total_amount}'

def extract_total(text):
    """
    Extracts the total amount from a receipt by finding the last occurrence of 'total' and getting the number from the next line.
    """
    # Convert the text to lowercase for consistent matching
    text_lower = text.lower()

    # Split the text into lines
    lines = text_lower.split('\n')

    # Regular expression to detect numeric values (numbers with decimal points)
    money_pattern = re.compile(r'\d+[.,]?\d{2}')

    total_amount = None

    # Iterate over lines to find every occurrence of 'total'
    for i, line in enumerate(lines):
        if 'total' in line:
            # Check the next line for a numeric value
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                match = money_pattern.search(next_line)
                if match:
                    total_amount = match.group().replace(',', '')  # Remove commas if any

    # Return the last total amount found
    return total_amount if total_amount else "Total amount not found"

# Route to show monthly report of total expenses
@app.route('/report')
def report():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM expenses WHERE strftime("%Y-%m", date) = ?', 
                   (datetime.now().strftime('%Y-%m'),))
    total = cursor.fetchone()[0]
    conn.close()

    return f'Total spent this month: ${total:.2f}' if total else "No expenses recorded for this month."


if __name__ == '__main__':
    init_db()
    # Get the port from Heroku's environment variable or default to 5000 locally
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
