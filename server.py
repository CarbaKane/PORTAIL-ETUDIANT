from flask import Flask, render_template, request, jsonify, send_from_directory, session
import csv
import os
import datetime
from werkzeug.utils import secure_filename
import logging
from logging.handlers import RotatingFileHandler
import codecs
import secrets  # NEW: Pour la gestion sécurisée des sessions

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # NEW: Clé secrète robuste
app.config['UPLOAD_FOLDER'] = 'data'
app.config['ALLOWED_EXTENSIONS'] = {'csv'}
app.config['VISITOR_LOG'] = 'data/visiteurs.txt'
app.config['ADMIN_CREDENTIALS'] = {  # NEW: Externalisation des identifiants
    'username': os.getenv('ADMIN_USER', 'DB'),
    'password': os.getenv('ADMIN_PASS', 'CarbaDB')
}

# NEW: Configuration sécurité supplémentaire
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Variables globales
visitor_count = 0
last_reset_date = datetime.date.today()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def reset_counter_if_new_day():
    global visitor_count, last_reset_date
    if datetime.date.today() > last_reset_date:
        visitor_count = 0
        last_reset_date = datetime.date.today()
        with open(app.config['VISITOR_LOG'], 'a') as f:
            f.write(f"\n\n==== Nouveau jour: {last_reset_date} ====\n\n")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/update-visitor-count', methods=['POST'])
def update_visitor_count():
    global visitor_count
    reset_counter_if_new_day()
    
    visitor_count += 1
    identifier = request.json.get('identifier', '')
    action = request.json.get('action', 'search')
    
    with open(app.config['VISITOR_LOG'], 'a', encoding='utf-8') as f:
        log_message = f"[{datetime.datetime.now()}] Visiteur #{visitor_count} - Action: {action}"
        if identifier:
            log_message += f" - ID: {identifier}"
        f.write(log_message + "\n")
    
    return jsonify({'count': visitor_count})

@app.route('/get-visitor-count')
def get_visitor_count():
    reset_counter_if_new_day()
    return jsonify({'count': visitor_count})

def search_csv(filename, cin):
    """Fonction de recherche dans les fichiers CSV par CNI"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    results = []  # NEW: Retourne une liste de tous les résultats
    
    try:
        if not os.path.exists(filepath):
            app.logger.error(f"Fichier {filename} introuvable")
            return results

        with codecs.open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader((line.replace('\0', '') for line in f), delimiter=';')
            for row in reader:
                try:
                    cleaned_row = {k.strip(): v.strip() if isinstance(v, str) else str(v) 
                                for k, v in row.items()}
                    if cin and cleaned_row.get('CNI', '') == cin:
                        results.append({
                            'nom': cleaned_row.get('NOM', ''),
                            'prenom': cleaned_row.get('PRENOM', ''),
                            'data': cleaned_row
                        })
                except Exception as row_error:
                    app.logger.warning(f"Erreur traitement ligne {row}: {str(row_error)}")
                    continue

    except Exception as e:
        app.logger.error(f"Erreur fichier {filename}: {str(e)}")
        if app.debug:
            import traceback
            traceback.print_exc()

    return results  # NEW: Retourne tous les résultats trouvés

@app.route('/search', methods=['POST'])
def search():
    try:
        cin = request.form.get('cin', '').strip()
        
        if not cin:
            app.logger.warning("Aucun CNI fourni")
            return jsonify({'error': 'Veuillez fournir un numéro CNI'}), 400
            
        required_files = ['bourses.csv', 'responsabilites.csv', 'subventions.csv', 'aides.csv', 'rurals.csv']
        missing_files = [f for f in required_files if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], f))]
        
        if missing_files:
            app.logger.error(f"Fichiers manquants: {missing_files}")
            return jsonify({'error': 'Fichiers de données manquants', 'missing': missing_files}), 500

        results = {
            'bourse': search_csv('bourses.csv', cin),
            'responsabilite': search_csv('responsabilites.csv', cin),
            'subvention': search_csv('subventions.csv', cin),
            'aides': search_csv('aides.csv', cin),
            'rurals': search_csv('rurals.csv', cin)
        }

        return jsonify(results)

    except Exception as e:
        app.logger.error(f"Erreur recherche: {str(e)}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.route('/check-files')
def check_files():
    files = {
        'subventions.csv': os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'subventions.csv')),
        'responsabilites.csv': os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'responsabilites.csv')),
        'bourses.csv': os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'bourses.csv')),
        'rurals.csv': os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'rurals.csv')),
        'aides.csv': os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'aides.csv'))
    }
    return jsonify(files)

@app.route('/admin-login', methods=['POST'])  # NEW: Endpoint séparé pour le login
def admin_login():
    data = request.get_json()
    if (data.get('username') == app.config['ADMIN_CREDENTIALS']['username'] and 
        data.get('password') == app.config['ADMIN_CREDENTIALS']['password']):
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Identifiants incorrects'}), 401

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'csvFile' not in request.files:
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    file = request.files['csvFile']
    file_type = request.form.get('fileType')
    
    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Seuls les fichiers CSV sont autorisés'}), 400
    
    expected_names = {
        'bourses': 'bourses.csv',
        'subventions': 'subventions.csv',
        'responsabilites': 'responsabilites.csv',
        'rurals': 'rurals.csv',
        'aides': 'aides.csv'
    }
    
    if file.filename != expected_names[file_type]:
        return jsonify({'error': f"Le fichier doit s'appeler '{expected_names[file_type]}'"}), 400
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], expected_names[file_type]))
    
    return jsonify({'success': True, 'message': f'Fichier {expected_names[file_type]} téléchargé avec succès'})

@app.route('/data/<path:filename>')
def serve_data(filename):
    return send_from_directory('data', filename)

@app.route('/images/<path:filename>')
def serve_images(filename):
    return send_from_directory('images', filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('images', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    if not os.path.exists(app.config['VISITOR_LOG']):
        with open(app.config['VISITOR_LOG'], 'w', encoding='utf-8') as f:
            f.write(f"=== Log des visiteurs - {datetime.date.today()} ===\n")
    
    # Modification importante ici pour utiliser le port de Railway
    port = int(os.environ.get("PORT", 5002))
    app.run(host='0.0.0.0', port=port, debug=False)  # debug=False en production