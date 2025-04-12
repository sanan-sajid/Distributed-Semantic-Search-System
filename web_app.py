from flask import Flask, render_template, request, jsonify
import socket
import json
import logging
import time

# Configuration 
BUFFER_SIZE    = 4096
END_MARKER     = "<END>"
WORKER_PORTS   = [5001, 5002]   
MAX_RETRIES    = 10         # 10 retries for worker connection
RETRY_DELAY    = 2          # 2 sec delay between retries

#  Logging setup 
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

def receive_data(sock: socket.socket) -> str:
    #  Receive data until END_MARKER -> <END>.
    data = ""
    while True:
        chunk = sock.recv(BUFFER_SIZE).decode('utf-8')
        if not chunk:
            break
        if END_MARKER in chunk:
            data += chunk[:chunk.index(END_MARKER)]
            break
        data += chunk
    return data

def send_data(sock: socket.socket, payload: dict):

    data_str = json.dumps(payload) + END_MARKER
    for i in range(0, len(data_str), BUFFER_SIZE):
        chunk = data_str[i:i+BUFFER_SIZE]
        sock.sendall(chunk.encode('utf-8'))

def send_admin_command(command: str, data: dict, worker_port: int) -> dict:

    admin_port = worker_port + 1000
    last_err = None

    for attempt in range(1, MAX_RETRIES+1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(('localhost', admin_port))
            logging.info(f"[admin] connected to worker {worker_port} admin port {admin_port}")
            request = {'command': command, **data}
            send_data(sock, request)
            raw = receive_data(sock)
            sock.close()
            return json.loads(raw)
        except (ConnectionRefusedError, socket.timeout) as e:
            last_err = e
            logging.warning(f"[admin] attempt {attempt}/{MAX_RETRIES} failed to connect to port {admin_port}: {e}")
            time.sleep(RETRY_DELAY)
        except Exception as e:
            logging.error(f"[admin] unexpected error talking to worker {worker_port}: {e}")
            return {'status': 'error', 'message': str(e)}

    msg = f"Could not connect to worker {worker_port} admin port {admin_port} after {MAX_RETRIES} attempts: {last_err}"
    logging.error(msg)
    return {'status': 'error', 'message': msg}


def query_master(query: str, master_port: int = 5000) -> list:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('localhost', master_port))
        send_data(sock, {'query': query})
        raw = receive_data(sock)
        sock.close()
        return json.loads(raw)['results']
    except Exception as e:
        logging.error(f"[master] query error: {e}")
        return []


# Flask route
@app.route('/')
def home():
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    query = request.json.get('query', '').strip()
    if not query:
        return jsonify({'error': 'Query is required'}), 400

    results = query_master(query)
    return jsonify({'results': results})


@app.route('/documents', methods=['GET'])
def list_documents():
    all_docs = []
    errors   = []

    for port in WORKER_PORTS:
        resp = send_admin_command('list', {}, port)
        if resp.get('status') == 'success':
            all_docs.extend(resp['documents'])
        else:
            errors.append(f"Worker {port}: {resp.get('message')}")

    if errors and not all_docs:
        return jsonify({
            'status': 'error',
            'message': 'Could not list any documents',
            'errors': errors
        }), 500

    return jsonify({
        'status':    'success',
        'documents': all_docs,
        'errors':    errors or None
    })


@app.route('/documents', methods=['POST'])
def add_documents():
    docs = request.json.get('documents', [])
    docs = [d.strip() for d in docs if d.strip()]
    if not docs:
        return jsonify({'error': 'No valid documents provided'}), 400
    
    
# Even partitioning of documents across workers
    # n_workers     = len(WORKER_PORTS)
    # per_worker    = len(docs) // n_workers
    # remainder     = len(docs) % n_workers
    # responses     = []
    # errors        = []
    # idx           = 0
    # for i, port in enumerate(WORKER_PORTS):
    #     count = per_worker + (1 if i < remainder else 0)
    #     if count == 0:
    #         continue
    #     chunk = docs[idx:idx+count]
    #     idx += count
    #     resp = send_admin_command('add', {'documents': chunk}, port)
    #     responses.append(resp)
    #     if resp.get('status') != 'success':
    #         errors.append(f"Worker {port}: {resp.get('message')}")
    # status = 'success' if not errors else 'partial_success'
    # return jsonify({'status': status, 'responses': responses, 'errors': errors or None})

    # Round-robin assignment of documents across workers
    n_workers = len(WORKER_PORTS)
    worker_docs = [[] for _ in range(n_workers)]
    for i, doc in enumerate(docs):
        worker_index = i % n_workers
        worker_docs[worker_index].append(doc)
    
    responses = []
    errors = []
    for i, port in enumerate(WORKER_PORTS):
        chunk = worker_docs[i]
        if chunk:  
            resp = send_admin_command('add', {'documents': chunk}, port)
            responses.append(resp)
            if resp.get('status') != 'success':
                errors.append(f"Worker {port}: {resp.get('message')}")

    status = 'success' if not errors else 'partial_success'
    return jsonify({'status': status, 'responses': responses, 'errors': errors or None})


@app.route('/documents/<int:doc_id>', methods=['DELETE'])
def remove_document(doc_id):
    errors = []
    for port in WORKER_PORTS:
        resp = send_admin_command('remove', {'doc_ids': [doc_id]}, port)
        if resp.get('status') == 'success':
            return jsonify(resp)
        errors.append(f"Worker {port}: {resp.get('message')}")

    return jsonify({
        'status':  'error',
        'message': f"Could not remove doc {doc_id}",
        'errors':  errors
    }), 404


if __name__ == '__main__':
    app.run(host='localhost', port=8000, debug=True)
