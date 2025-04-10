from flask import Flask, render_template, request, jsonify, send_from_directory
import csv
import os
import datetime
from werkzeug.utils import secure_filename



import logging
from logging.handlers import RotatingFileHandler

# Configuration du logging
log_handler = RotatingFileHandler('app.log', maxBytes=100000, backupCount=3)
log_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))




app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'data'
app.config['ALLOWED_EXTENSIONS'] = {'csv'}
app.config['VISITOR_LOG'] = 'data/visiteurs.txt'

# Variables globales pour le compteur
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

@app.route('/search', methods=['POST'])
def search():
    try:
        cin = request.form.get('cin', '').strip()
        telephone = request.form.get('telephone', '').strip()
        
        # Validation des entrées
        if not cin and not telephone:
            app.logger.warning("Aucun identifiant fourni")
            return jsonify({'error': 'Veuillez fournir un CNI ou un téléphone'}), 400
            
        if cin and telephone:
            app.logger.warning("Double identifiant fourni")
            return jsonify({'error': 'Veuillez fournir soit le CNI soit le téléphone, pas les deux'}), 400

        # Vérification des fichiers avant traitement
        required_files = ['bourses.csv', 'responsabilites.csv', 'subventions.csv', 'aides.csv', 'rurals.csv']
        missing_files = [f for f in required_files if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], f))]
        
        if missing_files:
            app.logger.error(f"Fichiers manquants: {', '.join(missing_files)}")
            return jsonify({'error': 'Fichiers de données manquants', 'missing': missing_files}), 500

        # Recherche
        results = {
            'bourse': search_csv('bourses.csv', cin, telephone),
            'responsabilite': search_csv('responsabilites.csv', cin, telephone),
            'subvention': search_csv('subventions.csv', cin, telephone),
            'aides': search_csv('aides.csv', cin, telephone),
            'rurals': search_csv('rurals.csv', cin, telephone)
        }

        return jsonify(results)

    except Exception as e:
        app.logger.error(f"Erreur dans la recherche: {str(e)}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500


def search_csv(filename, cin, telephone):
    """Fonction générique de recherche dans les fichiers CSV"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    result = {'found': False, 'nom': '', 'prenom': '', 'data': {}}
    
    try:
        # Vérification initiale du fichier
        if not os.path.exists(filepath):
            app.logger.error(f"Fichier {filename} introuvable dans {app.config['UPLOAD_FOLDER']}")
            return result

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            # Lire le fichier ligne par ligne en gérant les erreurs
            try:
                reader = csv.DictReader((line.replace('\0', '') for line in f), delimiter=';')
            except csv.Error as e:
                app.logger.error(f"Erreur de lecture CSV {filename}: {str(e)}")
                return result

            for row in reader:
                try:
                    # Nettoyage robuste des données
                    cleaned_row = {}
                    for k, v in row.items():
                        if v is None:
                            cleaned_row[k.strip()] = ''
                        else:
                            cleaned_row[k.strip()] = v.strip() if isinstance(v, str) else str(v)

                    # Recherche par CNI ou téléphone
                    current_cni = cleaned_row.get('CNI', '')
                    current_phone = cleaned_row.get('TELEPHONES', '')

                    if (cin and current_cni == cin) or (telephone and current_phone == telephone):
                        return {
                            'found': True,
                            'nom': cleaned_row.get('NOM', ''),
                            'prenom': cleaned_row.get('PRENOM', ''),
                            'data': cleaned_row
                        }
                except Exception as row_error:
                    app.logger.warning(f"Erreur traitement ligne {row}: {str(row_error)}")
                    continue

    except Exception as e:
        app.logger.error(f"Erreur critique avec {filename}: {str(e)}")
        if app.debug:
            import traceback
            traceback.print_exc()

    return result



def search_subvention(cin, telephone):
    result = search_csv('subventions.csv', cin, telephone)
    
    if result['found']:
        # Validation des champs obligatoires
        if not all(k in result['data'] for k in ['MONTANT', 'TYPE']):
            app.logger.warning(f"Subvention incomplète pour {cin or telephone}")
            result['found'] = False
            return result
            
        # Formatage sécurisé
        try:
            montant = int(result['data']['MONTANT'])
            result['data']['MONTANT'] = f"{montant} FCFA"
        except (ValueError, TypeError):
            result['data']['MONTANT'] = "Montant invalide"
    
    return result


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



@app.route('/')
def home():
    return "Hello World"



if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


# if __name__ == '__main__':
#     os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
#     if not os.path.exists(app.config['VISITOR_LOG']):
#         with open(app.config['VISITOR_LOG'], 'w', encoding='utf-8') as f:
#             f.write(f"=== Log des visiteurs - {datetime.date.today()} ===\n")
    
#     app.run(host='0.0.0.0', port=5000, debug=True)