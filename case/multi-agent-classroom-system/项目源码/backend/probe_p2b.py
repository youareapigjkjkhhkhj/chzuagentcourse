import json
import os

from app import create_app

app = create_app()
with app.app_context():
    from app.services.provider_registry import get_registry
    from app.services.voice import prefs
    reg = get_registry()
    out = {}
    out["env"] = {k: os.environ.get(k, "") for k in ("VOLC_TTS_API_KEY", "VOLC_TTS_ENDPOINT", "VOLC_REALTIME_API_KEY", "VOLC_REALTIME_ENDPOINT", "VOICE_ENABLED")}
    out["default_tts"] = reg.default_name("tts")
    out["default_realtime"] = reg.default_name("realtime")
    for kind in ("tts", "realtime", "asr"):
        try:
            p = reg.current(kind)
            out[f"current_{kind}"] = {"name": p.name, "configured": bool(p.configured), "missing": list(getattr(p, "missing", []) or [])}
        except Exception as exc:
            out[f"current_{kind}"] = f"{type(exc).__name__}({getattr(exc, 'code', '')}): {exc}"
    for label, fn in (("tts_provider", prefs.tts_provider), ("tts_or_none", prefs.tts_provider_or_none), ("realtime_provider", prefs.realtime_provider)):
        try:
            p = fn()
            out[label] = getattr(p, "name", None)
        except Exception as exc:
            out[label] = f"{type(exc).__name__}({getattr(exc, 'code', '')}): {exc}"
    from app.models.voice_profile import VoiceProfile
    try:
        out["profiles"] = [{"id": r.id, "provider": r.provider, "voiceType": r.voice_type} for r in VoiceProfile.query.all()]
    except Exception as exc:
        out["profiles"] = f"{type(exc).__name__}"
    print("PROBE " + json.dumps(out, ensure_ascii=False))
