# RegulatoryRAG Directive

## What it is
A RAG (Retrieval-Augmented Generation) application that lets users upload any regulatory PDF and ask plain-English questions. Claude answers only from the document — never from training data — and cites the exact page numbers used in every response.

## Why it exists
Life sciences companies like Roivant, Pfizer, and Merck manage thousands of regulatory documents (FDA submissions, Warning Letters, ICH guidelines, clinical trial protocols). Finding specific information means manually searching hundreds of pages. RegulatoryRAG makes any document instantly queryable by anyone — no technical knowledge required.

## How it works (RAG pipeline)
1. **Ingest** — PDF is parsed with PyMuPDF, split into 800-character chunks with 15% overlap
2. **Index** — each chunk is vectorized using TF-IDF and stored in a local JSON index
3. **Retrieve** — user's question is vectorized, top 4 most similar chunks are retrieved via cosine similarity
4. **Generate** — Claude Sonnet receives only the retrieved chunks + the question, answers from document only
5. **Cite** — every answer includes the source page numbers

## Safety features
- **500-character guard**: if PDF extraction yields < 500 chars (scanned/image PDF), app shows a clear error instead of querying on garbage
- **Out-of-scope refusal**: Claude is instructed to say "I could not find the answer" rather than hallucinate from training data
- **Human-readable errors**: API connection failures and rate limits show plain-English messages, not stack traces
- **No external data**: the model only sees what's in your document

## Run locally
```bash
# Ingest a PDF (default: FDA Regulatory Procedures Manual)
python regulatory_qa/execution/ingest.py

# Launch the app
streamlit run regulatory_qa/execution/app.py
# Open: http://localhost:8501
```

## Tech stack
- Python, Streamlit, PyMuPDF, Anthropic Claude Sonnet
- No external vector database — lightweight JSON index for demo simplicity
- Production version would use pgvector or Pinecone for scale
