from app.services.vision_manager import VisionManager
print("is_configured:", VisionManager.is_configured())
print("is_loaded:", VisionManager.is_loaded())
print("lm_studio_url:", VisionManager._lm_studio_url())
