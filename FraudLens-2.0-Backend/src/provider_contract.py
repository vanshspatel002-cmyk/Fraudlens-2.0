"""Non-sensitive fingerprints binding the one-off schema correction probe."""
import hashlib
import json

SCHEMA_WIRE_VERSION = 'json_schema_v1'
SCHEMA_CORRECTION_COMMIT = '8a534bf5388769c0eed8281de5da184f2bf3572d'
SCHEMA_CORRECTION_ID = 'legacy-schema-to-json-schema-2026-10-22-v1'


def structured_image_contract(schema, image_hash, prompt, model, request_profile):
    """Hash data/schema, never credentials; transport and gate use this function."""
    return {
        'wire_version': SCHEMA_WIRE_VERSION,
        'schema_sha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
        'image_sha256': image_hash,
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'model': model,
        'request_profile': request_profile,
    }


def perception_correction_contract(image_hash, model, request_profile):
    from .perception import PerceptionObservation, PERCEPTION_PROMPT
    return structured_image_contract(PerceptionObservation.model_json_schema(),
        image_hash, PERCEPTION_PROMPT, model, request_profile)
