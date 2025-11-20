# 🧠 Job Application RAG Assistant

A **Retrieval-Augmented Generation (RAG)** system that helps you craft tailored **Key skills, cover letters, and email template** for AI/ML roles using your personal project documents and resumes as context.  
Built with **LangChain**, **Ollama (Llama 3.2:3B)**, and **Streamlit** — this assistant runs entirely **locally**, no external API needed.

## 🚀 Features

- 📂 **Document ingestion** – Upload and index your resumes, project summaries, and portfolios
- 🔍 **Vector-based retrieval** – Context-aware search using **ChromaDB**
- 🧩 **LLM-powered reasoning** – Uses **Llama 3.2 (3B)** via Ollama for smart, offline generation
- 💬 **Interactive Q&A** – Ask job-specific questions and get personalized answers
- 🖥️ **Streamlit interface** – Simple UI for interacting with your assistant
- 📘 **Jupyter support** – Test, debug, or fine-tune responses directly in notebooks

## 🧰 Tech Stack

| Component     | Description                         |
| ------------- | ----------------------------------- |
| **Ollama**    | Local LLM runner (Llama 3.2:3B)     |
| **LangChain** | RAG pipeline & prompt management    |
| **ChromaDB**  | Vector database for semantic search |
| **Streamlit** | Web UI for user interaction         |
| **Python**    | Core logic and orchestration        |
| **Jupyter**   | Experimentation & development       |

## 📁 Directory Structure

```
project_root/
│
├── data/
│   ├── chroma_db/          # Vector database storage
│   ├── sample/             # Sample documents
│   └── job_rag/
│       └── profile_docs/   # User resumes, project files
│
├── notebooks/              # Jupyter notebooks for testing
├── docs/                   # Architecture / design notes
├── src/
│   ├── rag/
│   │   ├── config/         # settings + profile definitions
│   │   ├── ingestion/      # loaders, chunking, preprocess, ingest orchestration
│   │   ├── vectorstore/    # Chroma client + schemas
│   │   ├── models/         # embedding + LLM clients
│   │   ├── retrieval/      # retriever + query pipeline
│   │   ├── generation/     # prompts + generator workflow
│   │   ├── evaluation/     # (future) eval + metrics
│   │   └── utils/          # text helpers, logging, etc.
│   └── ui/                 # Streamlit interface (app.py)
├── tests/
├── requirements.txt
├── README.md
└── .gitignore
```

## ⚙️ Setup Instructions

### 1️⃣ Clone the repository

```bash
git clone https://github.com/sheikhmunim/rag-job-assistant.git
cd job_application_rag
```

### 2️⃣ Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate   # on Mac/Linux
.\.venv\Scripts\activate   # on Windows
```

### 3️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

### 4️⃣ Install and start Ollama

```bash
# Download Ollama: https://ollama.ai/download
ollama pull llama3.2:3b
ollama serve
```

### 5️⃣ Run the app

```bash
streamlit run src/ui/app.py
```

### 6️⃣ (Optional) Personalize your profile

Use the in-app **Profile & Role Settings** panel (or edit `data/job_rag/profile_settings.json`) with your contact details, skills, and achievements so the generator can tailor the outputs.

### 🔧 Optional: Runtime overrides

Copy `.env.example` to `.env` and adjust values (e.g., `OLLAMA_HOST`, log level) without touching the codebase:

```bash
cp .env.example .env
# edit .env as needed
```

## 🧩 Configuration Files

- `src/rag/config/settings.yaml` – filesystem layout, chunking parameters, and retrieval defaults.
- `src/rag/config/model_config.yaml` – default embedding + LLM model names and Ollama host.
- `data/job_rag/profile_settings.json` – active persona data; edit via code or through the Streamlit **Profile & Role Settings** expander.

## 🧩 Environment Variables

| Variable      | Default                  | Description                  |
| ------------- | ------------------------ | ---------------------------- |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server endpoint |
| `MODEL_NAME`  | `llama3.2:3b`            | Model used for generation    |
| `DATA_DIR`    | `./data/sample`          | Input data directory         |
| `DB_DIR`      | `./data/chroma_db`       | Chroma database path         |

## 🧠 Example Queries

- “Generate a cover letter for a Machine Learning Engineer role at Canva.”
- “Summarize my experience with ROS2 and PDDL planning.”
- “Write a professional email to apply for an AI Engineer internship.”

## 🧑‍💻 Development Notes

- Jupyter notebooks can be used to prototype and test RAG chains.
- Streamlit is used for deployment-ready interactive UI.
- All data stays local — **no cloud APIs required**.

## 🪪 License

This project is released under the **MIT License** — free to use and modify with attribution.

## ✨ Author

**Sheikh Abdul Munim**
Master of Artificial Intelligence, RMIT University  
🔗 [LinkedIn](https://www.linkedin.com/in/sheikh-abdul-munim-b19391158/)  
🔗 [GitHub](https://github.com/sheikhmunim)
