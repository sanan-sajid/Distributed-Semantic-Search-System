import socket
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
import heapq

BUFFER_SIZE = 4096
END_MARKER = "<END>"

def receive_data(sock):
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

def send_data(sock, data):

    data_str = json.dumps(data) + END_MARKER
    for i in range(0, len(data_str), BUFFER_SIZE):
        chunk = data_str[i:i + BUFFER_SIZE]
        sock.send(chunk.encode('utf-8'))

class MasterServer:
    def __init__(self, port: int, worker_ports: List[int]):
        """Initialize master server with worker information."""
        self.port = port
        self.worker_ports = worker_ports
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
    def query_worker(self, worker_port: int, query_embedding: np.ndarray) -> List[Dict]:
        """Send query to a worker and get results."""
        try:
            # Connect to worker
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect(('localhost', worker_port))
            
            # Send query embedding using chunked transfer
            query_data = {
                'embedding': query_embedding.tolist()
            }
            send_data(client_socket, query_data)
            
            # Receive results using chunked transfer
            response = receive_data(client_socket)
            results = json.loads(response)
            client_socket.close()
            
            return results['results']
            
        except Exception as e:
            print(f"Error querying worker on port {worker_port}: {e}")
            return []
    
    def merge_results(self, all_results: List[List[Dict]], top_k: int = 3) -> List[Dict]:
        # Flatten all results
        flat_results = []
        for worker_results in all_results:
            flat_results.extend(worker_results)
        
        # Sort by score and get top-k
        return sorted(flat_results, key=lambda x: x['score'], reverse=True)[:top_k]
    
    def start(self):
        #Start the master server.
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(('localhost', self.port))
        server_socket.listen(5)
        print(f"Master server listening on port {self.port}")
        
        with ThreadPoolExecutor(max_workers=len(self.worker_ports)) as executor:
            while True:
                try:
                    client_socket, addr = server_socket.accept()
                    print(f"Connection from {addr}")
                    
                    # Receive query using chunked transfer
                    data = receive_data(client_socket)
                    query_data = json.loads(data)
                    query_text = query_data['query']
                    
                    # Compute query embedding
                    query_embedding = self.model.encode([query_text])[0]
                    
                    # Query all workers in parallel
                    future_results = [
                        executor.submit(self.query_worker, port, query_embedding)
                        for port in self.worker_ports
                    ]
                    
                    # Collect results
                    all_results = [future.result() for future in future_results]
                    
                    # Merge and get top results
                    final_results = self.merge_results(all_results)
                    
                    # Send response using chunked transfer
                    response = {'results': final_results}
                    send_data(client_socket, response)
                    client_socket.close()
                    
                except Exception as e:
                    print(f"Error: {e}")
                    continue

if __name__ == "__main__":
    # Configure ports
    MASTER_PORT = 5000
    WORKER_PORTS = [5001, 5002]  # Two workers
    
    # Start master server
    master = MasterServer(MASTER_PORT, WORKER_PORTS)
    master.start() 