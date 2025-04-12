import socket
import json
import argparse

def query_master(query: str, master_port: int = 5000) -> list:
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(('localhost', master_port))

        # Send query
        query_data = {'query': query}
        client_socket.send(json.dumps(query_data).encode('utf-8'))
        
        # get results
        response = client_socket.recv(4096).decode('utf-8')
        results = json.loads(response)
        client_socket.close()
        
        return results['results']
        
    except Exception as e:
        print(f"Error querying master server: {e}")
        return []

def print_results(results: list):
    print("\nSearch Results:")
    print("-" * 80)
    
    for i, result in enumerate(results, 1):
        print(f"\n{i}. Document (Score: {result['score']:.4f}):")
        print(f"   {result['document']}")
    
    print("\n" + "-" * 80)

def main():
    parser = argparse.ArgumentParser(description="Distributed Search Client")
    parser.add_argument("--query", type=str, help="Search query")
    args = parser.parse_args()
    
    if args.query:
        query = args.query
    else:
        query = input("Enter your search query: ")
    
    results = query_master(query)
    if results:
        print_results(results)
    else:
        print("No results found or an error occurred.")

if __name__ == "__main__":
    main() 