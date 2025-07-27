from flask import Flask, request, jsonify
from flask_cors import CORS
import interactive

app = Flask(__name__)
CORS(app)

@app.route('/start', methods=['POST'])
def start_bot():
    try:
        n = int(request.json.get('n', 1))
        dryrun = bool(request.json.get('dryrun', True))
        user_id = request.json.get('user_id', 'U001')
        result = interactive.start_trading_bot(dryrun, user_id)
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/stop', methods=['POST'])
def stop_bot():
    try:
        n = int(request.json.get('n', 1))
        result = interactive.stop_trading_bot(n)
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    try:
        n = int(request.args.get('n', 1))
        result = interactive.currently_trading(n)
        return jsonify({'status': 'success', 'currently_trading': result})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/logs', methods=['GET'])
def logs():
    try:
        day = request.args.get('day', 'today')
        logs = interactive.load_logs_for_analysis(day)
        return jsonify({'status': 'success', 'logs': logs})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/reports', methods=['GET'])
def reports():
    try:
        n = int(request.args.get('n', 1))
        reports = interactive.get_today_reports(n)
        return jsonify({'status': 'success', 'reports': reports})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 