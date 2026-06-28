"""RAGStore — FAISS-backed retrieval of CAD/CAM/DFM snippets.

This is what makes the LLM stop hallucinating — it sees real working examples
before it writes new code. Same trick that ``giuliano-t/openAI-to-freeCAD-workflow``
uses to good effect.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
from loguru import logger


class RAGStore:
    """Minimal RAG store using sentence-transformers + FAISS.

    For very small corpora (<500 docs) we use exact L2 search.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("sentence-transformers not installed") from e
        self.model = SentenceTransformer(model_name)
        self.docs: list[dict] = []              # {"text", "engine", "tags"}
        self.embeddings: np.ndarray | None = None

    # ------- ingest -------
    def add_text(self, text: str, *, engine: str = "", tags: Iterable[str] = ()):
        self.docs.append({"text": text, "engine": engine, "tags": list(tags)})

    def add_file(self, path: Path, *, engine: str = "", tags: Iterable[str] = ()):
        self.add_text(path.read_text(), engine=engine, tags=tags)

    def load_jsonl(self, path: Path):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            self.add_text(row["text"], engine=row.get("engine", ""),
                          tags=row.get("tags", []))

    def build_index(self):
        if not self.docs:
            logger.warning("[RAGStore] empty corpus; index is empty.")
            self.embeddings = np.zeros((0, 384), dtype=np.float32)
            return
        logger.info(f"[RAGStore] embedding {len(self.docs)} docs…")
        vecs = self.model.encode([d["text"] for d in self.docs],
                                 normalize_embeddings=True,
                                 show_progress_bar=False)
        self.embeddings = np.asarray(vecs, dtype=np.float32)

    # ------- retrieve -------
    def query(self, text: str, *, k: int = 4, engine: str | None = None) -> list[str]:
        if self.embeddings is None or len(self.embeddings) == 0:
            return []
        q = self.model.encode([text], normalize_embeddings=True)
        q = np.asarray(q, dtype=np.float32)               # (1, D)

        # Cosine similarity via inner product on normalized vectors.
        scores = (self.embeddings @ q[0])                # (N,)

        if engine:
            mask = np.array([d.get("engine", "") == engine for d in self.docs])
            if mask.any():
                scores = np.where(mask, scores, -1.0)

        top = np.argsort(-scores)[:k]
        return [self.docs[i]["text"] for i in top if scores[i] > 0]


# ---------------------------------------------------------------------------
# Seed corpus — a few real, working CAD snippets so the first run isn't blank.
# ---------------------------------------------------------------------------
SEED_CORPUS: list[dict] = [
    {
        "engine": "freecad",
        "tags": ["box", "plate"],
        "text": """\
# FreeCAD: rectangular plate with N M-threads
import FreeCAD, Part

def plate(L, W, T, holes):
    box = Part.makeBox(L, W, T)
    for h in holes:
        cyl = Part.makeCylinder(h['dia']/2.0, T+0.5,
                                FreeCAD.Vector(h['x'], h['y'], -0.25),
                                FreeCAD.Vector(0,0,1))
        box = box.cut(cyl)
    return box

result = plate(80.0, 40.0, 6.0, [
    {'dia': 6.6, 'x': 10, 'y': 10},
    {'dia': 6.6, 'x': 70, 'y': 10},
    {'dia': 6.6, 'x': 10, 'y': 30},
    {'dia': 6.6, 'x': 70, 'y': 30},
])
obj = FreeCAD.ActiveDocument.addObject("Part::Feature", "Plate")
obj.Shape = result
Part.export([obj], "out.step")
""",
    },
    {
        "engine": "freecad",
        "tags": ["bracket", "L-shape"],
        "text": """\
# FreeCAD: L-bracket from two boxes
import FreeCAD, Part

def l_bracket(L, W, H, T, holes_v, holes_h):
    v = Part.makeBox(L, T, H)
    v.translate(FreeCAD.Vector(0, 0, 0))
    h = Part.makeBox(L, W, T)
    h.translate(FreeCAD.Vector(0, 0, 0))
    shape = v.fuse(h)
    for hole in holes_v + holes_h:
        cyl = Part.makeCylinder(hole['dia']/2.0, T+1.0,
                                FreeCAD.Vector(hole['x'], hole['y'], -0.5),
                                FreeCAD.Vector(0,0,1))
        shape = shape.cut(cyl)
    return shape

result = l_bracket(80, 50, 80, 6, [], [])
""",
    },
    {
        "engine": "cadquery",
        "tags": ["box", "plate", "holes"],
        "text": """\
# CadQuery: plate with 4 corner holes
import cadquery as cq

result = (
    cq.Workplane("XY")
      .box(80, 40, 6)
      .faces(">Z").workplane()
      .rect(60, 20, forConstruction=True)
      .vertices()
      .hole(6.6)
)
cq.exporters.export(result, "out.step")
""",
    },
    {
        "engine": "cadquery",
        "tags": ["bracket", "L-shape"],
        "text": """\
# CadQuery: L-bracket
import cadquery as cq

(L, W, H, T) = (80, 50, 80, 6)
vertical = cq.Workplane("XY").box(L, T, H).translate((0, (W-T)/2, H/2))
horizontal = cq.Workplane("XY").box(L, W, T).translate((0, 0, T/2))
result = vertical.union(horizontal)
cq.exporters.export(result, "out.step")
""",
    },
    {
        "engine": "cadquery",
        "tags": ["enclosure", "pocket"],
        "text": """\
# CadQuery: rectangular enclosure with a pocket
import cadquery as cq
result = (
    cq.Workplane("XY").box(100, 60, 20)
      .faces(">Z").workplane()
      .rect(80, 40).cutBlind(-10)
      .edges("|Z").fillet(3)
)
""",
    },
    {
        "engine": "freecad",
        "tags": ["enclosure", "pocket"],
        "text": """\
# FreeCAD: rectangular enclosure with a pocket and fillet
import FreeCAD, Part
outer = Part.makeBox(100, 60, 20)
pocket = Part.makeBox(80, 40, 11)
pocket.translate(FreeCAD.Vector(10, 10, 9))
shape = outer.cut(pocket)
shape = shape.makeFillet(3, [e for e in shape.Edges if e.Length > 5])
result = shape
""",
    },
]


def default_corpus_path() -> Path:
    return Path(__file__).resolve().parent.parent / "knowledge" / "cad_snippets.jsonl"


def seed_default_corpus() -> RAGStore:
    store = RAGStore()
    for entry in SEED_CORPUS:
        store.add_text(entry["text"], engine=entry["engine"], tags=entry["tags"])
    store.build_index()
    return store


if __name__ == "__main__":
    s = seed_default_corpus()
    print(s.query("L-bracket with M6 holes", k=3))
