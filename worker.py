import socket
import json
import numpy as np
import threading
import logging
import argparse

from typing import List, Tuple, Dict
from sentence_transformers import SentenceTransformer

# --- Constants ---
BUFFER_SIZE = 4096
END_MARKER = "<END>"

# --- Utility functions ---
def receive_data(sock: socket.socket) -> str:
    """Receive data in chunks until the end marker is found."""
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

def send_data(sock: socket.socket, payload: Dict) -> None:
    """Send JSON-serializable payload with end marker, in chunks."""
    data_str = json.dumps(payload) + END_MARKER
    for i in range(0, len(data_str), BUFFER_SIZE):
        chunk = data_str[i:i + BUFFER_SIZE]
        sock.sendall(chunk.encode('utf-8'))

# --- Worker class ---
class Worker:
    def __init__(self, port: int, documents: List[str]):
        # Networking
        self.port = port
        self.admin_port = port + 1000

        # Documents & model
        self.documents = documents
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.doc_lock = threading.RLock()  # ← allow re-entrant locking

        # Logging
        logging.info(f"Worker initialized on port {self.port} (admin {self.admin_port})")
        logging.info(f"Initial document count: {len(self.documents)}")

        # Build initial embeddings
        self.update_embeddings()
        # Start admin server thread
        self.start_admin_server()

    def update_embeddings(self):
        """(Re)compute embeddings for all documents."""
        with self.doc_lock:
            logging.info(f"Recomputing embeddings for {len(self.documents)} documents")
            self.doc_embeddings = self.model.encode(
                self.documents, convert_to_tensor=True
            )
            logging.info("Embeddings rebuilt successfully")

    def add_documents(self, new_docs: List[str]) -> Dict:
        """Add new documents, rebuild embeddings, and return their IDs."""
        try:
            # 1) Extend the document list under lock
            with self.doc_lock:
                start_idx = len(self.documents)
                self.documents.extend(new_docs)

            # 2) Rebuild embeddings (RLock lets us re-enter safely)
            self.update_embeddings()

            return {
                'status': 'success',
                'message': f'Added {len(new_docs)} documents',
                'doc_ids': list(range(start_idx, len(self.documents)))
            }
        except Exception as e:
            logging.error(f"Error in add_documents: {e}")
            return {'status': 'error', 'message': str(e)}

    def remove_documents(self, doc_ids: List[int]) -> Dict:
        """Remove documents by ID, rebuild embeddings, and report."""
        try:
            with self.doc_lock:
                logging.info(f"Removing documents: {doc_ids}")
                self.documents = [
                    doc for idx, doc in enumerate(self.documents)
                    if idx not in doc_ids
                ]

            self.update_embeddings()
            return {
                'status': 'success',
                'message': f'Removed {len(doc_ids)} documents',
                'remaining_docs': len(self.documents)
            }
        except Exception as e:
            logging.error(f"Error in remove_documents: {e}")
            return {'status': 'error', 'message': str(e)}

    def list_documents(self) -> Dict:
        """Return all documents (id + text)."""
        with self.doc_lock:
            docs = [
                {'id': idx, 'text': doc}
                for idx, doc in enumerate(self.documents)
            ]
        return {'status': 'success', 'documents': docs}

    def handle_admin_request(self, client_socket: socket.socket):
        """Receive an admin command (add/remove/list) and reply."""
        try:
            raw = receive_data(client_socket)
            req = json.loads(raw)
            cmd = req.get('command', '').lower()

            if cmd == 'add':
                resp = self.add_documents(req.get('documents', []))
            elif cmd == 'remove':
                resp = self.remove_documents(req.get('doc_ids', []))
            elif cmd == 'list':
                resp = self.list_documents()
            else:
                resp = {'status': 'error', 'message': f'Unknown command: {cmd}'}

            send_data(client_socket, resp)

        except Exception as e:
            logging.error(f"Admin handler error: {e}")
            try:
                send_data(client_socket, {'status': 'error', 'message': str(e)})
            except:
                pass
        finally:
            client_socket.close()

    def start_admin_server(self):
        """Spawn a thread to listen for admin (add/remove/list) connections."""
        def admin_loop():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('localhost', self.admin_port))
            sock.listen(5)
            logging.info(f"Admin server listening on port {self.admin_port}")

            while True:
                client, addr = sock.accept()
                logging.info(f"Admin connection from {addr}")
                threading.Thread(
                    target=self.handle_admin_request,
                    args=(client,),
                    daemon=True
                ).start()

        threading.Thread(target=admin_loop, daemon=True).start()

    def compute_similarities(self, query_embedding: np.ndarray, top_k: int = 3
                            ) -> List[Tuple[int, float]]:
        """Return top_k (doc_id, score) pairs by cosine similarity."""
        try:
            with self.doc_lock:
                sims = np.dot(self.doc_embeddings, query_embedding.T).squeeze()
            top_idxs = np.argsort(sims)[-top_k:][::-1]
            return [(int(i), float(sims[i])) for i in top_idxs]
        except Exception as e:
            logging.error(f"Error computing similarities: {e}")
            return []

    def start(self):
        """Main loop: accept query connections and return nearest docs."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('localhost', self.port))
        sock.listen(5)
        logging.info(f"Worker server listening on port {self.port}")

        while True:
            client, addr = sock.accept()
            logging.info(f"Query connection from {addr}")
            try:
                raw = receive_data(client)
                q = json.loads(raw)
                query_emb = np.array(q['embedding'])
                results = self.compute_similarities(query_emb)

                resp = {
                    'results': [
                        {
                            'doc_id': doc_id,
                            'document': self.documents[doc_id],
                            'score': score
                        }
                        for doc_id, score in results
                    ]
                }
                send_data(client, resp)
            except Exception as e:
                logging.error(f"Error handling query: {e}")
            finally:
                client.close()

# --- Sample document loader ---
def load_sample_documents(worker_id: int) -> List[str]:
    """For demo: split 10 base docs into two workers of 5 each."""
    base_docs = [
        "Machine learning is revolutionizing technology and business.",
        "Deep learning models have achieved remarkable results in computer vision.",
        "Natural language processing enables human-computer interaction.",
        "Artificial intelligence is transforming healthcare and medicine.",
        "Data science combines statistics, programming, and domain expertise.",
        "Neural networks are inspired by biological brain structures.",
        "Reinforcement learning is key to autonomous systems.",
        "Computer vision systems can detect objects and recognize faces.",
        "Big data analytics helps companies make better decisions.",
        "AI ethics is crucial for responsible technology development."
    ]
    start = (worker_id - 1) * 5
    return base_docs[start:start + 5]

# --- Entry point ---
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True,
                        help="Port for the worker server")
    parser.add_argument("--worker_id", type=int, choices=[1,2], required=True,
                        help="Worker ID (1 or 2)")
    args = parser.parse_args()

    docs = load_sample_documents(args.worker_id)
    worker = Worker(args.port, docs)
    worker.start()
