from flask import Flask, jsonify, request, render_template
from flask_httpauth import HTTPBasicAuth
from twilio.twiml.messaging_response import MessagingResponse
import json
import csv
import os
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)
auth = HTTPBasicAuth()

users = {"admin": "myapp2025"}  # Change to a secure password

@auth.verify_password
def verify_password(username, password):
    return users.get(username) == password

ORDER_FILE = "whatsapp_orders.json"
BILLING_FILE = "billing.csv"

def get_current_session():
    hour = datetime.now().hour
    if 6 <= hour < 10:
        return "Breakfast"
    elif 11 <= hour < 15:
        return "Lunch"
    elif 17 <= hour < 22:
        return "Dinner"
    return "None"

def get_session_files(session):
    if session == "None":
        return "kitchen.csv", "packing.csv"
    return f"kitchen_{session.lower()}.csv", f"packing_{session.lower()}.csv"

def save_order(phone, name, location, items, quantities, prices):
    session = get_current_session()
    if session == "None":
        return False, "Order received outside of valid session hours."
    
    order = {
        "customer_id": phone,
        "name": name,
        "phone": phone,
        "location": location,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "quantities": quantities,
        "prices": prices,
        "session": session
    }
    
    orders = []
    if os.path.exists(ORDER_FILE):
        with open(ORDER_FILE, 'r') as f:
            try:
                orders = json.load(f)
            except json.JSONDecodeError:
                orders = []
    
    orders.append(order)
    with open(ORDER_FILE, 'w') as f:
        json.dump(orders, f, indent=2)
    
    process_orders(session)
    return True, "Order processed successfully."

def process_orders(session):
    if not os.path.exists(ORDER_FILE):
        return
    
    with open(ORDER_FILE, 'r') as f:
        all_orders = json.load(f)
    
    orders = [order for order in all_orders if order["session"] == session]
    kitchen_file, packing_file = get_session_files(session)
    
    kitchen_data = defaultdict(int)
    for order in orders:
        for item, quantity in zip(order["items"], order["quantities"]):
            kitchen_data[item] += quantity
    
    with open(kitchen_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Item", "Quantity"])
        for item, quantity in kitchen_data.items():
            writer.writerow([item, quantity])
    
    packing_data = defaultdict(list)
    for order in orders:
        location = order["location"]
        packing_data[location].append({
            "name": order["name"],
            "customer_id": order["customer_id"],
            "items": ", ".join(f"{item} x{quantity}" for item, quantity in zip(order["items"], order["quantities"]))
        })
    
    with open(packing_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Location", "Name", "Customer ID", "Order"])
        for location, orders in packing_data.items():
            for order in orders:
                writer.writerow([location, order["name"], order["customer_id"], order["items"]])
    
    billing_data = []
    monthly_totals = defaultdict(float)
    current_month = datetime.now().strftime("%Y-%m")
    
    for order in all_orders:
        order_date = order["date"][:7]
        for item, quantity, price in zip(order["items"], order["quantities"], order["prices"]):
            total = quantity * price
            billing_data.append({
                "customer_id": order["customer_id"],
                "name": order["name"],
                "date": order["date"],
                "item": item,
                "price": total
            })
            if order_date == current_month:
                monthly_totals[order["customer_id"]] += total
    
    with open(BILLING_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if os.path.getsize(BILLING_FILE) == 0 if os.path.exists(BILLING_FILE) else True:
            writer.writerow(["Customer ID", "Name", "Date", "Item", "Price", "Monthly Total"])
        for data in billing_data:
            monthly_total = monthly_totals[data["customer_id"]] if data["date"][:7] == current_month else 0
            writer.writerow([
                data["customer_id"],
                data["name"],
                data["date"],
                data["item"],
                data["price"],
                monthly_total if data["date"][:7] == current_month else ""
            ])

def start_new_session(session):
    kitchen_file, packing_file = get_session_files(session)
    if os.path.exists(kitchen_file):
        open(kitchen_file, 'w').close()
    if os.path.exists(packing_file):
        open(packing_file, 'w').close()

def simulate_whatsapp_message(message):
    try:
        parts = message.split(",")
        phone = parts[0]
        name = parts[1]
        location = parts[2]
        items = []
        quantities = []
        prices = []
        
        for item_data in parts[3:]:
            item, quantity, price = item_data.split(":")
            items.append(item)
            quantities.append(int(quantity))
            prices.append(float(price))
        
        success, msg = save_order(phone, name, location, items, quantities, prices)
        return success, msg
    except Exception as e:
        return False, f"Error processing message: {e}"

@app.route('/api/orders')
@auth.login_required
def get_orders():
    if os.path.exists(ORDER_FILE):
        with open(ORDER_FILE, 'r') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/kitchen/<session>')
@auth.login_required
def get_kitchen(session):
    file = f'kitchen_{session.lower()}.csv'
    if os.path.exists(file):
        with open(file, 'r') as f:
            reader = csv.DictReader(f)
            return jsonify([{'item': row['Item'], 'quantity': int(row['Quantity'])} for row in reader])
    return jsonify([])

@app.route('/api/packing/<session>')
@auth.login_required
def get_packing(session):
    file = f'packing_{session.lower()}.csv'
    if os.path.exists(file):
        with open(file, 'r') as f:
            reader = csv.DictReader(f)
            return jsonify([{
                'location': row['Location'],
                'name': row['Name'],
                'customer_id': row['Customer ID'],
                'order': row['Order']
            } for row in reader])
    return jsonify([])

@app.route('/api/billing')
@auth.login_required
def get_billing():
    if os.path.exists(BILLING_FILE):
        with open(BILLING_FILE, 'r') as f:
            reader = csv.DictReader(f)
            return jsonify([{
                'customer_id': row['Customer ID'],
                'name': row['Name'],
                'date': row['Date'],
                'item': row['Item'],
                'price': float(row['Price']),
                'monthly_total': float(row['Monthly Total']) if row['Monthly Total'] else 0
            } for row in reader])
    return jsonify([])

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    message = request.form.get('Body')
    success, msg = simulate_whatsapp_message(message)
    resp = MessagingResponse()
    resp.message(msg)
    return str(resp)

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    start_new_session(get_current_session())
    app.run(port=5000, debug=True)
