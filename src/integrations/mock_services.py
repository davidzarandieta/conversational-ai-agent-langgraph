import copy
from typing import Dict, Any, Optional, List


class MockMongoCollection:
    """
    Simulador en memoria de una colección PyMongo para testing autónomo y zero-dependency.
    Soporta find_one, find_one_and_update y update_one con operadores $set y $unset.
    """
    def __init__(self, initial_data: Optional[List[Dict[str, Any]]] = None):
        self._data: Dict[str, Dict[str, Any]] = {}
        if initial_data:
            for doc in initial_data:
                key = self._doc_key(doc)
                self._data[key] = copy.deepcopy(doc)

    def _doc_key(self, doc_or_filter: Dict[str, Any]) -> str:
        u = str(doc_or_filter.get("user_id", ""))
        c = str(doc_or_filter.get("client_id", ""))
        return f"{c}:{u}"

    def find_one(self, filter_doc: Dict[str, Any], projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        for item in self._data.values():
            if self._matches(item, filter_doc):
                res = copy.deepcopy(item)
                if projection:
                    filtered = {}
                    for k, v in projection.items():
                        if v == 1 and k in res:
                            filtered[k] = res[k]
                    return filtered
                return res
        return None

    def find_one_and_update(
        self, 
        filter_doc: Dict[str, Any], 
        update_doc: Dict[str, Any], 
        return_document: bool = True
    ) -> Optional[Dict[str, Any]]:
        for key, item in self._data.items():
            if self._matches(item, filter_doc):
                self._apply_updates(item, update_doc)
                return copy.deepcopy(item)
        return None

    def update_one(self, filter_doc: Dict[str, Any], update_doc: Dict[str, Any]) -> None:
        for key, item in self._data.items():
            if self._matches(item, filter_doc):
                self._apply_updates(item, update_doc)
                return

    def _matches(self, doc: Dict[str, Any], filter_doc: Dict[str, Any]) -> bool:
        for k, v in filter_doc.items():
            if k == "_id":
                continue
            if isinstance(v, dict):
                if "$ne" in v:
                    if doc.get(k) == v["$ne"]:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def _apply_updates(self, doc: Dict[str, Any], update_doc: Dict[str, Any]) -> None:
        if "$set" in update_doc:
            for k, v in update_doc["$set"].items():
                doc[k] = v
        if "$unset" in update_doc:
            for k in update_doc["$unset"].keys():
                doc.pop(k, None)
        if "$push" in update_doc:
            for k, v in update_doc["$push"].items():
                if k not in doc or not isinstance(doc[k], list):
                    doc[k] = []
                doc[k].append(v)


class MockAnthropicClient:
    """Mock para Anthropic API con soporte para prompt caching."""
    def __init__(self, default_response: Optional[Dict[str, Any]] = None):
        self.default_response = default_response or {
            "content_array": ["¡Hola! En qué puedo ayudarte hoy?"],
            "estado_conversacion": "2",
            "send_booking_link": False,
            "nuevos_aprendizajes": "Lead interesado en entrenamiento"
        }
        self.calls_count = 0

    async def complete(self, *args, **kwargs) -> Dict[str, Any]:
        self.calls_count += 1
        return copy.deepcopy(self.default_response)


class MockManyChatClient:
    """Mock para delivery de ManyChat / Meta Webhooks."""
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []

    async def send(self, client_profile: Dict[str, Any], user_id: str, messages: List[str]) -> bool:
        self.sent_messages.append({
            "client_id": client_profile.get("client_id"),
            "user_id": user_id,
            "messages": messages
        })
        return True
