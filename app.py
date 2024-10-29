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
import cv2
import numpy as np

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


def upscale_image(image, scale_factor=2):
    return cv2.resize(image, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)

def to_grayscale(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

def apply_threshold(image):
    return cv2.adaptiveThreshold(image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

def denoise_image(image):
    return cv2.fastNlMeansDenoising(image, None, 30, 7, 21)

def sharpen_image(image):
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(image, -1, kernel)

def preprocess_image(image_path):
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    upscaled_image = upscale_image(image, scale_factor=2)
    grayscale_image = to_grayscale(upscaled_image)
    thresholded_image = apply_threshold(grayscale_image)
    denoised_image = denoise_image(thresholded_image)
    final_image = sharpen_image(denoised_image)
    processed_image_path = os.path.join(os.path.dirname(image_path), "processed_" + os.path.basename(image_path))
    cv2.imwrite(processed_image_path, final_image)
    return processed_image_path

@app.route('/upload', methods=['POST'])
def upload_receipt():
    if 'receipt' not in request.files:
        return "No file part"
    file = request.files['receipt']

    if file.filename == '':
        return "No selected file"

    # Save the uploaded file temporarily
    upload_folder = os.path.join(BASE_DIR, 'uploads')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    filepath = os.path.join(upload_folder, file.filename)
    file.save(filepath)

    # Preprocess the image
    processed_image_path = preprocess_image(filepath)

    # Compute the file hash for deduplication
    file_hash = compute_file_hash(filepath)

    # Check if the file hash already exists in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM expenses WHERE file_hash = %s', (file_hash,))
    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    if result > 0:
        os.remove(filepath)
        os.remove(processed_image_path)  # Clean up
        return "This receipt has already been uploaded."

    # Process with Google Cloud Vision
    with open(processed_image_path, 'rb') as image_file:
        content = image_file.read()
    
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    texts = response.text_annotations

    # Extract text and print for debugging
    full_text = texts[0].description if texts else ""
    print("OCR Detected Text:\n", full_text)

    # Extract the total amount from text
    total_amount = extract_total(full_text)

    if total_amount != "Total amount not found":
        store_total_in_db(float(total_amount), file_hash)

    # Clean up files
    os.remove(filepath)
    os.remove(processed_image_path)

    return f'Total amount: {total_amount}'


def extract_total(text):
    """
    Extracts the total amount from a receipt by capturing all monetary values and selecting the largest.
    """
    # Convert text to lowercase for consistent matching
    text_lower = text.lower()

    # Regex pattern to detect both English and French currency formats
    money_pattern = re.compile(r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b')
    
    # Find all monetary values
    amounts = money_pattern.findall(text_lower)
    
    # Normalize and convert matched values to floats
    numeric_amounts = []
    for amount in amounts:
        # Replace thousand separators and ensure proper decimal formatting
        normalized_amount = amount.replace(',', '').replace('.', '')  # Remove separators
        numeric_amount = float(normalized_amount[:-2] + '.' + normalized_amount[-2:])  # Format as float
        numeric_amounts.append(numeric_amount)
    
    # Return the largest amount if any were found
    return max(numeric_amounts) if numeric_amounts else "Total amount not found"



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
    
