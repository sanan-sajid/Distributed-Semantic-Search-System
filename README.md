# Distributed Semantic Search System

A high‑performance, scalable search engine that uses modern NLP to deliver fast, context‑aware results across large document collections.

---

## 🚀 What This Project Does

- **Semantic Search**  
  Transforms documents and queries into 384‑dimensional embeddings with a BERT‑based model (all‑MiniLM‑L6‑v2), enabling meaning‑driven retrieval.

- **Distributed Processing**  
  Master‑worker design shards data and workloads across nodes for parallel indexing and querying.

- **Real‑Time Results**  
  Leverages pre‑computed embeddings and NumPy vector operations to return top‑K matches in milliseconds.

- **Reliable Networking**  
  Custom JSON‑over‑TCP protocol with 4 KB chunking and end‑marker framing ensures robust communication.

- **Extensible Architecture**  
  Swap embedding models, similarity metrics, or storage backends with minimal changes. Built‑in logging and health checks simplify monitoring.

---

## 🔍 Key Components

| Component        | Description                                                      |
|------------------|------------------------------------------------------------------|
| **Web Interface**| Flask app (port 8000) for search UI and document management.     |
| **Master Server**| Orchestrates queries (port 5000), aggregates results, monitors workers. |
| **Worker Nodes** | Compute embeddings & similarities (ports 5001+), hold document shards, offer admin ports (6001+). |

---

## ⚙️ Core Workflows

### 1. Indexing & Embedding
1. **Ingest**: Documents sent to worker admin ports.  
2. **Embed**: Workers compute and normalize 384‑dim vectors via `sentence_transformers`.  
3. **Store**: Embeddings held in NumPy array shards.

### 2. Query Processing
1. **Submit**: Client sends JSON query to master.  
2. **Broadcast**: Master forwards to all workers.  
3. **Search**: Workers compute query embedding, dot‑product with shard embeddings, pick top K.  
4. **Merge**: Master merges and re‑ranks worker results, returns final top K.

---

## 📡 Network Protocol

- **Format**: JSON over TCP, 4 KB chunked, `END_MARKER` delimiter.  
- **Flows**:  
  - **Search**: Client → Master → Workers → Master → Client  
  - **Admin**: Client → Worker Admin → Worker

---

## 🔍 Usage Example

**Request:**  
```json
{
  "type": "search",
  "query": "machine learning trends",
  "top_k": 5
}
