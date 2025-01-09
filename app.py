from flask import Flask, request, jsonify
from datetime import datetime
from dateutil.relativedelta import relativedelta
import mysql.connector
import decimal

app = Flask(__name__)

# Database connection configuration
db_config = {
    "user": "manudev",        # Usuario de la base de datos
    "password": "46&#52^Be^y*2t!", # Contraseña de la base de datos
    "host": "devenergybilling.mysql.database.azure.com",       # Dirección del servidor (IP o dominio)
    "database": "energybilling",     # Nombre de la base de datos
    "port": 3306                 # Puerto del servidor (default: 3306)
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/reading', methods=['POST'])
def add_reading():
    try:
        data = request.json
        contract_number = data['contract_number']
        kw_consumed = data['kw_consumed']
        date = datetime.now()
        reading = [contract_number, date, kw_consumed]

        con = get_db_connection()
        cursor = con.cursor()
        query = "INSERT INTO reading (contract_id, date, kw_consumed) VALUES(%s, %s, %s)"
        cursor.execute(query, reading)
        con.commit()

        return jsonify({"message": "Reading added successfully"}), 201
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
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

        cursor.execute("SELECT * FROM reading WHERE contract_id = %s ORDER BY date DESC LIMIT 1;", (id_contract,))
        previous_record = cursor.fetchone()

        cost_energy = previous_record[3] * general_values[contract_data[6] - 1][1]
        financing = previous_record[3] * general_values[contract_data[6] - 1][2]
        subtotal = cost_energy + financing
        rounding = subtotal - int(subtotal)
        total = subtotal - rounding + general_values[contract_data[6] - 1][3]

        if previous_record:
            invoiced_period = f"{previous_record[2].strftime('%Y-%m-%d')} - {datetime.now().strftime('%Y-%m-%d')}"
        else:
            invoiced_period = "First invoice"
        expedition_date = datetime.now()
        suspension_date = expedition_date + relativedelta(days=7)
        next_reading = datetime.now() + relativedelta(days=28)

        cursor.execute("INSERT INTO invoice (id_contract, value, invoiced_period, issue_date, id_reading, kw_cost, financing) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                       (contract_data[0], total, invoiced_period, expedition_date, previous_record[0], general_values[contract_data[6] - 1][1], financing))
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
        con = get_db_connection()
        cursor = con.cursor()

        query = """
                WITH latest_invoice AS (
                    SELECT *
                    FROM invoice
                    WHERE id_contract = %s
                    ORDER BY issue_date DESC
                    LIMIT 1
                )
                -- Step 2: Get the reading and contract details based on the invoice
                SELECT 
                    li.invoice_id,
                    c.name AS contract_name,
                    c.id,
                    c.commune,
                    c.address,
                    li.value AS invoice_value,
                    li.invoiced_period,
                    li.issue_date,
                    r.date AS reading_date,
                    li.kw_cost,
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

        cost_energy = invoice_data[9] * invoice_data[10]
        subtotal = cost_energy + invoice_data[11]
        rounding = subtotal - int(subtotal)
        suspension_date = invoice_data[7] + relativedelta(days=7)
        next_reading = invoice_data[7] + relativedelta(days=28)

        if invoice_data:
            invoice_dict = {
                "invoice_id": invoice_data[0],
                "contract_name": invoice_data[1],
                "id": invoice_data[2],
                "commune": invoice_data[3],
                "address": invoice_data[4],
                "invoice_value": invoice_data[5],
                "invoiced_period": invoice_data[6],
                "issue_date": invoice_data[7].strftime('%Y-%m-%d'),
                "reading_date": invoice_data[8].strftime('%Y-%m-%d'),
                "kw_cost": invoice_data[9],
                "kw_consumed": invoice_data[10],
                "financing": invoice_data[11],
                "telephone": invoice_data[12],
                "stratum": invoice_data[13],
                "counter": invoice_data[14],
                "user_points": invoice_data[15],
                "cost_emergy": cost_energy,
                "subtotal": subtotal,
                "rounding": rounding,
                "suspension_date": suspension_date.strftime('%Y-%m-%d'),
                "next_reading": next_reading.strftime('%Y-%m-%d')
            }
            return jsonify(invoice_dict), 200
        else:
            return jsonify({"message": "Invoice not found"}), 404
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        if 'con' in locals() and con.is_connected():
            con.close()

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=5000)
