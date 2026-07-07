from app.services.document_processing_core import _LazyOCREngine
e = _LazyOCREngine()
engine = e._load()
print("Engine type:", type(engine))
print("Has extract:", hasattr(engine, "extract"))
print("Engine:", repr(engine))
