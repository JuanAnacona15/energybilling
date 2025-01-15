from flask import Flask, request, jsonify, make_response, send_from_directory
from datetime import datetime
from dateutil.relativedelta import relativedelta
import mysql.connector
from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader
import decimal
import os

app = Flask(__name__)

# Database connection configuration
db_config = {
    "user": os.getenv("DB_USER", "user"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "host": os.getenv("DB_HOST", "urldatabase"),
    "database": os.getenv("DB_NAME", "db_name"),
    "port": int(os.getenv("DB_PORT", 3306))
}

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory('images', filename)

def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/reading', methods=['POST'])
def add_reading():
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
        
        data = request.json

        required_fields = ['kw_consumed', 'counter']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        if not isinstance(data['kw_consumed'], (int, float)):
            return jsonify({"error": "kw_consumed must be a number"}), 400
        if not isinstance(data['counter'], str):
            return jsonify({"error": "counter must be an integer"}), 400
            
        date = datetime.now()
        
        con = get_db_connection()
        cursor = con.cursor()

        cursor.execute("SELECT id_contract FROM contracts WHERE counter = %s LIMIT 1;", (str(data['counter']),))
        id_contract = cursor.fetchone()[0]
        query = "INSERT INTO reading (contract_id, date, kw_consumed, counter) VALUES (%s, %s, %s, %s)"
        
        cursor.execute(query, (
            id_contract, 
            date, 
            data['kw_consumed'], 
            data['counter']
        ))
        
        con.commit()

        return jsonify({
            "message": "Reading added successfully",
            "data": {
                "contract_id": id_contract,
                "date": date.isoformat(),
                "kw_consumed": data['kw_consumed'],
                "counter": data['counter']
            }
        }), 201
        
    except mysql.connector.Error as err:
        error_message = str(err)
        if err.errno == 1062: 
            return jsonify({"error": "Duplicate reading entry"}), 409
        elif err.errno == 1452:
            return jsonify({"error": "Invalid contract_id"}), 400
        else:
            return jsonify({"error": error_message}), 500
            
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500
        
    finally:
        if 'cursor' in locals() and cursor is not None:
            cursor.close()
        if 'con' in locals() and con is not None and con.is_connected():
            con.close()

def fetch_invoice_data(id_contract):
    try:
        con = get_db_connection()
        cursor = con.cursor()

        query = """
                WITH latest_invoice AS (
                    SELECT *
                    FROM invoice
                    WHERE id_contract = %s
                    ORDER BY invoice_id DESC
                    LIMIT 1
                )
                SELECT 
                    li.invoice_id,
                    c.name AS contract_name,
                    c.id,
                    c.commune,
                    c.address,
                    li.value AS invoice_value,
                    li.invoiced_period,
                    li.issue_date,
                    r.id_reading,
                    r.date AS reading_date,
                    li.kw_cost,
                    li.public_lighting,
                    r.kw_consumed,
                    li.financing,
                    c.telephone,
                    c.stratum,
                    c.counter,
                    c.user_points
                    
                FROM latest_invoice li
                JOIN reading r ON li.id_reading = r.id_reading
                JOIN contracts c ON li.id_contract = c.id_contract;
        """
        cursor.execute(query, (id_contract,))
        invoice_data = cursor.fetchone()

        cost_energy = invoice_data[10] * invoice_data[12]
        subtotal = cost_energy - invoice_data[13]
        rounding = subtotal - int(subtotal)
        suspension_date = invoice_data[7] + relativedelta(days=7)
        next_reading = invoice_data[7] + relativedelta(days=28)

        if invoice_data:
            invoice_dict = {
                "invoice_id": invoice_data[0],
                "id_contract" : id_contract,
                "contract_name": invoice_data[1],
                "id": invoice_data[2],
                "commune": invoice_data[3],
                "address": invoice_data[4],
                "invoice_value": invoice_data[5],
                "invoiced_period": invoice_data[6],
                "issue_date": invoice_data[7].strftime('%Y-%m-%d'),
                "id_reading": invoice_data[8],
                "reading_date": invoice_data[9].strftime('%Y-%m-%d'),
                "kw_cost": invoice_data[10],
                "public_lighting": invoice_data[11],
                "kw_consumed": invoice_data[12],
                "financing": invoice_data[13],
                "telephone": invoice_data[14],
                "stratum": invoice_data[15],
                "counter": invoice_data[16],
                "user_points": invoice_data[17],
                "cost_energy": cost_energy,
                "subtotal": subtotal,
                "rounding": rounding,
                "suspension_date": suspension_date.strftime('%Y-%m-%d'),
                "next_reading": next_reading.strftime('%Y-%m-%d')
            }
            return invoice_dict
        else:
            return None
    except mysql.connector.Error as err:
        return None
    finally:
        if 'con' in locals() and con.is_connected():
            con.close()

def is_contract_registered(id_contract):
    try:
        con = get_db_connection()
        cursor = con.cursor()
        cursor.execute("SELECT COUNT(*) FROM contracts WHERE id_contract = %s", (id_contract,))
        result = cursor.fetchone()
        return result[0] > 0
    except mysql.connector.Error as err:
        return False
    finally:
        if 'cursor' in locals() and cursor is not None:
            cursor.close()
        if 'con' in locals() and con.is_connected():
            con.close()

@app.route('/generateinvoice/<int:id_contract>')
def generate_invoice(id_contract):
    try:
        con = get_db_connection()
        cursor = con.cursor()

        cursor.execute("SELECT * FROM contracts WHERE id_contract = %s LIMIT 1", (id_contract,))
        contract_data = cursor.fetchone()

        cursor.execute("SELECT * FROM general_values")
        general_values = cursor.fetchall()

        cursor.execute("SELECT * FROM reading WHERE contract_id = %s ORDER BY id_reading DESC LIMIT 2;", (id_contract,))
        previous_record = cursor.fetchall()

        cost_energy = previous_record[0][3] * general_values[contract_data[6] - 1][1]
        financing = previous_record[0][3] * general_values[contract_data[6] - 1][2]
        subtotal = cost_energy - financing
        rounding = subtotal - int(subtotal)
        total = subtotal - rounding + general_values[contract_data[6] - 1][3]

        if len(previous_record) == 1:
            return jsonify({"message": "Cannot generate invoice"}), 400

        if previous_record[1]:
            invoiced_period = f"{previous_record[0][2].strftime('%Y-%m-%d')} - {previous_record[1][2].strftime('%Y-%m-%d')}"
        else:
            invoiced_period = "First invoice"
        expedition_date = datetime.now()

        cursor.execute("INSERT INTO invoice (id_contract, value, invoiced_period, issue_date, id_reading, kw_cost, financing, public_lighting) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
                       (contract_data[0], total, invoiced_period, expedition_date, previous_record[0][0], general_values[contract_data[6] - 1][1], financing, general_values[contract_data[6] - 1][3]))
        con.commit()

        return jsonify({"message": "Invoice generated successfully"}), 201
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        if 'con' in locals() and con.is_connected():
            con.close()

@app.route('/getinvoice/<int:id_contract>')
def get_invoice(id_contract):
    try:
        invoice_data = fetch_invoice_data(id_contract)

        if invoice_data:
            return jsonify(invoice_data), 200
        else:
            return jsonify({"message": "Invoice not found"}), 404
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500

@app.route('/getinvoicepdf/<int:id_contract>')
def get_invoice_pdf(id_contract):
    try:
        if not is_contract_registered(id_contract):
            return jsonify({"message": "Contract not found"}), 404
        
        invoice_data = fetch_invoice_data(id_contract)
        if not invoice_data:
            return jsonify({"message": "Invoice not found"}), 404

        invoice_data["kw_cost"] = round(invoice_data["kw_cost"], 2)
        invoice_data["financing"] = round(invoice_data["financing"], 2)
        invoice_data["public_lighting"] = round(invoice_data["public_lighting"], 2)
        invoice_data["cost_energy"] = round(invoice_data["cost_energy"], 2)
        invoice_data["subtotal"] = round(invoice_data["subtotal"], 2)

        env = Environment(loader=FileSystemLoader('.'))
        template = env.get_template("invoice_template.html")
        html_content = template.render(invoice_data)

        pdf = pisa.CreatePDF(html_content)
        if not pdf.err:
            pdf = pdf.dest.getvalue()
            response = make_response(pdf)
            response.headers['Content-Type'] = 'application/pdf'
            return response
        else:
            return jsonify({"message": "Error generating PDF"}), 500
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500

@app.route('/senddatacontract', methods=['POST'])
def contract_data():
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
        data = request.json

        required_fields = ['commune', 'name', 'id', 'telephone', 'address', 'stratum', 'user_points', 'counter']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        if not isinstance(data['commune'], str):
            return jsonify({"error": "commune must be a text"}), 400
        if not isinstance(data['name'], str):
            return jsonify({"error": "name must be a text"}), 400
        if not isinstance(data['id'], int):
            return jsonify({"error": "id must be an integer"}), 400
        if not isinstance(data['telephone'], int) or len(str(data['telephone'])) != 10:
            return jsonify({"error": "telephone must be an integer with 10 digits"}), 400
        if not isinstance(data['address'], str):
            return jsonify({"error": "address must be a text"}), 400
        if not isinstance(data['stratum'], int) or not (0 <= data['stratum'] <= 5):
            return jsonify({"error": "stratum must be an integer in range 0-5"}), 400
        if not isinstance(data['user_points'], int):
            return jsonify({"error": "user_points must be an integer"}), 400
        if not isinstance(data['counter'], str):
            return jsonify({"error": "counter must be a text"}), 400


        con = get_db_connection()
        cursor = con.cursor()

        cursor.execute("SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END AS r FROM contracts WHERE counter = %s;", (data['counter'],))
        resp = cursor.fetchone()
    
        if resp[0] == 1:
            return jsonify({"error": "Counter already exists"}), 401
        
        query = """
            INSERT INTO contracts (commune, name, id, telephone, address, stratum, user_points, counter) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['commune'], 
            data['name'], 
            data['id'], 
            data['telephone'], 
            data['address'], 
            data['stratum'], 
            data['user_points'], 
            data['counter']
        ))
        
        query = "INSERT INTO reading (contract_id, date, kw_consumed, counter) VALUES (%s, %s, %s, %s)"

        cursor.execute("SELECT id_contract FROM contracts WHERE id = %s LIMIT 1;", (data['id'],))
        id_contract = cursor.fetchone()[0]
        
        cursor.execute(query, (
            id_contract, 
            datetime.now(), 
            0, 
            data['counter']
        ))
        con.commit()

        return jsonify({"ok": True}), 201
        
    except mysql.connector.Error as err:
        print(err)
        return jsonify({"error": str(err)}), 500
        
    finally:
        if 'cursor' in locals() and cursor is not None:
            cursor.close()
        if 'con' in locals() and con is not None and con.is_connected():
            con.close()

@app.route('/validatecontract/<int:id_contract>')
def validate_contract(id_contract):
    try:
        if not is_contract_registered(id_contract):
            return jsonify({"message": "Contract found"}), 404
        return jsonify({"message": "Contract registered"}), 200
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500

@app.route('/createcontract')
def contract():
    return send_from_directory('.', 'create_contract.html')

@app.route('/addreading')
def addreading():
    return send_from_directory('.', 'reading.html')

@app.route('/consultinvoice')
def consultinvoice():
    return send_from_directory('.', 'consult_invoice.html')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=5000)
