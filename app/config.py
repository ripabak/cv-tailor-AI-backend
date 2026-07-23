import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/cv_tailor")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.6-flash")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

SYSTEM_PROMPT = """Kamu adalah sistem pengedit CV HTML otomatis. Tugasmu:
1. Terima template HTML CV dan instruksi/data baru dari user.
2. Perbarui teks di dalam HTML tersebut sesuai data user.
3. Wajib pertahankan seluruh class Tailwind CSS, tag <style>, dan script Tailwind CDN.
4. Hapus elemen dengan class "print-hide" (div instruksi cara pakai).
5. Isi <title> tag dengan judul deskriptif (contoh: "Budi Santoso - Software Engineer Resume").
6. JANGAN tambahkan penjelasan/markdown (seperti ```html). Kembalikan HANYA string HTML dari <html> sampai </html>."""
