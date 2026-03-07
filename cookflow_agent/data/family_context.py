"""
Firestore service for FamilyContext persistence.

Drop this file into cookflow_agent/data/family_context.py
Requires: google-cloud-firestore (add to requirements.txt)
"""

import os
from typing import Optional

from google.cloud import firestore

_COLLECTION = "cookflow_users"
_db = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return _db


def load_family_context(user_id: str) -> Optional[dict]:
    """
    Load FamilyContext from Firestore.
    Returns None if no record exists (first session or consent=False).
    """
    try:
        doc = _get_db().collection(_COLLECTION).document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception:
        return None


def save_family_context(user_id: str, context: dict) -> bool:
    """
    Save FamilyContext to Firestore.
    Only call this after the user has explicitly consented to data storage.
    Uses merge=True so partial updates don't wipe existing fields.
    """
    try:
        _get_db().collection(_COLLECTION).document(user_id).set(context, merge=True)
        return True
    except Exception:
        return False


def delete_family_context(user_id: str) -> bool:
    """
    Delete FamilyContext from Firestore.
    Call this when a user withdraws consent mid-session.
    """
    try:
        _get_db().collection(_COLLECTION).document(user_id).delete()
        return True
    except Exception:
        return False
