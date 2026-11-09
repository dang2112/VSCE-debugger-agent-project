# Document Retrieval MVP

## Overview

This module provides a simple document retrieval component for the larger debugging and RCA system.

The MVP currently assumes that the input document is a Markdown (`.md`) file stored locally. The location of the document is provided by `main.py`.

The module exposes four independent functions

1. Exact Search
2. BM25 Lexical Search
3. Sentence-BERT Semantic Search
4. Adaptive-K Result Selection

The retrieval methods are intentionally kept independent. The agent using this module decides which retrieval function to call based on the evidence it currently has.

For example, an agent may first perform an exact search for a function name. If the returned information is insufficient, it can then perform a BM25 search. If lexical matching still does not provide useful information, the agent may explicitly perform semantic search.

---

## Project Structure

```text
document_retrieval
├── exact_search.py
├── bm25_search.py
├── semantic_bert.py
├── adaptive_k.py
├── main.py
└── documents
    └── example.md
```

---

## Retrieval Flow

The module does not enforce a fixed retrieval pipeline.

Instead, each function is exposed independently to the calling agent.

```text
                  Agent
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
 Exact Search   BM25 Search   Semantic Search
        │           │           │
        └───────────┴───────────┘
                    │
                    ▼
               Adaptive-K
                    │
                    ▼
             Selected Evidence
```

A possible agent interaction is

```text
1. exact_search(...)
      ↓
   useful
      │
      ├── yes → use evidence
      │
      └── no
           ↓
2. bm25_search(...)
      ↓
   useful
      │
      ├── yes → use evidence
      │
      └── no
           ↓
3. semantic_search(...)
      ↓
4. adaptive_k(...)
```

However, this decision is made by the agent rather than by the retrieval module.

---

# 1. Exact Search

File

```text
exact_search.py
```

Exact Search performs literal matching against the Markdown document.

It is mainly intended for information that is expected to appear explicitly in documentation, such as

 function names
 class names
 constants
 API paths
 error names
 configuration values
 exact terminology

Example

```python
results = exact_search(
    file_path=documentsexample.md,
    query=process_payment,
    top_k=5
)
```

If the exact string appears in the document, matching chunks are returned.

Example query

```text
process_payment
```

Possible matching documentation

```text
The process_payment function validates the account before processing the transaction.
```

Exact search is deterministic and should normally be preferred when the agent already knows the exact identifier it is looking for.

---

# 2. BM25 Lexical Search

File

```text
bm25_search.py
```

BM25 provides lexical retrieval based on word overlap and term importance.

Unlike exact search, the entire query does not need to appear literally in the document.

Example

```python
results = bm25_search(
    file_path=documentsexample.md,
    query=payment account balance failure,
    top_k=5
)
```

A relevant document chunk may contain

```text
A transaction is rejected when the available account balance
is lower than the requested payment amount.
```

BM25 is useful when the agent knows the important terminology but does not know the exact wording used in the documentation.

The MVP uses

```text
rank-bm25
```

with `BM25Okapi`.

---

# 3. Sentence-BERT Semantic Search

File

```text
semantic_bert.py
```

Semantic Search retrieves document chunks according to their meaning rather than only their exact words.

The implementation uses the Sentence Transformers library with the following pretrained model

```text
sentence-transformersall-MiniLM-L6-v2
```

Example

```python
results = semantic_search(
    file_path=documentsexample.md,
    query=What happens when the customer does not have enough money,
    top_k=5
)
```

The documentation may instead contain

```text
A transaction must be rejected when the available account
balance is lower than the requested payment amount.
```

Although the wording differs significantly, Sentence-BERT can represent both texts as embeddings and determine that they have similar meanings.

Semantic search is useful when

 the query is expressed differently from the documentation
 lexical search produces irrelevant results
 the agent is searching for a concept rather than an identifier
 business rules are described using different terminology

Semantic search is not automatically called when BM25 fails.

The calling agent decides whether semantic retrieval is necessary.

---

# 4. Adaptive-K

File

```text
adaptive_k.py
```

Each retrieval function can return up to five candidate chunks.

However, always sending all five chunks to the RCA agent may introduce irrelevant information and increase context size.

Adaptive-K attempts to determine how many of the ranked results should actually be retained.

Input

```text
Top 5 retrieval results
```

Example

```text
Result 1    0.91
Result 2    0.88
Result 3    0.84
Result 4    0.40
Result 5    0.37
```

There is a large relevance drop between Result 3 and Result 4.

Adaptive-K may therefore return

```text
K = 3
```

Result

```text
Result 1
Result 2
Result 3
```

The MVP uses a simple heuristic based on relative score differences.

Adaptive-K is intentionally separated from the retrieval algorithms so it can operate on the output of whichever retrieval method the agent chooses.

---

# Markdown Document Handling

The MVP currently supports Markdown files only.

`main.py` provides the document path

```python
DOCUMENT_PATH = documentsexample.md
```

Each retrieval function receives the path directly

```python
exact_search(
    file_path=DOCUMENT_PATH,
    query=process_payment
)
```

The Markdown document is divided into chunks before retrieval.

For the MVP, chunks are separated primarily by Markdown headings.

Example

```markdown
# Payment Service

General payment documentation.

## Insufficient Balance

A payment must be rejected when the customer's account
does not contain enough funds.

## Authentication

Users must provide a valid access token.
```

This produces approximately

```text
Chunk 1
# Payment Service
...

Chunk 2
## Insufficient Balance
...

Chunk 3
## Authentication
...
```

More advanced chunking strategies can be introduced later.

---

# `main.py`

`main.py` acts as the local testing environment.

It is responsible for defining where the Markdown document is located.

Example

```python
DOCUMENT_PATH = documentsexample.md
```

Individual functions can then be tested independently

```python
exact_results = exact_search(
    DOCUMENT_PATH,
    process_payment
)

bm25_results = bm25_
```
Run this line before running the program
pip install rank-bm25 sentence-transformers torch