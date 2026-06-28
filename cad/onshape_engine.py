"""OnshapeEngine — pushes FeatureScript code to a Part Studio via REST API.

Reference: https://github.com/onshape-public/onshape-clients
           https://onshape-public.github.io/docs/api-intro/

This engine needs:
    ONSHAPE_ACCESS_KEY, ONSHAPE_SECRET_KEY (from cad.onshape.com → Dev Tools)
    An existing document + element (Part Studio) to inject FeatureScript into.

If the env vars are not set, ``execute()`` raises a clear error pointing the
user at the setup page.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from .base import CADEngine, CADGeometry, register_engine


@register_engine
class OnshapeEngine(CADEngine):
    name = "onshape"

    def __init__(self, base_url: str | None = None,
                 access_key: str | None = None,
                 secret_key: str | None = None):
        self.base = (base_url or os.getenv("ONSHAPE_BASE_URL",
                                           "https://cad.onshape.com")).rstrip("/")
        self.access = access_key or os.getenv("ONSHAPE_ACCESS_KEY", "")
        self.secret = secret_key or os.getenv("ONSHAPE_SECRET_KEY", "")
        self.doc_id = os.getenv("ONSHAPE_DOC_ID", "")
        self.element_id = os.getenv("ONSHAPE_ELEMENT_ID", "")

    def execute(self, script_path: Path, out_dir: Path) -> CADGeometry:
        if not (self.access and self.secret):
            raise RuntimeError(
                "Onshape keys not set — see .env.example "
                "(https://cad.onshape.com → Developer Tools)"
            )
        if not (self.doc_id and self.element_id):
            raise RuntimeError(
                "Onshape target document not set — set ONSHAPE_DOC_ID and "
                "ONSHAPE_ELEMENT_ID, or wire up a factory that creates a doc."
            )

        fs_source = script_path.read_text()
        client = _OnshapeClient(self.base, self.access, self.secret)
        client.create_featurescript_feature(self.doc_id, self.element_id, fs_source)
        # TODO: export STEP via /api/partstudios/d/{did}/e/{eid}/translations
        # For now we return a stub geometry pointing at the document.
        stub = out_dir / "onshape_reference.txt"
        stub.write_text(
            f"Onshape FeatureScript applied.\n"
            f"  doc:     {self.doc_id}\n"
            f"  element: {self.element_id}\n"
            f"  source:  {script_path}\n"
            f"\nOpen in browser: {self.base}/documents/{self.doc_id}/e/{self.element_id}\n"
        )
        return CADGeometry(
            step_path=stub, units="mm", bbox_mm=(0, 0, 0),
            metadata={"engine": "onshape", "remote": True},
        )


class _OnshapeClient:
    """Thin REST wrapper — only the endpoints we actually use."""

    def __init__(self, base: str, access_key: str, secret_key: str):
        self.base = base.rstrip("/")
        self.access = access_key
        self.secret = secret_key
        self._http = httpx.Client(timeout=60.0)

    def _sign(self, method: str, url: str, body: bytes = b"",
              content_type: str = "application/json") -> dict[str, str]:
        nonce = base64.b64encode(os.urandom(16)).decode()
        ts = str(int(time.time() * 1000))
        parsed = urllib.parse.urlparse(url)
        path_q = parsed.path
        if parsed.query:
            path_q += "?" + parsed.query
        hmac_msg = f"{method}\n{path_q}\n{ts}\n{nonce}\n".encode() + body
        sig = base64.b64encode(
            hmac.new(self.secret.encode(), hmac_msg, hashlib.sha256).digest()
        ).decode()
        return {
            "Authorization": f"On {self.access}:HmacSHA256:{sig}",
            "On-Nonce": nonce,
            "Date": ts,
            "Content-Type": content_type,
        }

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base}{path}"
        body = kwargs.pop("body", b"")
        headers = self._sign(method, url, body if isinstance(body, bytes) else b"")
        return self._http.request(method, url, headers=headers,
                                  content=body if isinstance(body, bytes) else None,
                                  **kwargs)

    def create_featurescript_feature(self, doc_id: str, element_id: str,
                                    fs_source: str) -> dict[str, Any]:
        """Inject a new FeatureScript feature into a Part Studio."""
        body = {
            "feature": {
                "type": 130,            # FeatureScript feature type
                "name": "JoyCADFeature",
                "featureScript": fs_source,
                "parameters": [],
            }
        }
        path = f"/api/partstudios/d/{doc_id}/e/{element_id}/features"
        r = self._req("POST", path, body=str(body).encode())
        r.raise_for_status()
        logger.info(f"[Onshape] FeatureScript applied ({len(fs_source)} chars).")
        return r.json()

    def export_step(self, doc_id: str, element_id: str, out_path: Path) -> Path:
        path = f"/api/partstudios/d/{doc_id}/e/{element_id}/translations"
        r = self._req("POST", path,
                      body=str({"formatName": "STEP",
                                "version": "1.0",
                                "destinationName": "joycad"}).encode())
        r.raise_for_status()
        url = r.json()["data"]["location"]
        with self._http.stream("GET", url) as resp:
            with out_path.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        return out_path
