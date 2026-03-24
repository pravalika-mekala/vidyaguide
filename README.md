# VidyaGuide 🚀 

**VidyaGuide** is a premium, AI-driven career companion designed to humanize the job search process. By combining advanced AI insights with a person-centric landing experience, VidyaGuide helps students and professionals find their career confidence through resume analysis, personalized job matching, and real-time AI assistance.

![VidyaGuide Hero Image](static/images/hero-human.png)

## ✨ Key Features

- **Human-Centric Landing Page**: A warm, welcoming entry experience that focuses on user benefits and career support.
- **AI Assistant (Gemini 1.5 Pro/Flash)**: A highly specialized AI tutor and career coach that provides interview tips, networking advice, and technical guidance.
- **Resume Analyzer**: Real-time feedback on your professional profile with automated job role predictions.
- **True Black UI**: A premium, high-contrast "True Black" (#000000) aesthetic with vibrant emerald and mint green accents.
- **Secure Authentication**: Robust OTP-based login and password recovery to ensure your career data is protected.
- **Responsive Design**: Seamlessly shifts between "True Black" and "Vibrant Light" themes to suit your work environment.

## 🛠️ Tech Stack

- **Backend**: Python 3.9+, FastAPI, Uvicorn
- **Database**: MySQL (Primary), SQLite (Development fallback)
- **AI Engine**: Google Gemini AI (Generative AI SDK)
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (ES6+), Bootstrap 5
- **Security**: Passlib (Bcrypt), Dotenv, OTP-Rate Limiting

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.9 or higher
- MySQL Server (Optional, if using production settings)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/yourusername/vidyaguide.git
cd vidyaguide

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup
Copy the `.env.example` file to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
Ensure you provide your **GEMINI_API_KEY** and **SMTP** details for full functionality.

### 4. Running the Application
```bash
python main.py
# or
uvicorn app.main:app --reload
```
Visit `http://localhost:8000` in your browser.

## 🛡️ Security
This project uses a strict `.env` configuration for all sensitive information. Make sure never to commit your `.env` file! A comprehensive `.gitignore` is provided to protect your secrets.

---
*Built with ❤️ to empower the next generation of professionals.*
