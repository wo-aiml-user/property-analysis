# FastAPI Project Setup Guide

## Prerequisites

Ensure you have the following installed:
- **Python 3.8+**
- **pip** (Python package manager)
- **virtualenv** (optional but recommended)

---

## 🚀 Setup Instructions

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/your-repo/your-project.git
cd your-project
```

### 2️⃣ Create a Virtual Environment
#### Windows
```powershell
python -m venv venv
venv\Scripts\activate
```

#### Linux / macOS
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 💻 Running the Server
```bash
python uvicorn_config.py
```

---

## 🚀 Running in Production

### **Using Gunicorn with Config File**

A `uvicorn_config.py` file is already included for configuring Uviicorn. Run the following command to start the production server:

```bash
python uvicorn_config.py
```

---

## 🔧 Environment Variables
You can configure environment-specific settings using a `.env` file.

Create a **.env** file in the project root:
```ini
APP_NAME=FastAPI App
DEBUG=True
HOST=0.0.0.0
PORT=8000
```

---


## ✅ API Documentation
Once the server is running, access the API docs:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)