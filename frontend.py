import os
import subprocess
import time
import logging
from flask import Flask, render_template, request, redirect, url_for
from multiprocessing import Process

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')
@app.route('/start_interactive')
def start_interactive():
    p = Process(target=start_process, args=('interactive.py', '-g', 'technology'))
    p.start()
    return redirect(url_for('index'))

@app.route('/start_generatelist')
def start_generatelist():
    p = Process(target=start_process, args=('generatelist.py', '-g', 'technology'))
    p.start()
    return redirect(url_for('index'))

@app.route('/logs')
def logs():
    with open('controller-logs.log', 'r') as f:
        logs = f.read()
    return render_template('logs.html', logs=logs)

def start_process(script, *args):
    subprocess.call(['python', script] + list(args))

if __name__ == "__main__":
    app.run(debug=True)
