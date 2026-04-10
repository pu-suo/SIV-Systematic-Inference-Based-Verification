# %% Cell 1: Setup
"""
# SIV: Systematic Inference-Based Verification

Interactive notebook for exploring SIV. Works on Google Colab and locally.

**No GPU required.** SIV uses the OpenAI API for extraction and generation.
All compilation, verification, and scoring runs on CPU.
"""
import subprocess, sys, os

# Install dependencies
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"])
subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm", "-q"])

# NLTK data
import nltk
for r in ['wordnet', 'averaged_perceptron_tagger_eng', 'punkt_tab', 'brown']:
    nltk.download(r, quiet=True)


# %% Cell 2: API Key
import os

# Option A: Set directly (for quick testing)
# os.environ["OPENAI_API_KEY"] = "sk-your-key-here"

# Option B: Colab Secrets
try:
    from google.colab import userdata
    os.environ["OPENAI_API_KEY"] = userdata.get("OPENAI_API_KEY")
    print("API key loaded from Colab Secrets.")
except Exception:
    pass

# Option C: .env file (handled by bootstrap)
import siv._bootstrap

key = os.environ.get("OPENAI_API_KEY", "")
print(f"OpenAI API key: {'SET' if key and not key.startswith('sk-your') else 'NOT SET — configure above'}")


# %% Cell 3: Vampire (optional)
from siv.vampire_interface import setup_vampire, is_vampire_available

if not is_vampire_available():
    setup_vampire()

print(f"Vampire available: {is_vampire_available()}")


# %% Cell 4: Inspect a sentence
# Shows what SIV "sees": extraction, compiled test suite, and optionally score a candidate.

sentence = "All employees who schedule meetings attend the company building."

# Run inspect via CLI
result = subprocess.run(
    [sys.executable, "-m", "siv", "inspect", sentence],
    capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)


# %% Cell 5: Inspect with candidate scoring
sentence = "All employees who schedule meetings attend the company building."
candidate = "(exists x.Employees(x)) & all x.(Employees(x) -> exists y.(Meetings(y) & Schedule(x,y) & Attend(x,companyBuilding)))"

result = subprocess.run(
    [sys.executable, "-m", "siv", "inspect", sentence, "--candidate", candidate],
    capture_output=True, text=True
)
print(result.stdout)


# %% Cell 6: Score existing FOL
import json, tempfile

problems = [{
    "problem_id": "demo_1",
    "premises": ["All dogs are mammals.", "All mammals breathe."],
    "candidates": {
        "gold": "all x.(Dog(x) -> Mammal(x))",
        "wrong": "exists x.(Dog(x) & Mammal(x))",
    }
}]

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(problems, f)
    input_path = f.name

result = subprocess.run(
    [sys.executable, "-m", "siv", "score", input_path, "--format", "human"],
    capture_output=True, text=True
)
print(result.stdout)


# %% Cell 7: Generate FOL (Clean-FOLIO)
import json, tempfile

problems = [{
    "problem_id": "demo_gen",
    "premises": ["All birds can fly.", "Penguins are birds."],
    "candidates": {
        "gold": "all x.(Bird(x) -> Fly(x))"
    }
}]

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(problems, f)
    input_path = f.name

result = subprocess.run(
    [sys.executable, "-m", "siv", "generate", input_path,
     "--compare-to-gold", "gold", "--format", "human"],
    capture_output=True, text=True
)
print(result.stdout)


# %% Cell 8: Full FOLIO evaluation (requires folio_problems.json)
import os
folio_path = os.path.join("data", "folio_problems.json")

if os.path.exists(folio_path):
    # Score gold annotations
    result = subprocess.run(
        [sys.executable, "-m", "siv", "score", folio_path, "--format", "json"],
        capture_output=True, text=True
    )
    scores = json.loads(result.stdout)
    print(f"Problems scored: {len(scores.get('problems', []))}")
    print(f"Grand total: {json.dumps(scores.get('grand_total', {}), indent=2)}")
else:
    print(f"FOLIO dataset not found at {folio_path}.")
    print("Place folio_problems.json in the data/ directory to run batch evaluation.")
