# Megabyte Circuits Gerber Previewer & DFM Engine

FastAPI-based service for PCB Gerber file parsing, DFM (Design for Manufacturability) analysis, layer classification, 2D/3D PCB rendering, and interactive web visualization.

## Prerequisites

- Python 3.10+

## Local Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone git@github.com:hdpatel234/megabyte-circuits-gerber-previewer.git
   cd megabyte-circuits-gerber-previewer
   ```

2. **Create and activate Virtual Environment:**
   ```bash
   python -m venv venv
   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Development Server:**
   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. Access the API and Gerber Previewer:
   - Web App UI: http://127.0.0.1:8000/
   - API Docs (Swagger): http://127.0.0.1:8000/docs
