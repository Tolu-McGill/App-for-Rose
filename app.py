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

# Initialize the database
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date TEXT,
            amount REAL,
            category TEXT,
            file_hash TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

# Modified Index Route to Include Current Month Entries
@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total spending for the month
    cursor.execute('''
        SELECT SUM(amount) 
        FROM expenses 
        WHERE date_trunc('month', date::date) = date_trunc('month', CURRENT_DATE)
    ''')
    total_spent = cursor.fetchone()[0]

    # Entries for the current month
    cursor.execute('''
        SELECT date, amount, category 
        FROM expenses 
        WHERE date_trunc('month', date::date) = date_trunc('month', CURRENT_DATE)
        ORDER BY date DESC
    ''')
    current_entries = cursor.fetchall()

    cursor.close()
    conn.close()
    total_spent = total_spent if total_spent else 0.0
    return render_template('index.html', total_spent=total_spent, current_entries=current_entries)

# Route to add a new expense
@app.route('/add_expense', methods=['POST'])
def add_expense():
    amount = request.form.get('amount')
    category = request.form.get('category')
    if not amount or not category:
        return "Amount and category are required."

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

# Monthly report route
@app.route('/report')
def report():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category, SUM(amount) 
        FROM expenses 
        WHERE date_trunc('month', date::date) = date_trunc('month', CURRENT_DATE)
        GROUP BY category
    ''')
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()

    expenses_by_category = {category: amount for category, amount in expenses}
    total_spent = sum(expenses_by_category.values())

    return render_template('report.html', expenses_by_category=expenses_by_category, total_spent=total_spent)

# Route to show history of reports
@app.route('/history')
def history():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT date_trunc('month', date::date) AS month, SUM(amount)
        FROM expenses
        GROUP BY date_trunc('month', date::date)
        ORDER BY month DESC
    ''')
    reports = cursor.fetchall()
    cursor.close()
    conn.close()

    # Process the reports into a dictionary format for display
    historical_reports = {row[0].strftime('%B %Y'): row[1] for row in reports}
    return render_template('history.html', historical_reports=historical_reports)

@app.route('/report/<month>')
def report_by_month(month):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Parse the month string back into a date
    month_start = datetime.strptime(month, '%B %Y')

    # Fetch the breakdown for the given month
    cursor.execute('''
        SELECT category, SUM(amount) 
        FROM expenses 
        WHERE date_trunc('month', date::date) = %s
        GROUP BY category
    ''', (month_start,))
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()

    # Format the data for rendering
    expenses_by_category = {category: amount for category, amount in expenses}
    total_spent = sum(expenses_by_category.values())

    return render_template(
        'report.html', 
        expenses_by_category=expenses_by_category, 
        total_spent=total_spent, 
        month=month
    )

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
