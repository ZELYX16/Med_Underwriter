from sentence_transformers import SentenceTransformer
import time

print("Loading model...", flush=True)

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
model.max_seq_length = 256

text = """
Type 2 diabetes mellitus is a chronic metabolic condition characterized
by elevated blood glucose levels. Hypertension refers to persistently
elevated blood pressure. Coronary artery disease affects the coronary
arteries and may increase cardiovascular risk.
"""

print("Model loaded.", flush=True)

start = time.time()

embedding = model.encode(
    [text],
    batch_size=1,
    show_progress_bar=True,
    convert_to_numpy=True,
    normalize_embeddings=True,
)

print("Embedding complete.", flush=True)
print("Shape:", embedding.shape)
print("Time:", round(time.time() - start, 2), "seconds")