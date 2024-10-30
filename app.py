from flask import Flask, request, render_template, redirect, url_for
import os
import psycopg2
from urllib.parse import urlparse
from datetime import datetime
import json
from collections import defaultdict
import matplotlib.pyplot as plt
import io
import base64

# Initialize the Flask app
app = Flask(__name__)

# Initialize PostgreSQL connection
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    result = urlparse(database_url)
    conn = psycopg2.connect(
        dbname=result.path[1:], 
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
            date DATE,
            amount REAL,
            category TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()
    print("PostgreSQL database initialized successfully.")

# Route to show the index page
@app.route('/')
def index():
    return render_template('index.html')

# Route to add a new expense
@app.route('/add_expense', methods=['POST'])
def add_expense():
    # Get form data
    amount = request.form.get('amount')
    category = request.form.get('category')
    
    if not amount or not category:
        return "Amount and category are required."

    # Store the expense in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO expenses (date, amount, category) VALUES (%s, %s, %s)', 
        (datetime.now().date(), float(amount), category)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('index'))

# Route to show the monthly report with a pie chart
@app.route('/report')
def report():
    # Fetch data from the database for the current month
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category, SUM(amount) 
        FROM expenses 
        WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
        GROUP BY category
    ''')
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()

    # Process data for display
    categories = []
    amounts = []
    for category, amount in expenses:
        categories.append(category)
        amounts.append(amount)
    
    # Generate pie chart
    fig, ax = plt.subplots()
    ax.pie(amounts, labels=categories, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')
    plt.title("Monthly Spending by Category")

    # Save plot to a PNG image in memory
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()

    return render_template('report.html', plot_url=plot_url)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
