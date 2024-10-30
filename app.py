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
import matplotlib.pyplot as plt
from io import BytesIO
import base64

# Get Google Cloud credentials
credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
if not credentials_json:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not found")
with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as temp_file:
    temp_file.write(credentials_json)
    temp_credentials_path = temp_file.name
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_credentials_path

# Initialize Vision API client and Flask app
client = vision.ImageAnnotatorClient()
app = Flask(__name__)

# Database connection setup
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    result = urlparse(database_url)
    conn = psycopg2.connect(
        dbname=result.path[1:], user=result.username,
        password=result.password, host=result.hostname, port=result.port
    )
    return conn

# Initialize the database with additional columns for categories
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date TEXT,
            category TEXT,
            amount REAL,
            file_hash TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# Endpoint for adding expenses by category
@app.route('/add_expense', methods=['POST'])
def add_expense():
    category = request.form['category']
    amount = float(request.form['amount'])

    # Store category and amount in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO expenses (date, category, amount) VALUES (%s, %s, %s)",
                   (datetime.now().strftime('%Y-%m-%d'), category, amount))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('index'))

# Monthly report with pie chart by category
@app.route('/report')
def report():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT category, SUM(amount) FROM expenses GROUP BY category")
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    # Process data for pie chart
    categories = [row[0] for row in data]
    amounts = [row[1] for row in data]
    total_spent = sum(amounts)

    # Generate pie chart
    fig, ax = plt.subplots()
    ax.pie(amounts, labels=categories, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')

    # Convert chart to base64 for HTML rendering
    img = BytesIO()
    fig.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()

    return render_template('report.html', plot_url=plot_url, total_spent=total_spent)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
