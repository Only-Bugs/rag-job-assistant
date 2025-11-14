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

| Component     | Description                          |
|---------------|--------------------------------------|
| **Ollama**    | Local LLM runner (Llama 3.2:3B)      |
| **LangChain** | RAG pipeline & prompt management     |
| **ChromaDB**  | Vector database for semantic search  |
| **Streamlit** | Web UI for user interaction          |
| **Python**    | Core logic and orchestration         |
| **Jupyter**   | Experimentation & development        |

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
├── app/                    # Streamlit app (main interface)
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
streamlit run app/main.py
```

## 🧩 Environment Variables

| Variable        | Default                   | Description                      |
|-----------------|---------------------------|----------------------------------|
| `OLLAMA_HOST`   | `http://localhost:11434`  | Local Ollama server endpoint     |
| `MODEL_NAME`    | `llama3.2:3b`             | Model used for generation        |
| `DATA_DIR`      | `./data/sample`           | Input data directory             |
| `DB_DIR`        | `./data/chroma_db`        | Chroma database path             |

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
