"""Secret-free version identity captured at submission and checked by workers."""
import hashlib
import os
from pathlib import Path
from .contracts import Mode, ResearchMode, VersionBundle, stable_hash


def execution_context(mode: Mode | str, research_mode: ResearchMode | str | None = None) -> dict:
    mode=Mode(mode)
    model='backtest-frozen-v1' if research_mode is None else ('quant-only-v1' if ResearchMode(research_mode)==ResearchMode.QUANT_ONLY else ('deterministic-demo-v1' if mode==Mode.DEMO else os.environ.get('LLM_MODEL','unavailable')))
    data_hash=None
    if mode==Mode.REAL:
        path=os.environ.get('REAL_DATA_PATH')
        if path:
            try:
                file=Path(path).expanduser()
                if file.is_dir():
                    file=file/'bundle.json'
                data_hash=hashlib.sha256(file.read_bytes()).hexdigest()
            except OSError:
                data_hash='UNAVAILABLE'
    return {'schema':1,'versions':VersionBundle().model_dump(mode='json'), 'model':model,
            'llm_endpoint_hash': stable_hash(os.environ.get('LLM_BASE_URL','https://api.openai.com/v1'))
                                 if mode==Mode.REAL and research_mode is not None and ResearchMode(research_mode)!=ResearchMode.QUANT_ONLY else None,
            'provider_bundle_hash':data_hash,
            'llm_concurrency':os.environ.get('LLM_CONCURRENCY','3') if mode==Mode.REAL and research_mode is not None else None,
            'llm_min_interval_seconds':os.environ.get('LLM_MIN_INTERVAL_SECONDS','0.2') if mode==Mode.REAL and research_mode is not None else None,'data_provider_version':'synthetic-v1' if mode==Mode.DEMO else 'verified-bundle-v1'}
